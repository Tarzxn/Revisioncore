"""Rian AI Gen 2 — a built-in Ollama-powered student hub."""
import json
import os
import re
import secrets
import threading
import time
import uuid
from functools import wraps
from pathlib import Path

import requests
from flask import Flask, Response, jsonify, render_template, request, stream_with_context
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)

# Never allow an old frontend bundle to survive a deployment. This is
# particularly important for authentication: serving an older auth script
# alongside a newer server can make the login form appear to endlessly
# refresh/redirect. Render deployments should always receive the current
# HTML/JS/CSS.
@app.after_request
def no_stale_frontend_cache(response):
    path = request.path or ""
    if path == "/" or path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024

# ---- Authentication --------------------------------------------------------
# Two different lifetimes, on purpose:
#  - ACCOUNTS (who is allowed to log in) are persisted to disk, hashed, so
#    people don't have to re-register every time the server restarts — that
#    would make a login system pointless.
#  - SESSIONS (being currently logged in) and conversation history are NOT
#    persisted anywhere durable: session tokens live only in this in-memory
#    dict (wiped on restart) and are never set as a cookie — the browser
#    holds its token in sessionStorage, cleared the moment the tab closes, and
#    sends it explicitly on every request. There is no mechanism for a
#    returning visitor to be silently auto-logged-in.
USERS_FILE = Path(os.environ.get("USERS_FILE", "data/users.json"))
FORGE_USERNAME = os.environ.get("RIAN_USERNAME", os.environ.get("FORGE_USERNAME", "")).strip()  # optional seed account, see seed_admin_account()
FORGE_PASSWORD = os.environ.get("RIAN_PASSWORD", os.environ.get("FORGE_PASSWORD", "")).strip()
SESSION_TOKENS = {}  # token -> expiry unix timestamp
SESSION_USERS = {}   # token -> username (same in-memory lifetime as the token)
_session_lock = threading.Lock()  # gthread workers mean real concurrent threads touch this dict now
SESSION_TTL_SECONDS = int(os.environ.get("FORGE_SESSION_HOURS", "12")) * 3600
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{3,32}$")
_users_lock = threading.Lock()  # gunicorn now runs with gthread workers, so concurrent requests within one process are real

# Optional free persistence for accounts across redeploys on hosts (like
# Render's free tier) that don't offer a persistent disk at all: sync
# users.json to a private GitHub Gist instead, using a personal access token
# you already have from having a GitHub account — no new paid service, no new
# signup. This is layered on top of the local file, never replaces it: every
# read/write still touches the local file too, and any GitHub failure is
# swallowed and falls back to whatever's local, so a network hiccup or an
# unset token never breaks login.
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GITHUB_GIST_ID = os.environ.get("GITHUB_GIST_ID", "").strip()
GITHUB_GIST_FILENAME = "rian_ai_gen2_users.json"
GITHUB_API_VERSION = "2022-11-28"


def _github_headers():
    return {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": GITHUB_API_VERSION}


def _gist_load():
    """Best-effort read from the configured gist. Returns None (never raises)
    if sync isn't configured or the call fails, so callers fall back to the
    local file instead."""
    if not (GITHUB_TOKEN and GITHUB_GIST_ID): return None
    try:
        response = requests.get(f"https://api.github.com/gists/{GITHUB_GIST_ID}", headers=_github_headers(), timeout=10)
        response.raise_for_status()
        file_data = response.json().get("files", {}).get(GITHUB_GIST_FILENAME)
        if not file_data or file_data.get("truncated"): return None
        return json.loads(file_data["content"])
    except (requests.RequestException, json.JSONDecodeError, KeyError, ValueError, TypeError):
        return None


def _gist_save(users):
    """Best-effort push to the configured gist. Never raises — a failed sync
    just means the local file (and, until the next successful sync, whatever
    was already in the gist) stays the source of truth instead."""
    if not (GITHUB_TOKEN and GITHUB_GIST_ID): return
    try:
        requests.patch(
            f"https://api.github.com/gists/{GITHUB_GIST_ID}",
            headers=_github_headers(),
            json={"files": {GITHUB_GIST_FILENAME: {"content": json.dumps(users, indent=2)}}},
            timeout=10,
        )
    except requests.RequestException as error:
        print(f"[Rian AI Gen 2] Warning: could not sync accounts to GitHub Gist: {error}")


def _gist_create_if_needed():
    """If a token is set but no gist ID, create a new private gist once and
    print its ID. The operator needs to copy that into a GITHUB_GIST_ID env
    var — without it, every restart would create a brand new empty gist
    instead of reusing the same one, which defeats the point."""
    global GITHUB_GIST_ID
    if not GITHUB_TOKEN or GITHUB_GIST_ID: return
    try:
        response = requests.post(
            "https://api.github.com/gists",
            headers=_github_headers(),
            json={"description": "Rian AI Gen 2 account store — do not edit by hand", "public": False,
                  "files": {GITHUB_GIST_FILENAME: {"content": "{}"}}},
            timeout=10,
        )
        response.raise_for_status()
        GITHUB_GIST_ID = response.json()["id"]
        print(f"[Rian AI Gen 2] Created a private gist for account storage: {GITHUB_GIST_ID}")
        print(f"[Rian AI Gen 2] IMPORTANT: set GITHUB_GIST_ID={GITHUB_GIST_ID} as an env var now — "
              f"without it, the next restart creates a new, empty gist instead of reusing this one.")
    except (requests.RequestException, KeyError, ValueError) as error:
        print(f"[Rian AI Gen 2] Warning: could not create a gist for account storage: {error}. Falling back to local-file-only persistence.")


_users_cache = None
_gist_lock = threading.Lock()


def load_users():
    """Accounts are read once (gist, else local file) and then served from memory, so requests
    never wait on GitHub and concurrent edits all share one dict instead of overwriting each other."""
    global _users_cache
    if _users_cache is None:
        remote = _gist_load()
        if remote is not None:
            _users_cache = remote
        else:
            try: _users_cache = json.loads(USERS_FILE.read_text()) if USERS_FILE.exists() else {}
            except (json.JSONDecodeError, OSError): _users_cache = {}
    return _users_cache


def save_users(users):
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = USERS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(users, indent=2))
    os.replace(tmp, USERS_FILE)  # atomic: a crash mid-write can't corrupt the account file
    if GITHUB_TOKEN and GITHUB_GIST_ID:
        def push():
            with _gist_lock:
                try: _gist_save(json.loads(json.dumps(users)))
                except RuntimeError: pass
        threading.Thread(target=push, daemon=True).start()  # off the request path


def create_user(username, password):
    """Caller must hold _users_lock. Returns False if the username is taken."""
    users = load_users()
    key = username.lower()
    if key in users: return False
    users[key] = {"username": username, "password_hash": generate_password_hash(password), "created_at": time.time()}
    save_users(users)
    return True


def seed_admin_account():
    """Optional convenience: FORGE_USERNAME/FORGE_PASSWORD, if both set, are
    created as a standing account on startup — same as it worked before
    self-signup existed — so existing deployments keep working unchanged."""
    if not FORGE_USERNAME or not FORGE_PASSWORD: return
    with _users_lock:
        create_user(FORGE_USERNAME, FORGE_PASSWORD)


_gist_create_if_needed()
seed_admin_account()
# A startup diagnostic, not an error: if this reads 0 accounts on every
# restart even though people have signed up, accounts aren't actually
# persisting (no GitHub sync configured and USERS_FILE isn't on persistent
# storage — e.g. a Render free-tier service with no disk attached).
print(f"[Rian AI Gen 2] {len(load_users())} account(s) loaded"
      f"{' (synced via GitHub Gist ' + GITHUB_GIST_ID + ')' if GITHUB_TOKEN and GITHUB_GIST_ID else f' from {USERS_FILE.resolve()}'}")


def issue_token(username):
    token = secrets.token_urlsafe(32)
    with _session_lock:
        SESSION_TOKENS[token] = time.time() + SESSION_TTL_SECONDS
        SESSION_USERS[token] = username
    return token


def current_username():
    token = token_from_request()
    if not is_valid_token(token):
        return None
    with _session_lock:
        return SESSION_USERS.get(token)


def token_from_request():
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    # Plain <a href> downloads/previews can't set custom headers, so those two
    # routes also accept the token as a query string parameter.
    return request.args.get("token", "").strip()


def is_valid_token(token):
    if not token: return False
    with _session_lock:
        expiry = SESSION_TOKENS.get(token)
        if expiry is None: return False
        if time.time() > expiry:
            SESSION_TOKENS.pop(token, None)
            SESSION_USERS.pop(token, None)
            return False
        return True


def require_auth(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not is_valid_token(token_from_request()):
            return jsonify(error="Not authenticated. Please log in."), 401
        return view(*args, **kwargs)
    return wrapped


# Single server-side token for Ollama Cloud. Keep credentials in Render
# environment variables; never commit an API key to the repository.
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "").strip()
# Ollama Cloud uses its native /api/chat shape, not the OpenAI-style /v1 route.
OLLAMA_CHAT_URL = "https://ollama.com/api/chat"


# Tavily — web search, used to ground answers in current information before
# the model responds. No key is baked in (unlike Ollama) because none was
# provided; set TAVILY_API_KEY in the environment to enable the "Web search"
# toggle in the composer. Get a free key at https://app.tavily.com.
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "").strip()
TAVILY_SEARCH_URL = "https://api.tavily.com/search"

# Ollama Cloud's hosted catalogue. gpt-oss:20b is the default: it's a strong,
# fast open-weight instruction/coding model sized to run well on the cloud
# tier without the latency of the much larger 120b/671b models below.
MODELS = [
    {"id": "gpt-oss:20b", "name": "GPT-OSS 20B", "family": "OpenAI OSS", "tag": "Recommended · fast & capable"},
    {"id": "gpt-oss:120b", "name": "GPT-OSS 120B", "family": "OpenAI OSS", "tag": "Larger · slower · stronger reasoning"},
]
DEFAULT_MODEL = MODELS[0]["id"]

# ---- Power level (ChatGPT-style Low/Medium/High/Max reasoning-effort slider) -----
# Maps onto Ollama's native "think" field, which GPT-OSS (every model in
# MODELS) supports: bool or "low"/"medium"/"high" (GPT-OSS specifically
# always reasons at least a little regardless of the boolean value — "Low"
# still gets the smallest token budget and skips the explicit higher levels).
# There's no official "max" level at the Ollama API — Rian AI Gen 2's "Max" instead
# combines "high" thinking with the largest token budget and (for 3D
# requests specifically) the largest model, which is the actual lever
# available for going further than "High".
POWER_LEVELS = {
    "low":    {"think": False,   "num_predict": 2048},
    "medium": {"think": "low",   "num_predict": 4096},
    "high":   {"think": "medium","num_predict": 6144},
    "max":    {"think": "high",  "num_predict": 9216},
}
DEFAULT_POWER = "medium"

SYSTEM = '''You are Rian AI Gen 2, the built-in student AI assistant.

Return ONLY a helpful plain-text/Markdown response to the user's request. NEVER create, describe, attach, encode, save, preview, download, or return files or file-generation instructions. Do not output JSON wrappers or artifact metadata. If a user asks for a file, explain the content directly in the chat instead and offer a copyable text version when appropriate.

You are especially good at explaining school subjects, making quizzes, exam-style questions, revision plans, study techniques, homework guidance, course planning, and helping students understand questions. Be concise but useful, use clear headings/bullets when helpful, and do not pretend to have access to school systems or private information you were not given.'''



def tavily_search(query):
    """Search the live web via Tavily and return a compact text block the
    model can read as extra context. Raises on failure — the caller decides
    whether that should abort the request or just proceed without results."""
    response = requests.post(
        TAVILY_SEARCH_URL,
        headers={"Authorization": f"Bearer {TAVILY_API_KEY}"},
        json={"query": query, "search_depth": "basic", "max_results": 6, "include_answer": True},
        timeout=25,
    )
    response.raise_for_status()
    body = response.json()
    lines = []
    if body.get("answer"): lines.append(f"Summary: {body['answer']}")
    for result in body.get("results", [])[:6]:
        title = str(result.get("title", "")).strip()
        url = str(result.get("url", "")).strip()
        snippet = str(result.get("content", "")).strip()[:500]
        lines.append(f"- {title} ({url}): {snippet}")
    if not lines:
        raise ValueError("Tavily returned no results")
    return "\n".join(lines)


@app.get("/")
def index(): return render_template("index.html")


@app.post("/api/login")
def login():
    if _throttled(): return jsonify(error="Too many attempts. Wait a few minutes and try again."), 429
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="Malformed request body."), 400
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    users = load_users()
    if not users:
        return jsonify(error='No accounts exist yet — use "Create account" below to set one up.'), 404
    record = users.get(username.lower())
    # check_password_hash is constant-time; run it even on a missing user
    # (against a dummy hash) so a failed lookup and a wrong password take the
    # same amount of time either way, and username existence can't be timed.
    if not record:
        check_password_hash(generate_password_hash("dummy"), password)
        return jsonify(error="Incorrect username or password."), 401
    if not check_password_hash(record["password_hash"], password):
        return jsonify(error="Incorrect username or password."), 401
    return jsonify(token=issue_token(record["username"]), expiresIn=SESSION_TTL_SECONDS)


@app.post("/api/signup")
def signup():
    if _throttled(): return jsonify(error="Too many attempts. Wait a few minutes and try again."), 429
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="Malformed request body."), 400
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    if not USERNAME_RE.match(username):
        return jsonify(error="Username must be 3-32 characters: letters, numbers, dots, hyphens, or underscores only."), 400
    if len(password) < 8:
        return jsonify(error="Password must be at least 8 characters."), 400
    with _users_lock:
        if not create_user(username, password):
            return jsonify(error="That username is already taken."), 409
    return jsonify(token=issue_token(username), expiresIn=SESSION_TTL_SECONDS)


@app.post("/api/logout")
def logout():
    with _session_lock:
        token = token_from_request()
        SESSION_TOKENS.pop(token, None)
        SESSION_USERS.pop(token, None)
    return jsonify(ok=True)



# ---- Student hub data ------------------------------------------------------
# Student data lives inside the same account store as credentials. When the
# optional GitHub Gist persistence is configured on Render, this means tasks,
# timetable and revision data survive deploys without requiring a paid disk.
DAYS = {"monday", "tuesday", "wednesday", "thursday", "friday"}
_attempts = {}


def _throttled():
    ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip()
    now = time.time()
    count, start = _attempts.get(ip, (0, now))
    if now - start > 300: count, start = 0, now
    _attempts[ip] = (count + 1, start)
    return count + 1 > 15


def _safe_url(value):
    value = str(value or "").strip()[:500]
    return value if re.match(r"^https?://", value, re.I) else ""


def _clean_task(t):
    if not isinstance(t, dict) or not str(t.get("title", "")).strip(): return None
    created = t.get("created_at")
    return {"id": str(t.get("id") or uuid.uuid4().hex)[:40], "title": str(t["title"]).strip()[:160],
            "subject": str(t.get("subject") or "General").strip()[:60], "due": str(t.get("due") or "")[:10],
            "priority": t.get("priority") if t.get("priority") in {"low", "normal", "high"} else "normal",
            "done": bool(t.get("done")), "created_at": created if isinstance(created, (int, float)) else time.time()}


def _sanitize_student(s, username):
    """The client sends whole documents back, so everything is re-validated here."""
    p = s.get("profile") if isinstance(s.get("profile"), dict) else {}
    s["profile"] = {k: str(p.get(k) or "").strip()[:80] for k in ("display_name", "year_group", "school")}
    s["profile"]["username"] = username
    tasks = s.get("tasks") if isinstance(s.get("tasks"), list) else []
    s["tasks"] = [t for t in map(_clean_task, tasks) if t][:500]
    lessons = []
    for t in (s.get("timetable") if isinstance(s.get("timetable"), list) else []):
        if isinstance(t, dict) and t.get("day") in DAYS and str(t.get("subject", "")).strip():
            lessons.append({"id": str(t.get("id") or uuid.uuid4().hex)[:40], "day": t["day"], "subject": str(t["subject"]).strip()[:60],
                            "start": str(t.get("start") or "")[:5], "end": str(t.get("end") or "")[:5], "room": str(t.get("room") or "").strip()[:60]})
    s["timetable"] = lessons[:200]
    links = []
    for l in (s.get("quick_links") if isinstance(s.get("quick_links"), list) else []):
        if isinstance(l, dict) and str(l.get("title", "")).strip() and _safe_url(l.get("url")):
            title = str(l["title"]).strip()[:60]
            links.append({"title": title, "url": _safe_url(l["url"]), "icon": (str(l.get("icon") or title[:1]).strip() or "↗")[:2]})
    s["quick_links"] = links[:24]
    s["notes"] = str(s.get("notes") or "")[:5000]
    # Flashcards are stored as lightweight student-owned text records.
    cards = []
    for c in (s.get("flashcards") if isinstance(s.get("flashcards"), list) else []):
        if not isinstance(c, dict): continue
        q, a = str(c.get("question") or "").strip(), str(c.get("answer") or "").strip()
        if not q or not a: continue
        cards.append({"id": str(c.get("id") or uuid.uuid4().hex)[:40], "deck": str(c.get("deck") or "General").strip()[:80] or "General", "subject": str(c.get("subject") or "").strip()[:80], "question": q[:1000], "answer": a[:2000], "created_at": c.get("created_at") if isinstance(c.get("created_at"), (int,float)) else time.time()})
    s["flashcards"] = cards[:5000]


def _default_student():
    return {
        "profile": {"display_name": "", "year_group": "", "school": ""},
        "tasks": [],
        "timetable": [],
        "subjects": [],
        "quick_links": [
            {"title": "Google Classroom", "url": "https://classroom.google.com", "icon": "▦"},
            {"title": "Microsoft Teams", "url": "https://teams.microsoft.com", "icon": "T"},
            {"title": "OneDrive", "url": "https://onedrive.live.com", "icon": "☁"},
            {"title": "BBC Bitesize", "url": "https://www.bbc.co.uk/bitesize", "icon": "B"},
        ],
        "notes": "",
        "flashcards": [],
    }


def _student_record(username):
    with _users_lock:
        users = load_users()
        key = username.lower()
        record = users.get(key)
        if not record:
            return None, None, None
        record.setdefault("student", _default_student())
        if not isinstance(record["student"].get("profile"), dict): record["student"]["profile"] = {}
        record["student"]["profile"]["username"] = record.get("username", username)
        defaults = _default_student()
        for k, v in defaults.items():
            record["student"].setdefault(k, v)
        return users, key, record


def _save_student(username, student):
    with _users_lock:
        users = load_users()
        key = username.lower()
        if key not in users:
            return False
        users[key].setdefault("student", _default_student())
        users[key]["student"] = student
        save_users(users)
        return True


@app.get("/api/me")
@require_auth
def me():
    username = current_username()
    users, key, record = _student_record(username)
    if not record:
        return jsonify(error="Account not found."), 404
    student = record["student"]
    profile = dict(student.get("profile") or {})
    profile["username"] = record.get("username", username)
    return jsonify(user=profile)


@app.get("/api/student")
@require_auth
def student_data():
    username = current_username()
    _, _, record = _student_record(username)
    if not record:
        return jsonify(error="Account not found."), 404
    return jsonify(student=record["student"])


@app.put("/api/student")
@require_auth
def update_student():
    username = current_username()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="Malformed request body."), 400
    _, _, record = _student_record(username)
    if not record:
        return jsonify(error="Account not found."), 404
    current = record["student"]
    for key in ("profile", "tasks", "timetable", "subjects", "quick_links", "notes"):
        if key in data:
            current[key] = data[key]
    # Keep the student course model structured and safe for older accounts that
    # may still contain a simple list of subject strings.
    if isinstance(current.get("subjects"), list):
        courses = []
        for item in current["subjects"]:
            if isinstance(item, str):
                name = item.strip()
                if name:
                    courses.append({"name": name, "course": "", "exam_board": "", "specification": "", "progress": 0})
            elif isinstance(item, dict):
                name = str(item.get("name", "")).strip()
                if name:
                    try: progress = max(0, min(100, int(float(item.get("progress", 0)))))
                    except (TypeError, ValueError): progress = 0
                    courses.append({"name": name[:120], "course": str(item.get("course", "")).strip()[:120], "exam_board": str(item.get("exam_board", item.get("examBoard", ""))).strip()[:80], "specification": _safe_url(item.get("specification", item.get("spec_link", ""))), "progress": progress})
        current["subjects"] = courses
    _sanitize_student(current, record.get("username", username))
    if not _save_student(username, current):
        return jsonify(error="Could not save student data."), 500
    return jsonify(ok=True, student=current)


def _clean_course(data):
    if not isinstance(data, dict):
        return None, "Course data is invalid."
    name = str(data.get("name", "")).strip()
    course = str(data.get("course", "")).strip()
    exam_board = str(data.get("exam_board", data.get("examBoard", ""))).strip()
    specification = str(data.get("specification", data.get("spec_link", ""))).strip()
    if not name:
        return None, "Subject name is required."
    if len(name) > 120 or len(course) > 120 or len(exam_board) > 80 or len(specification) > 500:
        return None, "One or more course fields are too long."
    if specification and not (specification.startswith("https://") or specification.startswith("http://")):
        return None, "Specification link must start with http:// or https://."
    try:
        progress = max(0, min(100, int(float(data.get("progress", 0)))))
    except (TypeError, ValueError):
        return None, "Course progress must be between 0 and 100."
    return {"id": uuid.uuid4().hex, "name": name, "course": course, "exam_board": exam_board, "specification": specification, "progress": progress}, None


@app.post("/api/student/courses")
@require_auth
def add_course():
    username = current_username()
    _, _, record = _student_record(username)
    if not record:
        return jsonify(error="Account not found."), 404
    course, error = _clean_course(request.get_json(silent=True) or {})
    if error:
        return jsonify(error=error), 400
    courses = record["student"].setdefault("subjects", [])
    # Treat the same subject + qualification as a duplicate instead of creating
    # confusing copies. Existing courses can still be edited in Settings.
    key = (course["name"].casefold(), course["course"].casefold())
    if any((str(c.get("name", "")).casefold(), str(c.get("course", "")).casefold()) == key for c in courses if isinstance(c, dict)):
        return jsonify(error="That course is already in your list."), 409
    courses.append(course)
    if not _save_student(username, record["student"]):
        return jsonify(error="Could not save the course."), 500
    return jsonify(ok=True, course=course, student=record["student"]), 201


def _clean_flashcard(c, deck_default="General"):
    if not isinstance(c, dict): return None, "Invalid flashcard."
    q = str(c.get("question") or "").strip()
    a = str(c.get("answer") or "").strip()
    if not q or not a: return None, "Each flashcard needs both a question and an answer."
    return {"id": uuid.uuid4().hex, "deck": str(c.get("deck") or deck_default).strip()[:80] or "General", "subject": str(c.get("subject") or "").strip()[:80], "question": q[:1000], "answer": a[:2000], "created_at": time.time()}, None


@app.post("/api/student/flashcards/import")
@require_auth
def import_flashcards():
    data = request.get_json(silent=True) or {}
    raw = str(data.get("text") or "")
    deck = str(data.get("deck") or "General").strip()[:80] or "General"
    subject = str(data.get("subject") or "").strip()[:80]
    fmt = str(data.get("format") or "auto").lower()
    if not raw.strip(): return jsonify(error="Paste or import some flashcards first."), 400
    import csv, io
    rows=[]
    try:
        if fmt in {"csv","auto"} and (fmt=="csv" or "," in raw.splitlines()[0]):
            reader=csv.reader(io.StringIO(raw))
            parsed=[r for r in reader if any(str(x).strip() for x in r)]
            if parsed and len(parsed[0]) >= 2 and any(str(x).strip().lower() in {"question","front","term","prompt"} for x in parsed[0][:2]): parsed=parsed[1:]
            rows=[(r[0], r[1]) for r in parsed if len(r)>=2]
        if not rows:
            # TXT supports: question<TAB>answer, question :: answer, or blank-line pairs.
            lines=[x.strip() for x in raw.splitlines()]
            for line in lines:
                if not line: continue
                if "\t" in line: rows.append(tuple(line.split("\t",1)))
                elif "::" in line: rows.append(tuple(line.split("::",1)))
                elif "|" in line: rows.append(tuple(line.split("|",1)))
            if not rows:
                blocks=[b.strip().splitlines() for b in raw.split("\n\n") if b.strip()]
                rows=[(b[0], " ".join(b[1:])) for b in blocks if len(b)>=2]
    except Exception:
        return jsonify(error="We could not read that import. Check the format and try again."), 400
    if not rows: return jsonify(error="No valid question/answer pairs were found."), 400
    _, _, record = _student_record(current_username())
    cards=record["student"].setdefault("flashcards", [])
    existing={(str(c.get("deck","General")).casefold(),str(c.get("question","")).strip().casefold(),str(c.get("answer","")).strip().casefold()) for c in cards if isinstance(c,dict)}
    added=duplicates=invalid=0
    new_cards=[]
    for q,a in rows[:1000]:
        card,err=_clean_flashcard({"question":q,"answer":a,"deck":deck,"subject":subject},deck)
        if err: invalid+=1; continue
        key=(deck.casefold(),card["question"].casefold(),card["answer"].casefold())
        if key in existing: duplicates+=1; continue
        existing.add(key); cards.append(card); new_cards.append(card); added+=1
    record["student"]["flashcards"]=cards[-5000:]
    if not _save_student(current_username(), record["student"]): return jsonify(error="Could not save the imported flashcards."), 500
    return jsonify(ok=True, added=added, duplicates=duplicates, invalid=invalid, flashcards=new_cards, student=record["student"])


@app.patch("/api/student/flashcards/<card_id>")
@require_auth
def patch_flashcard(card_id):
    data=request.get_json(silent=True) or {}
    _,_,record=_student_record(current_username()); cards=record["student"].setdefault("flashcards", [])
    card=next((c for c in cards if c.get("id")==card_id),None)
    if not card: return jsonify(error="Flashcard not found."),404
    for k,limit in (("question",1000),("answer",2000),("deck",80),("subject",80)):
        if k in data: card[k]=str(data[k] or "").strip()[:limit]
    if not card.get("question") or not card.get("answer"): return jsonify(error="Question and answer are required."),400
    _save_student(current_username(),record["student"]); return jsonify(card=card)


@app.delete("/api/student/flashcards/<card_id>")
@require_auth
def delete_flashcard(card_id):
    _,_,record=_student_record(current_username()); cards=record["student"].setdefault("flashcards", [])
    new=[c for c in cards if c.get("id")!=card_id]
    if len(new)==len(cards): return jsonify(error="Flashcard not found."),404
    record["student"]["flashcards"]=new; _save_student(current_username(),record["student"]); return jsonify(ok=True)


@app.post("/api/student/tasks")
@require_auth
def add_task():
    username = current_username()
    _, _, record = _student_record(username)
    if not record: return jsonify(error="Account not found."), 404
    data = request.get_json(silent=True) or {}
    title = str(data.get("title", "")).strip()
    if not title: return jsonify(error="Task title is required."), 400
    task = {
        "id": uuid.uuid4().hex,
        "title": title[:160],
        "subject": str(data.get("subject", "General")).strip()[:60] or "General",
        "due": str(data.get("due", "")).strip()[:20],
        "priority": str(data.get("priority", "normal")).lower() if str(data.get("priority", "normal")).lower() in {"low","normal","high"} else "normal",
        "done": False,
        "created_at": time.time(),
    }
    record["student"].setdefault("tasks", []).append(task)
    _save_student(username, record["student"])
    return jsonify(task=task), 201


@app.patch("/api/student/tasks/<task_id>")
@require_auth
def patch_task(task_id):
    username = current_username()
    _, _, record = _student_record(username)
    if not record: return jsonify(error="Account not found."), 404
    data = request.get_json(silent=True) or {}
    tasks = record["student"].setdefault("tasks", [])
    task = next((t for t in tasks if t.get("id") == task_id), None)
    if not task: return jsonify(error="Task not found."), 404
    for key, limit in (("title", 160), ("subject", 60), ("due", 10)):
        if key in data and (key != "title" or str(data[key]).strip()): task[key] = str(data[key]).strip()[:limit]
    if data.get("priority") in {"low", "normal", "high"}: task["priority"] = data["priority"]
    if "done" in data: task["done"] = bool(data["done"])
    _save_student(username, record["student"])
    return jsonify(task=task)


@app.delete("/api/student/tasks/<task_id>")
@require_auth
def delete_task(task_id):
    username = current_username()
    _, _, record = _student_record(username)
    if not record: return jsonify(error="Account not found."), 404
    tasks = record["student"].setdefault("tasks", [])
    before = len(tasks)
    record["student"]["tasks"] = [t for t in tasks if t.get("id") != task_id]
    if len(record["student"]["tasks"]) == before:
        return jsonify(error="Task not found."), 404
    _save_student(username, record["student"])
    return jsonify(ok=True)


@app.get("/api/models")
@require_auth
def models():
    return jsonify(MODELS)


@app.get("/api/config")
@require_auth
def config():
    return jsonify(webSearchEnabled=bool(TAVILY_API_KEY))


@app.post("/api/chat")
@require_auth
def chat():
    if not OLLAMA_API_KEY:
        return jsonify(error="Rian AI Gen 2 isn't configured yet: set OLLAMA_API_KEY on Render, then restart."), 500
    data = request.get_json(silent=True)
    if not isinstance(data, dict): return jsonify(error="Malformed request body."), 400
    prompt = str(data.get("prompt", "")).strip()
    if not prompt: return jsonify(error="Enter a request."), 400
    if len(prompt) > 8000: return jsonify(error="That message is too long. Keep it under 8,000 characters."), 400
    messages = [{"role":"system","content":SYSTEM}]
    history = data.get("history") if isinstance(data.get("history"), list) else []
    for m in history[-10:]:
        if isinstance(m, dict) and m.get("role") in {"user","assistant"} and isinstance(m.get("content"), str):
            messages.append({"role":m["role"],"content":m["content"]})
    if data.get("web_search"):
        if not TAVILY_API_KEY: return jsonify(error="Web search isn't configured on this server."), 500
        try: messages.append({"role":"system","content":f"Relevant live web search context:\n{tavily_search(prompt)}"})
        except (requests.RequestException, ValueError, KeyError) as error: return jsonify(error=f"Web search failed: {error}"), 502
    messages.append({"role":"user","content":prompt})
    model_id = data.get("model") or DEFAULT_MODEL
    if model_id not in {m["id"] for m in MODELS}: model_id=DEFAULT_MODEL
    power = str(data.get("power", DEFAULT_POWER)).lower()
    if power not in POWER_LEVELS: power=DEFAULT_POWER
    cfg=POWER_LEVELS[power]
    payload={"model":model_id,"messages":messages,"stream":True,"think":cfg["think"],"options":{"num_predict":cfg["num_predict"]}}
    upstream=None; last_error=None
    for attempt in range(2):
        try: candidate=requests.post(OLLAMA_CHAT_URL,headers={"Authorization":f"Bearer {OLLAMA_API_KEY}"},json=payload,timeout={"low":150,"medium":220,"high":280,"max":280}[power],stream=True)
        except requests.RequestException as error: last_error=error; time.sleep(.6); continue
        if candidate.status_code in (502,503,504) and attempt==0: candidate.close(); last_error=requests.HTTPError(f"upstream returned {candidate.status_code}"); time.sleep(.6); continue
        upstream=candidate; break
    if upstream is None: return jsonify(error=f"Ollama Cloud is temporarily unavailable ({last_error}). Please retry."),502
    if upstream.status_code==401: upstream.close(); return jsonify(error="Ollama Cloud rejected the API key. Check OLLAMA_API_KEY on Render."),502
    if upstream.status_code==429: upstream.close(); return jsonify(error=f"{model_id} is rate-limited on Ollama Cloud right now. Please retry shortly."),502
    try: upstream.raise_for_status()
    except requests.HTTPError:
        detail=upstream.text[:500]; status=upstream.status_code; upstream.close(); return jsonify(error=f"Ollama Cloud rejected this request ({status}). {detail}"),502
    def generate():
        try:
            for line in upstream.iter_lines(decode_unicode=True):
                if not line: continue
                try: chunk=json.loads(line)
                except json.JSONDecodeError: continue
                msg=chunk.get("message") or {}
                think=msg.get("thinking","")
                if think: yield json.dumps({"type":"thinking","text":think},ensure_ascii=False)+"\n"
                piece=msg.get("content","")
                if piece: yield json.dumps({"type":"delta","text":piece},ensure_ascii=False)+"\n"
                if chunk.get("done"): yield json.dumps({"type":"done"})+"\n"; break
        except requests.RequestException as error: yield json.dumps({"type":"error","error":f"Connection to Ollama Cloud dropped: {error}"})+"\n"
        except Exception as error: yield json.dumps({"type":"error","error":f"Generation failed: {error}"})+"\n"
        finally: upstream.close()
    return Response(stream_with_context(generate()),mimetype="application/x-ndjson")

