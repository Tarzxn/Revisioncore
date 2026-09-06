from flask import Flask, render_template, jsonify, request, send_file, Response, stream_with_context, session
import json, os, uuid, socket, io, urllib.request, urllib.error, urllib.parse, sqlite3
from functools import wraps
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
# On Render, set a SECRET_KEY env var so sessions survive restarts/redeploys.
app.secret_key = os.environ.get('SECRET_KEY', 'dev-only-change-me-in-render-env-vars')

DATA_DIR      = 'data'
QUIZZES_FILE  = os.path.join(DATA_DIR, 'quizzes.json')   # shared curriculum bank — same for everyone, fine as a file
SETTINGS_FILE = os.path.join(DATA_DIR, 'settings.json')  # legacy Ollama/OpenRouter config — no longer used by the AI Tutor
LOCAL_DB_FILE = os.path.join(DATA_DIR, 'revisioncore.db')

SUBJECT_IDS = ['biology','chemistry','physics','maths','computer_science',
                'english','history','geography','french','spanish','german']

# ── Defaults ──────────────────────────────────────────────────────────────────
OLLAMA_BASE  = 'http://127.0.0.1:11434'
OLLAMA_MODEL = 'llama3.2'

OPENROUTER_API_URL = 'https://openrouter.ai/api/v1/chat/completions'

OPENROUTER_MODELS = {
    'google/gemini-2.0-flash-exp:free':     'Gemini 2.0 Flash (free)',
    'google/gemini-flash-1.5':              'Gemini 1.5 Flash (fast)',
    'meta-llama/llama-3.3-70b-instruct':    'Llama 3.3 70B (free)',
    'meta-llama/llama-3.1-8b-instruct:free':'Llama 3.1 8B (free)',
    'mistralai/mistral-7b-instruct:free':   'Mistral 7B (free)',
    'anthropic/claude-3.5-haiku':           'Claude 3.5 Haiku',
    'anthropic/claude-3.5-sonnet':          'Claude 3.5 Sonnet',
    'openai/gpt-4o-mini':                   'GPT-4o Mini',
    'openai/gpt-4o':                        'GPT-4o',
    'deepseek/deepseek-r1:free':            'DeepSeek R1 (free)',
}

os.makedirs(DATA_DIR, exist_ok=True)

# ══════════════════════════════════════════════════════════════════════════════
#  DATABASE — real, persistent storage for accounts + all per-user data.
#
#  If a DATABASE_URL env var is set (a free Neon/Supabase Postgres URL), that
#  is used — this is what makes data survive Render redeploys. Otherwise it
#  falls back to a local SQLite file, which is fine for localhost but will be
#  wiped on every Render redeploy since Render's disk is not persistent.
# ══════════════════════════════════════════════════════════════════════════════
DATABASE_URL = os.environ.get('DATABASE_URL')
IS_PG = bool(DATABASE_URL)

if IS_PG:
    import psycopg2
    import psycopg2.extras

def get_db():
    if IS_PG:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    else:
        conn = sqlite3.connect(LOCAL_DB_FILE)
        conn.row_factory = sqlite3.Row
    return conn

def db_execute(conn, sql, params=()):
    """Run a query written in %s-placeholder (Postgres) style on either backend."""
    if IS_PG:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    else:
        cur = conn.cursor()
        sql = sql.replace('%s', '?')
    cur.execute(sql, params)
    return cur

def init_db():
    conn = get_db()
    id_col = 'SERIAL PRIMARY KEY' if IS_PG else 'INTEGER PRIMARY KEY AUTOINCREMENT'
    blob_type = 'BYTEA' if IS_PG else 'BLOB'
    db_execute(conn, f'''CREATE TABLE IF NOT EXISTS users (
        id {id_col},
        username TEXT UNIQUE NOT NULL,
        email TEXT,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL
    )''')
    # Generic per-user JSON store — replaces the old data/*.json files with
    # rows that live in the (persistent) database instead of local disk.
    db_execute(conn, '''CREATE TABLE IF NOT EXISTS user_store (
        user_id TEXT NOT NULL,
        store_name TEXT NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (user_id, store_name)
    )''')
    # Uploaded revision-guide PDFs, stored as bytes in the DB (not on disk)
    # so they also survive redeploys.
    db_execute(conn, f'''CREATE TABLE IF NOT EXISTS guide_files (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        filename TEXT NOT NULL,
        content {blob_type} NOT NULL
    )''')
    conn.commit()
    conn.close()

init_db()

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('user_id'):
            return jsonify({"error": "Not logged in"}), 401
        return fn(*args, **kwargs)
    return wrapper

def current_user_id():
    return str(session.get('user_id'))

def default_progress():
    return {"subjects": {sub: {"score":0,"quizzes_completed":0,"cards_mastered":0} for sub in SUBJECT_IDS},
            "total_xp":0, "streak":0, "last_active":""}

# ── Per-user JSON store (backed by the DB — Postgres in production) ───────────
def get_store(uid, name, default):
    conn = get_db()
    row = db_execute(conn, 'SELECT data FROM user_store WHERE user_id=%s AND store_name=%s', (uid, name)).fetchone()
    conn.close()
    if not row: return default
    return json.loads(row['data'])

def set_store(uid, name, value):
    conn = get_db()
    data = json.dumps(value)
    if IS_PG:
        db_execute(conn, '''INSERT INTO user_store (user_id, store_name, data) VALUES (%s,%s,%s)
                             ON CONFLICT (user_id, store_name) DO UPDATE SET data = EXCLUDED.data''',
                   (uid, name, data))
    else:
        db_execute(conn, '''INSERT INTO user_store (user_id, store_name, data) VALUES (%s,%s,%s)
                             ON CONFLICT (user_id, store_name) DO UPDATE SET data = excluded.data''',
                   (uid, name, data))
    conn.commit()
    conn.close()

def new_user_defaults(uid):
    """Seed the demo flashcard sets + empty progress/guides/memorise for a freshly registered user."""
    uid = str(uid)
    set_store(uid, 'guides', [])
    set_store(uid, 'annotations', {})
    set_store(uid, 'memorise', [])
    set_store(uid, 'progress', default_progress())
    starter_sets = [
        {"id":str(uuid.uuid4())[:8],"name":"Cell Biology","subject":"biology","cards":[
            {"question":"What is the powerhouse of the cell?","answer":"Mitochondria"},
            {"question":"What process do plants use to make food?","answer":"Photosynthesis"},
            {"question":"What is DNA?","answer":"Deoxyribonucleic acid — carries genetic information"}]},
        {"id":str(uuid.uuid4())[:8],"name":"Basic Elements","subject":"chemistry","cards":[
            {"question":"What is H2O?","answer":"Water"},
            {"question":"Atomic number of Carbon?","answer":"6"},
            {"question":"Three states of matter?","answer":"Solid, Liquid, Gas"}]},
    ]
    set_store(uid, 'sets', starter_sets)

def _read_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        try: return json.load(f)
        except Exception: return default

def _write_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

# ── Settings helpers (legacy Ollama/OpenRouter panel only) ────────────────────
def get_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    return {
        'provider':        'ollama',       # 'ollama' | 'openrouter'
        'openrouter_key':   '',
        'openrouter_model': 'google/gemini-2.0-flash-exp:free',
        'ollama_model':     'llama3.2',
    }

def save_settings(s):
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(s, f, indent=2)

# ── Data init ─────────────────────────────────────────────────────────────────
def init_data():
    # Shared curriculum quiz bank (same practice questions for everyone) — this
    # is static seed content, not per-user data, so a plain file is fine.
    if not os.path.exists(QUIZZES_FILE):
        base = {
            "biology":  [{"question":"What is photosynthesis?","options":["How plants make food","How animals breathe","Cell division","DNA replication"],"correct":0},
                          {"question":"Largest organ in the human body?","options":["Heart","Brain","Liver","Skin"],"correct":3}],
            "chemistry":[{"question":"Chemical symbol for Gold?","options":["Go","Gd","Au","Ag"],"correct":2},
                          {"question":"Neutral pH level?","options":["0","7","14","1"],"correct":1}],
            "physics":  [{"question":"Gravity on Earth?","options":["9.8 m/s²","10 m/s","5 m/s²","15 m/s²"],"correct":0}],
            "maths":    [{"question":"15% of 200?","options":["20","25","30","35"],"correct":2}],
        }
        for sub in SUBJECT_IDS:
            base.setdefault(sub, [])
        _write_json(QUIZZES_FILE, base)
    else:
        # Make sure newly-added subjects have (at least empty) quiz lists
        quizzes = _read_json(QUIZZES_FILE, {})
        changed = False
        for sub in SUBJECT_IDS:
            if sub not in quizzes:
                quizzes[sub] = []; changed = True
        if changed: _write_json(QUIZZES_FILE, quizzes)

init_data()

# ══════════════════════════════════════════════════════════════════════════════
#  AI PROVIDER ABSTRACTION
# ══════════════════════════════════════════════════════════════════════════════

# ── Ollama ────────────────────────────────────────────────────────────────────
def ollama_request(endpoint, payload=None, timeout=5):
    url  = f"{OLLAMA_BASE}{endpoint}"
    data = json.dumps(payload).encode() if payload else None
    req  = urllib.request.Request(url, data=data, headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def ollama_generate(prompt, system, model):
    result = ollama_request('/api/generate', {
        "model": model, "prompt": prompt, "system": system, "stream": False
    }, timeout=120)
    return result.get("response","").strip()

def ollama_stream_gen(prompt, system, model):
    payload = json.dumps({"model":model,"prompt":prompt,"system":system,"stream":True}).encode()
    req = urllib.request.Request(f"{OLLAMA_BASE}/api/generate", data=payload,
                                 headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            for raw in r:
                line = raw.decode().strip()
                if not line: continue
                try:
                    obj   = json.loads(line)
                    token = obj.get("response","")
                    done  = obj.get("done", False)
                    if token: yield f"data: {json.dumps({'chunk':token})}\n\n"
                    if done:  yield "data: [DONE]\n\n"; return
                except: continue
    except Exception as e:
        yield f"data: {json.dumps({'error':str(e)})}\n\n"

# ── OpenRouter ────────────────────────────────────────────────────────────────
def openrouter_generate(prompt, system, api_key, model):
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system",  "content": system},
            {"role": "user",    "content": prompt}
        ],
        "max_tokens": 2048,
        "temperature": 0.7
    }).encode()
    req = urllib.request.Request(
        OPENROUTER_API_URL,
        data=body,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer":  "http://127.0.0.1:5000",
            "X-Title":       "RevisionCore"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
            return data['choices'][0]['message']['content'].strip()
    except urllib.error.HTTPError as e:
        err = json.loads(e.read())
        raise RuntimeError(err.get('error', {}).get('message', str(e)))

def openrouter_stream_gen(prompt, system, api_key, model):
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt}
        ],
        "max_tokens": 2048,
        "temperature": 0.7,
        "stream": True
    }).encode()
    req = urllib.request.Request(
        OPENROUTER_API_URL,
        data=body,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer":  "http://127.0.0.1:5000",
            "X-Title":       "RevisionCore"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            for raw in r:
                line = raw.decode('utf-8', errors='replace').strip()
                if not line or not line.startswith('data:'): continue
                data_str = line[5:].strip()
                if data_str == '[DONE]':
                    yield "data: [DONE]\n\n"; return
                try:
                    obj   = json.loads(data_str)
                    delta = obj['choices'][0].get('delta', {})
                    token = delta.get('content', '')
                    if token: yield f"data: {json.dumps({'chunk': token})}\n\n"
                    if obj['choices'][0].get('finish_reason') in ('stop', 'length'):
                        yield "data: [DONE]\n\n"; return
                except: continue
    except urllib.error.HTTPError as e:
        err_body = e.read().decode()
        yield f"data: {json.dumps({'error': err_body[:300]})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"

# ── Unified interface ─────────────────────────────────────────────────────────
def ai_generate(prompt, system="You are a helpful GCSE revision tutor."):
    s = get_settings()
    if s['provider'] == 'openrouter':
        if not s.get('openrouter_key'):
            raise RuntimeError("No OpenRouter API key set. Go to AI Settings to add one.")
        return openrouter_generate(prompt, system, s['openrouter_key'], s['openrouter_model'])
    else:
        return ollama_generate(prompt, system, s.get('ollama_model', OLLAMA_MODEL))

def ai_stream(prompt, system="You are a helpful GCSE revision tutor."):
    s = get_settings()
    if s['provider'] == 'gemini':
        if not s.get('gemini_key'):
            yield f"data: {json.dumps({'error':'No Gemini API key set. Go to AI Settings.'})}\n\n"
            return
        yield from gemini_stream_gen(prompt, system, s['gemini_key'], s['gemini_model'])
    else:
        yield from ollama_stream_gen(prompt, system, s.get('ollama_model', OLLAMA_MODEL))

def make_stream_response(prompt, system):
    return Response(stream_with_context(ai_stream(prompt, system)),
                    mimetype='text/event-stream',
                    headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})

# ══════════════════════════════════════════════════════════════════════════════
#  ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/')
def index(): return render_template('index.html')

# ── Auth ──────────────────────────────────────────────────────────────────────
@app.route('/api/auth/register', methods=['POST'])
def auth_register():
    data     = request.json or {}
    username = (data.get('username') or '').strip()
    email    = (data.get('email') or '').strip()
    password = data.get('password') or ''
    if not username or len(username) < 3:
        return jsonify({"error":"Username must be at least 3 characters"}), 400
    if len(password) < 6:
        return jsonify({"error":"Password must be at least 6 characters"}), 400
    conn = get_db()
    try:
        cur = db_execute(conn,
            'INSERT INTO users (username, email, password_hash, created_at) VALUES (%s,%s,%s,%s)' + (' RETURNING id' if IS_PG else ''),
            (username, email, generate_password_hash(password), datetime.now().isoformat()))
        if IS_PG:
            uid = cur.fetchone()['id']
        else:
            uid = cur.lastrowid
        conn.commit()
    except (sqlite3.IntegrityError, Exception) as e:
        conn.rollback() if IS_PG else None
        conn.close()
        if 'unique' in str(e).lower() or isinstance(e, sqlite3.IntegrityError):
            return jsonify({"error":"That username is already taken"}), 400
        return jsonify({"error": f"Could not create account: {e}"}), 500
    conn.close()
    new_user_defaults(uid)
    session['user_id'] = uid
    session['username'] = username
    return jsonify({"status":"success","user":{"id":uid,"username":username}})

@app.route('/api/auth/login', methods=['POST'])
def auth_login():
    data     = request.json or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    conn = get_db()
    row  = db_execute(conn, 'SELECT * FROM users WHERE username=%s', (username,)).fetchone()
    conn.close()
    if not row or not check_password_hash(row['password_hash'], password):
        return jsonify({"error":"Incorrect username or password"}), 401
    session['user_id']  = row['id']
    session['username'] = row['username']
    return jsonify({"status":"success","user":{"id":row['id'],"username":row['username']}})

@app.route('/api/auth/logout', methods=['POST'])
def auth_logout():
    session.clear()
    return jsonify({"status":"success"})

@app.route('/api/auth/me')
def auth_me():
    if not session.get('user_id'):
        return jsonify({"logged_in": False}), 401
    return jsonify({"logged_in": True, "user": {"id": session['user_id'], "username": session['username']}})

# ── Settings ──────────────────────────────────────────────────────────────────
@app.route('/api/settings', methods=['GET'])
def get_settings_route():
    s = get_settings()
    # Never send the full API key to the frontend — just whether it's set
    safe = dict(s)
    if safe.get('openrouter_key'):
        key = safe['openrouter_key']
        safe['openrouter_key_preview'] = f"{key[:6]}…{key[-4:]}" if len(key) > 10 else '(set)'
        safe['openrouter_key_set'] = True
    else:
        safe['openrouter_key_preview'] = ''
        safe['openrouter_key_set'] = False
    safe.pop('openrouter_key', None)  # never send to frontend
    safe['openrouter_models'] = OPENROUTER_MODELS
    return jsonify(safe)

@app.route('/api/settings', methods=['POST'])
def save_settings_route():
    data = request.json
    s    = get_settings()
    if 'provider'         in data: s['provider']         = data['provider']
    if 'openrouter_model' in data: s['openrouter_model'] = data['openrouter_model']
    if 'ollama_model'     in data: s['ollama_model']     = data['ollama_model']
    if 'openrouter_key'   in data and data['openrouter_key'].strip():
        s['openrouter_key'] = data['openrouter_key'].strip()
    elif 'clear_openrouter_key' in data and data['clear_openrouter_key']:
        s['openrouter_key'] = ''
    save_settings(s)
    return jsonify({"status":"success"})

# ── Flashcard sets ────────────────────────────────────────────────────────────
@app.route('/api/sets', methods=['GET'])
@login_required
def get_sets():
    return jsonify(get_store(current_user_id(), 'sets', []))

@app.route('/api/sets', methods=['POST'])
@login_required
def create_set():
    data = request.json
    uid = current_user_id()
    sets = get_store(uid, 'sets', [])
    new_set = {"id":str(uuid.uuid4())[:8],"name":data.get('name','Untitled'),
               "subject":data.get('subject','general'),"cards":data.get('cards',[])}
    sets.append(new_set)
    set_store(uid, 'sets', sets)
    return jsonify({"status":"success","set":new_set})

@app.route('/api/sets/<set_id>', methods=['PUT'])
@login_required
def update_set(set_id):
    data = request.json
    uid = current_user_id()
    sets = get_store(uid, 'sets', [])
    for s in sets:
        if s['id'] == set_id:
            s.update({k:data[k] for k in ('name','subject','cards') if k in data})
    set_store(uid, 'sets', sets)
    return jsonify({"status":"success"})

@app.route('/api/sets/<set_id>', methods=['DELETE'])
@login_required
def delete_set(set_id):
    uid = current_user_id()
    sets = [s for s in get_store(uid, 'sets', []) if s['id'] != set_id]
    set_store(uid, 'sets', sets)
    return jsonify({"status":"success"})

# ── Progress ──────────────────────────────────────────────────────────────────
@app.route('/api/progress', methods=['GET','POST'])
@login_required
def progress():
    uid = current_user_id()
    if request.method=='GET':
        return jsonify(get_store(uid, 'progress', default_progress()))
    set_store(uid, 'progress', request.json)
    return jsonify({"status":"success"})

# ── Quizzes ───────────────────────────────────────────────────────────────────
@app.route('/api/quizzes/<subject>')
def get_quizzes(subject):
    with open(QUIZZES_FILE) as f: return jsonify(json.load(f).get(subject,[]))

# ── Guides ────────────────────────────────────────────────────────────────────
@app.route('/api/guides', methods=['GET'])
@login_required
def get_guides():
    return jsonify(get_store(current_user_id(), 'guides', []))

@app.route('/api/guides/upload', methods=['POST'])
@login_required
def upload_guide():
    if 'file' not in request.files: return jsonify({"error":"No file"}),400
    file = request.files['file']
    subject = request.form.get('subject','general')
    if not file.filename.lower().endswith('.pdf'): return jsonify({"error":"PDF only"}),400
    uid = current_user_id()
    filename = secure_filename(file.filename)
    file_bytes = file.read()
    guides = get_store(uid, 'guides', [])
    guide_id = len(guides)
    file_id = str(uuid.uuid4())

    conn = get_db()
    content_param = psycopg2.Binary(file_bytes) if IS_PG else file_bytes
    db_execute(conn, 'INSERT INTO guide_files (id, user_id, filename, content) VALUES (%s,%s,%s,%s)',
               (file_id, uid, filename, content_param))
    conn.commit()
    conn.close()

    guide = {"id":guide_id,"name":filename,"subject":subject,
             "file_id":file_id,"uploaded_at":datetime.now().isoformat()}
    guides.append(guide)
    set_store(uid, 'guides', guides)
    return jsonify({"status":"success","guide":guide})

@app.route('/api/guides/<int:guide_id>/pdf')
@login_required
def get_guide_pdf(guide_id):
    uid = current_user_id()
    guides = get_store(uid, 'guides', [])
    guide = next((g for g in guides if g['id']==guide_id),None)
    if not guide: return jsonify({"error":"Not found"}),404
    conn = get_db()
    row = db_execute(conn, 'SELECT content FROM guide_files WHERE id=%s AND user_id=%s', (guide['file_id'], uid)).fetchone()
    conn.close()
    if not row: return jsonify({"error":"File not found"}),404
    content = bytes(row['content'])
    return send_file(io.BytesIO(content), mimetype='application/pdf', download_name=guide['name'])

@app.route('/api/guides/<int:guide_id>/annotations', methods=['GET','POST'])
@login_required
def guide_annotations(guide_id):
    uid = current_user_id()
    user_ann = get_store(uid, 'annotations', {})
    key = str(guide_id)
    if request.method=='GET': return jsonify(user_ann.get(key,{}))
    user_ann[key] = request.json
    set_store(uid, 'annotations', user_ann)
    return jsonify({"status":"success"})

@app.route('/api/guides/<int:guide_id>', methods=['DELETE'])
@login_required
def delete_guide(guide_id):
    uid = current_user_id()
    guides = get_store(uid, 'guides', [])
    guide = next((g for g in guides if g['id']==guide_id),None)
    if guide:
        conn = get_db()
        db_execute(conn, 'DELETE FROM guide_files WHERE id=%s AND user_id=%s', (guide['file_id'], uid))
        conn.commit()
        conn.close()
        set_store(uid, 'guides', [g for g in guides if g['id']!=guide_id])
        user_ann = get_store(uid, 'annotations', {})
        user_ann.pop(str(guide_id),None)
        set_store(uid, 'annotations', user_ann)
    return jsonify({"status":"success"})

# ── Memorise ──────────────────────────────────────────────────────────────────
@app.route('/api/memorise', methods=['GET'])
@login_required
def get_memorise():
    return jsonify(get_store(current_user_id(), 'memorise', []))

@app.route('/api/memorise', methods=['POST'])
@login_required
def create_memorise():
    data = request.json
    uid = current_user_id()
    items = get_store(uid, 'memorise', [])
    item = {"id":str(uuid.uuid4())[:8],"title":data.get('title','Untitled'),
            "subject":data.get('subject','general'),"text":data.get('text',''),
            "created":datetime.now().isoformat()}
    items.append(item)
    set_store(uid, 'memorise', items)
    return jsonify({"status":"success","item":item})

@app.route('/api/memorise/<item_id>', methods=['DELETE'])
@login_required
def delete_memorise(item_id):
    uid = current_user_id()
    items = [i for i in get_store(uid, 'memorise', []) if i['id']!=item_id]
    set_store(uid, 'memorise', items)
    return jsonify({"status":"success"})


# ── AI: status ────────────────────────────────────────────────────────────────
@app.route('/api/ai/status')
def ai_status():
    s = get_settings()
    if s['provider'] == 'openrouter':
        if not s.get('openrouter_key'):
            return jsonify({"running":False,"provider":"openrouter",
                            "error":"No API key set","needs_key":True})
        try:
            result = openrouter_generate("Say 'ok' only.", "Reply with one word.",
                                         s['openrouter_key'], s['openrouter_model'])
            return jsonify({"running":True,"provider":"openrouter",
                            "model":s['openrouter_model'],
                            "models":[s['openrouter_model']]})
        except Exception as e:
            return jsonify({"running":False,"provider":"openrouter","error":str(e)})
    else:
        # Ollama
        try:
            data   = ollama_request('/api/tags',timeout=4)
            models = [m['name'] for m in data.get('models',[])]
            return jsonify({"running":True,"provider":"ollama",
                            "model":s.get('ollama_model',OLLAMA_MODEL),
                            "models":models})
        except urllib.error.URLError as e:
            return jsonify({"running":False,"provider":"ollama","error":str(e.reason)})
        except Exception as e:
            return jsonify({"running":False,"provider":"ollama","error":str(e)})

@app.route('/api/ai/debug')
def ai_debug():
    s = get_settings()
    results = {'provider': s['provider']}
    if s['provider'] == 'openrouter':
        results['model'] = s.get('openrouter_model')
        results['key_set'] = bool(s.get('openrouter_key'))
        if s.get('openrouter_key'):
            try:
                reply = openrouter_generate("Say 'hello'.", "Reply in one word.", s['openrouter_key'], s['openrouter_model'])
                results['test'] = f"OK — {reply[:60]}"
                results['status'] = 'ALL GOOD'
            except Exception as e:
                results['test']   = f"FAILED — {e}"
    else:
        results['ollama_url'] = OLLAMA_BASE
        results['model']      = s.get('ollama_model', OLLAMA_MODEL)
        try:
            sock = socket.create_connection(('127.0.0.1',11434),timeout=2)
            sock.close()
            results['tcp'] = 'OK'
            data   = ollama_request('/api/tags',timeout=4)
            models = [m['name'] for m in data.get('models',[])]
            results['models'] = models
            reply  = ollama_generate("Say 'ok'.", "Reply in one word.", s.get('ollama_model',OLLAMA_MODEL))
            results['test']   = f"OK — {reply[:60]}"
            results['status'] = 'ALL GOOD'
        except Exception as e:
            results['error'] = str(e)
    return jsonify(results)

# ── AI: explain ───────────────────────────────────────────────────────────────
@app.route('/api/ai/explain', methods=['POST'])
def ai_explain():
    data   = request.json
    prompt = (f"A student is studying {data.get('subject','')}. "
              f"Explain this concept simply for a GCSE student:\n\n"
              f"Term: {data.get('term','')}\nDefinition: {data.get('definition','')}\n\n"
              f"Give a clear 2-4 sentence explanation then one real-world example. "
              f"Use plain English, no bullet points.")
    system = "You are a clear and friendly GCSE tutor. Explain simply with real-world examples."
    return make_stream_response(prompt, system)

# ── AI: quiz generation ───────────────────────────────────────────────────────
@app.route('/api/ai/generate-quiz', methods=['POST'])
def ai_generate_quiz():
    data    = request.json
    cards   = data.get('cards',[])
    subject = data.get('subject','')
    count   = min(int(data.get('count',5)),10)
    facts   = "\n".join(f"- {c['question']}: {c['answer']}" for c in cards[:20])
    prompt  = (f"Create exactly {count} multiple choice questions for a GCSE {subject} student.\n"
               f"Use ONLY these facts:\n{facts}\n\n"
               f"Respond with ONLY a JSON array:\n"
               f'[{{"question":"...","options":["...","...","...","..."],"correct":0}}]')
    try:
        reply = ai_generate(prompt, "Respond with valid JSON only. No explanation, no markdown.")
        s,e   = reply.find('['),reply.rfind(']')+1
        if s==-1: raise ValueError("No JSON array")
        return jsonify({"questions":json.loads(reply[s:e])})
    except Exception as ex:
        return jsonify({"error":str(ex)}),500

@app.route('/api/ai/generate-quiz-stream', methods=['POST'])
def ai_generate_quiz_stream():
    data    = request.json
    set_ids = data.get('set_ids',[])
    subject = data.get('subject','mixed')
    count   = min(int(data.get('count',5)),15)
    cards   = data.get('cards',[])

    if set_ids:
        all_sets = get_store(current_user_id(), 'sets', []) if session.get('user_id') else []
        merged,subjects_used = [],set()
        for s in all_sets:
            if s['id'] in set_ids:
                merged.extend(s['cards']); subjects_used.add(s['subject'])
        if merged:
            cards   = merged
            subject = ', '.join(subjects_used) if len(subjects_used)>1 else (subjects_used.pop() if subjects_used else 'mixed')

    if not cards: return jsonify({"status":"error","message":"No cards found"}),400

    import random
    sample = random.sample(cards, min(len(cards),20))
    facts  = "\n".join(f"- {c['question']}: {c['answer']}" for c in sample)
    prompt = (f"Create exactly {count} multiple choice questions for a GCSE student studying {subject}.\n"
              f"Use ONLY these facts:\n{facts}\n\n"
              f"Each question must have exactly 4 options. Make wrong answers plausible.\n"
              f"'correct' is the 0-based index of the right answer.\n\n"
              f"Respond with ONLY a JSON array:\n"
              f'[{{"question":"...","options":["...","...","...","..."],"correct":0}}]')
    try:
        reply = ai_generate(prompt, "Output valid JSON only. No markdown, no explanation.")
        s,e   = reply.find('['),reply.rfind(']')+1
        if s==-1 or e==0: raise ValueError("No JSON array found")
        questions = json.loads(reply[s:e])
        if not isinstance(questions,list) or not questions: raise ValueError("Empty list")
        return jsonify({"status":"success","questions":questions,"count":len(questions)})
    except json.JSONDecodeError as ex:
        return jsonify({"status":"error","message":f"JSON parse error: {ex}",
                        "raw":reply[:400] if 'reply' in dir() else ''}),500
    except Exception as ex:
        return jsonify({"status":"error","message":str(ex)}),503

# ── AI: mark ──────────────────────────────────────────────────────────────────
@app.route('/api/ai/mark', methods=['POST'])
def ai_mark():
    data   = request.json
    stream = data.get('stream',False)
    prompt = (f"Mark this GCSE {data.get('subject','')} answer.\n"
              f"Question: {data.get('question','')}\n"
              f"Model answer: {data.get('correct_answer','')}\n"
              f"Student answer: {data.get('student_answer','')}\n\n"
              f"Give a mark out of 3 (0=wrong,1=partial,2=mostly,3=fully correct). "
              f"Then give feedback and a memory tip.")
    if stream:
        return make_stream_response(prompt, "You are a GCSE examiner. Give a clear mark /3, feedback, and a memory tip.")
    else:
        json_prompt = prompt + '\nRespond ONLY with JSON: {"mark":2,"feedback":"...","tip":"..."}'
        try:
            reply = ai_generate(json_prompt, "Respond with valid JSON only.")
            s,e   = reply.find('{'),reply.rfind('}')+1
            return jsonify(json.loads(reply[s:e]))
        except Exception as ex:
            return jsonify({"error":str(ex)}),500

# ── AI: chat ──────────────────────────────────────────────────────────────────
@app.route('/api/ai/chat', methods=['POST'])
def ai_chat():
    data    = request.json
    message = data.get('message','')
    history = data.get('history',[])
    context = ""
    for msg in history[-6:]:
        role     = "Student" if msg["role"]=="user" else "Tutor"
        context += f"{role}: {msg['content']}\n"
    context += f"Student: {message}"
    try:
        reply = ai_generate(context,
            "You are RevisionCore AI, a friendly GCSE tutor. "
            "Give clear, concise answers with examples. Keep focused on studying.")
        return jsonify({"response":reply})
    except Exception as ex:
        return jsonify({"error":str(ex)}),503

# ── AI: streaming tutor ───────────────────────────────────────────────────────
@app.route('/api/ai/tutor', methods=['POST'])
def ai_tutor():
    data     = request.json
    messages = data.get('messages',[])
    subject  = data.get('subject','general')
    context  = ""
    for msg in messages[-8:]:
        role     = "Student" if msg["role"]=="user" else "Tutor"
        context += f"{role}: {msg['content']}\n"
    system = (f"You are RevisionCore AI, a friendly GCSE {subject} tutor. "
              "Give clear, helpful answers. Use examples. Keep focused on studying.")
    return make_stream_response(context, system)

if __name__ == '__main__':
    s = get_settings()
    print("🚀 RevisionCore running at http://127.0.0.1:5000")
    print(f"🤖 AI provider: {s['provider']} | model: {s.get('openrouter_model') if s['provider']=='openrouter' else s.get('ollama_model','llama3.2')}")
    print("🔍 Debug: http://127.0.0.1:5000/api/ai/debug")
    app.run(debug=True, port=5000)
