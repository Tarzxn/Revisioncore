"""Rian AI Gen 2 — a built-in Ollama-powered student hub."""
import json
import hashlib
import os
import re
import secrets
import threading
import time
import uuid
from functools import wraps
from pathlib import Path

import requests
from flask import Flask, Response, jsonify, render_template, request, stream_with_context, redirect
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

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
# Accounts and their student data are stored in the account store. Active
# browser sessions are also persisted as SHA-256 token hashes, so a normal
# Render wake-up/restart does not sign the student out. The raw session token
# lives only in an HttpOnly cookie and is never exposed to JavaScript.
USERS_FILE = Path(os.environ.get("USERS_FILE", "data/users.json"))
FORGE_USERNAME = os.environ.get("RIAN_USERNAME", os.environ.get("FORGE_USERNAME", "")).strip()  # optional seed account, see seed_admin_account() if not (CF_AUTH_URL and CF_AUTH_SERVICE_KEY) else None
FORGE_PASSWORD = os.environ.get("RIAN_PASSWORD", os.environ.get("FORGE_PASSWORD", "")).strip()
SESSION_TOKENS = {}  # token -> expiry unix timestamp (hot cache)
SESSION_USERS = {}   # token -> username (hot cache)
_session_lock = threading.Lock()
# Persistent browser sessions survive a Render wake-up/restart when the account
# store is backed by the configured GitHub Gist. The raw token is only sent in
# an HttpOnly cookie; the durable store keeps a SHA-256 hash.
SESSION_TTL_SECONDS = int(os.environ.get("RIAN_SESSION_DAYS", "30")) * 24 * 3600
SESSION_COOKIE = "rian_session"
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
CF_AUTH_URL = os.environ.get("RIAN_AUTH_URL", "").strip().rstrip("/")
CF_AUTH_SERVICE_KEY = os.environ.get("RIAN_AUTH_SERVICE_KEY", "").strip()
CF_SESSION_CACHE = {}
CF_SESSION_TTL = 60
TEAMS_CLIENT_ID = os.environ.get("MICROSOFT_CLIENT_ID", "").strip()
TEAMS_CLIENT_SECRET = os.environ.get("MICROSOFT_CLIENT_SECRET", "").strip()
TEAMS_REDIRECT_URI = os.environ.get("MICROSOFT_REDIRECT_URI", "").strip()
TEAMS_STATES = {}





def _cf_request(path, payload):
    if not (CF_AUTH_URL and CF_AUTH_SERVICE_KEY):
        return None
    try:
        response = requests.post(f"{CF_AUTH_URL}{path}", headers={"Content-Type":"application/json", "X-Rian-Service-Key":CF_AUTH_SERVICE_KEY}, json=payload, timeout=8)
        data = response.json() if response.content else {}
        return response.status_code, data
    except requests.RequestException as error:
        print(f"[Rian AI Gen 2] Cloudflare auth request failed: {error}")
        return None

def _ensure_local_shadow(username):
    # Student data still lives in the existing account store/Gist. The password
    # itself never needs to be copied to Render when Cloudflare auth is enabled.
    with _users_lock:
        users = load_users()
        key = username.lower()
        if key not in users:
            users[key] = {"username": username, "password_hash": "CLOUDFLARE_MANAGED", "created_at": time.time()}
            save_users(users)
        return users[key]


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
    payload={"files": {GITHUB_GIST_FILENAME: {"content": json.dumps(users, indent=2)}}}
    last_error=None
    for attempt in range(2):
        try:
            response=requests.patch(f"https://api.github.com/gists/{GITHUB_GIST_ID}",headers=_github_headers(),json=payload,timeout=10)
            response.raise_for_status()
            return
        except requests.RequestException as error:
            last_error=error
            if attempt == 0: time.sleep(.35)
    if last_error:
        print(f"[Rian AI Gen 2] Warning: could not sync accounts to GitHub Gist: {last_error}")


def _gist_create_if_needed():
    """If a token is set but no gist ID, create a new private gist once and
    print its ID. The operator needs to copy that into a GITHUB_GIST_ID env
    var — without it, every restart would create a brand new empty gist
    instead of reusing the same one, which defeats the point."""
    global GITHUB_GIST_ID
    if not GITHUB_TOKEN or GITHUB_GIST_ID: return
    try:
        existing = requests.get("https://api.github.com/gists?per_page=100", headers=_github_headers(), timeout=10)
        existing.raise_for_status()
        for gist in existing.json() if isinstance(existing.json(), list) else []:
            if gist.get("description") == "Rian AI Gen 2 account store — do not edit by hand" and GITHUB_GIST_FILENAME in (gist.get("files") or {}):
                GITHUB_GIST_ID = gist.get("id", "")
                print(f"[Rian AI Gen 2] Reusing existing private account gist: {GITHUB_GIST_ID}")
                return
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
        # Account data (including flashcard sets and learning progress) must be
        # durable before the request completes. A background-only sync could
        # lose the last few edits if Render restarts immediately afterwards.
        with _gist_lock:
            try: _gist_save(json.loads(json.dumps(users)))
            except RuntimeError: pass


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
seed_admin_account() if not (CF_AUTH_URL and CF_AUTH_SERVICE_KEY) else None
# A startup diagnostic, not an error: if this reads 0 accounts on every
# restart even though people have signed up, accounts aren't actually
# persisting (no GitHub sync configured and USERS_FILE isn't on persistent
# storage — e.g. a Render free-tier service with no disk attached).
print(f"[Rian AI Gen 2] {len(load_users())} account(s) loaded"
      f"{' (synced via GitHub Gist ' + GITHUB_GIST_ID + ')' if GITHUB_TOKEN and GITHUB_GIST_ID else f' from {USERS_FILE.resolve()}'}")


def _token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def issue_token(username):
    token = secrets.token_urlsafe(48)
    expires = time.time() + SESSION_TTL_SECONDS
    with _users_lock:
        users = load_users()
        key = username.lower()
        record = users.get(key)
        if not record:
            return token
        sessions = record.setdefault("sessions", [])
        now = time.time()
        sessions[:] = [x for x in sessions if isinstance(x, dict) and float(x.get("expires_at", 0) or 0) > now]
        sessions.append({"token_hash": _token_hash(token), "created_at": now, "last_seen": now, "expires_at": expires})
        # Keep a small number of active devices per account.
        record["sessions"] = sessions[-8:]
        save_users(users)
        if GITHUB_TOKEN and GITHUB_GIST_ID:
            try:
                with _gist_lock: _gist_save(json.loads(json.dumps(users)))
            except Exception as error: print(f"[Rian AI Gen 2] Session sync warning: {error}")
    with _session_lock:
        SESSION_TOKENS[token] = expires
        SESSION_USERS[token] = username
    return token

def current_username():
    token = token_from_request()
    return username_for_token(token) if is_valid_token(token) else None

def token_from_request():
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.cookies.get(SESSION_COOKIE, "").strip() or request.args.get("token", "").strip()

def username_for_token(token):
    global _users_cache
    if not token: return None
    if CF_AUTH_URL and CF_AUTH_SERVICE_KEY:
        cached = CF_SESSION_CACHE.get(token)
        if cached and cached[1] > time.time(): return cached[0]
        result = _cf_request("/verify", {"token": token})
        if result and result[0] == 200 and result[1].get("valid"):
            username = str(result[1].get("username", "")).strip()
            if username:
                _ensure_local_shadow(username)
                CF_SESSION_CACHE[token] = (username, time.time() + CF_SESSION_TTL)
                return username
        return None
    with _session_lock:
        if token in SESSION_USERS: return SESSION_USERS[token]
    digest = _token_hash(token)
    now = time.time()
    with _users_lock:
        users = load_users()
        if GITHUB_TOKEN and GITHUB_GIST_ID:
            remote = _gist_load()
            if isinstance(remote, dict) and remote != users:
                _users_cache = remote
                users = remote
        for key, record in users.items():
            for session in record.get("sessions", []) if isinstance(record, dict) else []:
                if isinstance(session, dict) and session.get("token_hash") == digest:
                    if float(session.get("expires_at", 0) or 0) <= now: continue
                    username = record.get("username", key)
                    with _session_lock:
                        SESSION_TOKENS[token] = float(session["expires_at"]); SESSION_USERS[token] = username
                    return username
    return None

def is_valid_token(token):
    return username_for_token(token) is not None

def revoke_token(token):
    if not token: return
    if CF_AUTH_URL and CF_AUTH_SERVICE_KEY:
        _cf_request("/logout", {"token": token}); CF_SESSION_CACHE.pop(token, None); return
    digest = _token_hash(token)
    with _session_lock:
        SESSION_TOKENS.pop(token, None); SESSION_USERS.pop(token, None)
    with _users_lock:
        users = load_users(); changed = False
        for record in users.values():
            sessions = record.get("sessions", []) if isinstance(record, dict) else []
            filtered = [x for x in sessions if not (isinstance(x, dict) and x.get("token_hash") == digest)]
            if len(filtered) != len(sessions): record["sessions"] = filtered; changed = True
        if changed: save_users(users)


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
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip(); password = str(data.get("password", ""))
    if CF_AUTH_URL and CF_AUTH_SERVICE_KEY:
        result = _cf_request("/login", {"username": username, "password": password})
        if result and result[0] == 200:
            _ensure_local_shadow(result[1]["username"])
            CF_SESSION_CACHE[result[1]["token"]] = (result[1]["username"], time.time() + min(CF_SESSION_TTL, int(result[1].get("expiresIn", SESSION_TTL_SECONDS))))
            response = jsonify(ok=True, expiresIn=result[1].get("expiresIn", SESSION_TTL_SECONDS))
            response.set_cookie(SESSION_COOKIE, result[1]["token"], max_age=int(result[1].get("expiresIn", SESSION_TTL_SECONDS)), httponly=True, secure=bool(request.is_secure), samesite="Lax", path="/")
            return response
        if result and result[0] == 401: return jsonify(error=result[1].get("error", "Incorrect username or password.")), 401
        return jsonify(error="Cloudflare authentication service is unavailable. Check RIAN_AUTH_URL and RIAN_AUTH_SERVICE_KEY."), 503
    users = load_users()
    if not users: return jsonify(error='No accounts exist yet — use "Create account" below to set one up.'), 404
    record = users.get(username.lower())
    if not record:
        check_password_hash(generate_password_hash("dummy"), password); return jsonify(error="Incorrect username or password."), 401
    if record.get("password_hash") == "CLOUDFLARE_MANAGED" or not check_password_hash(record["password_hash"], password): return jsonify(error="Incorrect username or password."), 401
    token = issue_token(record["username"]); response = jsonify(ok=True, expiresIn=SESSION_TTL_SECONDS)
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_TTL_SECONDS, httponly=True, secure=bool(request.is_secure), samesite="Lax", path="/"); return response


@app.post("/api/signup")
def signup():
    if _throttled(): return jsonify(error="Too many attempts. Wait a few minutes and try again."), 429
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip(); password = str(data.get("password", ""))
    if not USERNAME_RE.match(username): return jsonify(error="Username must be 3-32 characters: letters, numbers, dots, hyphens, or underscores only."), 400
    if len(password) < 8: return jsonify(error="Password must be at least 8 characters."), 400
    if CF_AUTH_URL and CF_AUTH_SERVICE_KEY:
        result = _cf_request("/signup", {"username": username, "password": password})
        if result and result[0] == 200:
            _ensure_local_shadow(result[1]["username"])
            CF_SESSION_CACHE[result[1]["token"]] = (result[1]["username"], time.time() + min(CF_SESSION_TTL, int(result[1].get("expiresIn", SESSION_TTL_SECONDS))))
            response = jsonify(ok=True, expiresIn=result[1].get("expiresIn", SESSION_TTL_SECONDS))
            response.set_cookie(SESSION_COOKIE, result[1]["token"], max_age=int(result[1].get("expiresIn", SESSION_TTL_SECONDS)), httponly=True, secure=bool(request.is_secure), samesite="Lax", path="/"); return response
        if result and result[0] == 409: return jsonify(error="That username is already taken."), 409
        return jsonify(error="Cloudflare authentication service is unavailable. Check RIAN_AUTH_URL and RIAN_AUTH_SERVICE_KEY."), 503
    with _users_lock:
        if not create_user(username, password): return jsonify(error="That username is already taken."), 409
    token = issue_token(username); response = jsonify(ok=True, expiresIn=SESSION_TTL_SECONDS)
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_TTL_SECONDS, httponly=True, secure=bool(request.is_secure), samesite="Lax", path="/"); return response


@app.post("/api/logout")
def logout():
    revoke_token(token_from_request())
    response = jsonify(ok=True)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response



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
            "done": bool(t.get("done")), "created_at": created if isinstance(created, (int, float)) else time.time(),
            "source": str(t.get("source") or "manual")[:30], "external_id": str(t.get("external_id") or "")[:200], "web_url": _safe_url(t.get("web_url"))}


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
        cards.append({"id": str(c.get("id") or uuid.uuid4().hex)[:40], "deck": str(c.get("deck") or "General").strip()[:80] or "General", "subject": str(c.get("subject") or "").strip()[:80], "question": q[:1000], "answer": a[:2000], "starred": bool(c.get("starred", False)), "created_at": c.get("created_at") if isinstance(c.get("created_at"), (int,float)) else time.time()})
    s["flashcards"] = cards[:5000]
    # Flashcard sets are first-class account data. Empty sets and their metadata
    # therefore survive redeploys instead of being inferred only from cards.
    sets = []
    seen_set_names = set()
    raw_sets = s.get("flashcard_sets") if isinstance(s.get("flashcard_sets"), list) else []
    for fs in raw_sets:
        if not isinstance(fs, dict): continue
        name = str(fs.get("name") or "").strip()[:80]
        if not name or name.casefold() in seen_set_names: continue
        seen_set_names.add(name.casefold())
        sets.append({
            "id": str(fs.get("id") or uuid.uuid4().hex)[:40],
            "name": name,
            "description": str(fs.get("description") or "").strip()[:240],
            "subject": str(fs.get("subject") or "").strip()[:80],
            "created_at": fs.get("created_at") if isinstance(fs.get("created_at"), (int,float)) else time.time(),
            "updated_at": fs.get("updated_at") if isinstance(fs.get("updated_at"), (int,float)) else time.time(),
        })
    # Migrate older accounts: every deck already present on a card becomes a
    # persistent set record, including the default General set.
    for card in cards:
        name = str(card.get("deck") or "General").strip()[:80] or "General"
        if name.casefold() not in seen_set_names:
            seen_set_names.add(name.casefold())
            sets.append({"id": uuid.uuid4().hex, "name": name, "description": "", "subject": str(card.get("subject") or "")[:80], "created_at": time.time(), "updated_at": time.time()})
    if not sets:
        now = time.time()
        sets = [{"id": uuid.uuid4().hex, "name": "General", "description": "", "subject": "", "created_at": now, "updated_at": now}]
    s["flashcard_sets"] = sets[:500]
    progress = {}
    raw_progress = s.get("learn_progress") if isinstance(s.get("learn_progress"), dict) else {}
    for cid, st in raw_progress.items():
        if not isinstance(st, dict): continue
        try: mastery = max(0, min(2, int(st.get("mastery", 0))))
        except (TypeError, ValueError): mastery = 0
        progress[str(cid)[:40]] = {
            "mastery": mastery,
            "correct": max(0, int(st.get("correct", 0) or 0)),
            "incorrect": max(0, int(st.get("incorrect", 0) or 0)),
            "streak": max(0, int(st.get("streak", 0) or 0)),
            "due_at": float(st.get("due_at", 0) or 0),
            "last_seen": float(st.get("last_seen", 0) or 0),
        }
    s["learn_progress"] = progress


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
        "flashcard_sets": [{"id": uuid.uuid4().hex, "name": "General", "description": "", "subject": "", "created_at": time.time(), "updated_at": time.time()}],
        "learn_progress": {},
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
    return {"id": uuid.uuid4().hex, "deck": str(c.get("deck") or deck_default).strip()[:80] or "General", "subject": str(c.get("subject") or "").strip()[:80], "question": q[:1000], "answer": a[:2000], "starred": bool(c.get("starred", False)), "created_at": time.time()}, None


@app.get("/api/student/flashcard-sets")
@require_auth
def flashcard_sets():
    _, _, record = _student_record(current_username())
    if not record: return jsonify(error="Account not found."), 404
    _sanitize_student(record["student"], record.get("username", current_username()))
    return jsonify(sets=record["student"].get("flashcard_sets", []), student=record["student"])


@app.post("/api/student/flashcard-sets")
@require_auth
def create_flashcard_set():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name") or "").strip()[:80]
    if not name: return jsonify(error="Set name is required."), 400
    _, _, record = _student_record(current_username())
    if not record: return jsonify(error="Account not found."), 404
    sets = record["student"].setdefault("flashcard_sets", [])
    if any(str(x.get("name", "")).casefold() == name.casefold() for x in sets if isinstance(x, dict)):
        return jsonify(error="A set with that name already exists."), 409
    now = time.time()
    item = {"id": uuid.uuid4().hex, "name": name, "description": str(data.get("description") or "").strip()[:240], "subject": str(data.get("subject") or "").strip()[:80], "created_at": now, "updated_at": now}
    sets.append(item)
    _sanitize_student(record["student"], record.get("username", current_username()))
    if not _save_student(current_username(), record["student"]): return jsonify(error="Could not save the set."), 500
    return jsonify(ok=True, set=item, student=record["student"]), 201


@app.patch("/api/student/flashcard-sets/<set_id>")
@require_auth
def patch_flashcard_set(set_id):
    data = request.get_json(silent=True) or {}
    _, _, record = _student_record(current_username())
    if not record: return jsonify(error="Account not found."), 404
    sets = record["student"].setdefault("flashcard_sets", [])
    item = next((x for x in sets if isinstance(x, dict) and x.get("id") == set_id), None)
    if not item: return jsonify(error="Set not found."), 404
    if "name" in data:
        name = str(data.get("name") or "").strip()[:80]
        if not name: return jsonify(error="Set name is required."), 400
        if any(x is not item and str(x.get("name", "")).casefold() == name.casefold() for x in sets if isinstance(x, dict)):
            return jsonify(error="A set with that name already exists."), 409
        old_name = item["name"]
        item["name"] = name
        for card in record["student"].get("flashcards", []):
            if str(card.get("deck") or "General") == old_name: card["deck"] = name
    for key, limit in (("description",240),("subject",80)):
        if key in data: item[key] = str(data.get(key) or "").strip()[:limit]
    item["updated_at"] = time.time()
    _sanitize_student(record["student"], record.get("username", current_username()))
    if not _save_student(current_username(), record["student"]): return jsonify(error="Could not save the set."), 500
    return jsonify(ok=True, set=item, student=record["student"])


@app.delete("/api/student/flashcard-sets/<set_id>")
@require_auth
def delete_flashcard_set(set_id):
    _, _, record = _student_record(current_username())
    if not record: return jsonify(error="Account not found."), 404
    sets = record["student"].setdefault("flashcard_sets", [])
    item = next((x for x in sets if isinstance(x, dict) and x.get("id") == set_id), None)
    if not item: return jsonify(error="Set not found."), 404
    if len(sets) <= 1: return jsonify(error="Keep at least one flashcard set."), 400
    if any(str(c.get("deck") or "General").casefold() == str(item.get("name") or "").casefold() for c in record["student"].get("flashcards", [])):
        return jsonify(error="Move or delete the cards in this set before deleting it."), 409
    record["student"]["flashcard_sets"] = [x for x in sets if x is not item]
    if not _save_student(current_username(), record["student"]): return jsonify(error="Could not delete the set."), 500
    return jsonify(ok=True, student=record["student"])


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
    sets=record["student"].setdefault("flashcard_sets", [])
    if not any(str(x.get("name","")).casefold()==deck.casefold() for x in sets if isinstance(x,dict)):
        now=time.time(); sets.append({"id":uuid.uuid4().hex,"name":deck,"description":"","subject":subject,"created_at":now,"updated_at":now})
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
    old_deck = card.get("deck", "General")
    for k,limit in (("question",1000),("answer",2000),("deck",80),("subject",80)):
        if k in data: card[k]=str(data[k] or "").strip()[:limit]
    if card.get("deck") != old_deck:
        sets=record["student"].setdefault("flashcard_sets", [])
        if not any(str(x.get("name","")).casefold()==str(card.get("deck") or "General").casefold() for x in sets if isinstance(x,dict)):
            now=time.time(); sets.append({"id":uuid.uuid4().hex,"name":card.get("deck") or "General","description":"","subject":card.get("subject") or "","created_at":now,"updated_at":now})
    if "starred" in data: card["starred"] = bool(data.get("starred"))
    if not card.get("question") or not card.get("answer"): return jsonify(error="Question and answer are required."),400
    _save_student(current_username(),record["student"]); return jsonify(card=card)


@app.delete("/api/student/flashcards/<card_id>")
@require_auth
def delete_flashcard(card_id):
    _,_,record=_student_record(current_username()); cards=record["student"].setdefault("flashcards", [])
    new=[c for c in cards if c.get("id")!=card_id]
    if len(new)==len(cards): return jsonify(error="Flashcard not found."),404
    record["student"]["flashcards"]=new; _save_student(current_username(),record["student"]); return jsonify(ok=True)


@app.post("/api/student/learn/answer")
@require_auth
def learn_answer():
    data = request.get_json(silent=True) or {}
    card_id = str(data.get("card_id") or "").strip()
    correct = bool(data.get("correct"))
    if not card_id: return jsonify(error="Card id is required."), 400
    _, _, record = _student_record(current_username())
    if not record: return jsonify(error="Account not found."), 404
    cards = record["student"].setdefault("flashcards", [])
    if not any(c.get("id") == card_id for c in cards): return jsonify(error="Flashcard not found."), 404
    progress = record["student"].setdefault("learn_progress", {})
    st = progress.setdefault(card_id, {"mastery":0,"correct":0,"incorrect":0,"streak":0,"due_at":0,"last_seen":0})
    now = time.time(); st["last_seen"] = now
    if correct:
        st["correct"] = int(st.get("correct",0))+1; st["streak"] = int(st.get("streak",0))+1
        st["mastery"] = min(2, int(st.get("mastery",0))+1)
        intervals = {1: 6*3600, 2: 2*86400}
        st["due_at"] = now + intervals.get(st["mastery"], 6*3600)
    else:
        st["incorrect"] = int(st.get("incorrect",0))+1; st["streak"] = 0
        st["mastery"] = max(0, int(st.get("mastery",0))-1)
        st["due_at"] = now + 5*60
    _sanitize_student(record["student"], record.get("username", current_username()))
    if not _save_student(current_username(), record["student"]): return jsonify(error="Could not save Learn progress."), 500
    return jsonify(ok=True, progress=st, student=record["student"])


@app.get("/api/teams/connect")
@require_auth
def teams_connect():
    if not (TEAMS_CLIENT_ID and TEAMS_CLIENT_SECRET and TEAMS_REDIRECT_URI):
        return jsonify(error="Microsoft Teams integration is not configured on this Render service."), 503
    username = current_username()
    state = secrets.token_urlsafe(32)
    TEAMS_STATES[state] = (username, time.time() + 600)
    from urllib.parse import urlencode
    params = {
        "client_id": TEAMS_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": TEAMS_REDIRECT_URI,
        "response_mode": "query",
        "scope": "openid profile offline_access EduAssignments.ReadBasic",
        "state": state,
    }
    return redirect("https://login.microsoftonline.com/common/oauth2/v2.0/authorize?" + urlencode(params))


@app.get("/api/teams/callback")
def teams_callback():
    state = request.args.get("state", "")
    entry = TEAMS_STATES.pop(state, None)
    if not entry or entry[1] < time.time(): return "Teams connection expired. Return to Rian AI and try again.", 400
    username = entry[0]
    if request.args.get("error"):
        return redirect("/?teams=cancelled#tasks")
    code = request.args.get("code", "")
    if not code: return "Microsoft did not return an authorization code.", 400
    token_response = requests.post("https://login.microsoftonline.com/common/oauth2/v2.0/token", data={
        "client_id": TEAMS_CLIENT_ID, "client_secret": TEAMS_CLIENT_SECRET, "grant_type": "authorization_code",
        "code": code, "redirect_uri": TEAMS_REDIRECT_URI, "scope": "openid profile offline_access EduAssignments.ReadBasic"
    }, timeout=15)
    if not token_response.ok: return "Microsoft sign-in could not be completed. Check your Entra app configuration.", 502
    token = token_response.json().get("access_token", "")
    if not token: return "Microsoft did not return an access token.", 502
    graph = requests.get("https://graph.microsoft.com/v1.0/education/me/assignments?$orderby=dueDateTime%20asc", headers={"Authorization": f"Bearer {token}"}, timeout=20)
    if not graph.ok: return "Microsoft connected, but Rian could not read your Teams assignments. Your school may need to grant EduAssignments.ReadBasic.", 502
    payload = graph.json(); assignments = payload.get("value", []) if isinstance(payload, dict) else []
    _, _, record = _student_record(username)
    if not record: return "Account not found.", 404
    tasks = record["student"].setdefault("tasks", [])
    existing = {str(t.get("external_id")) for t in tasks if t.get("source") == "microsoft_teams"}
    imported = 0
    for a in assignments:
        aid = str(a.get("id") or "").strip(); title = str(a.get("displayName") or "Teams assignment").strip()
        if not aid or not title or aid in existing: continue
        due_raw = a.get("dueDateTime") or ""
        due = str(due_raw)[:10] if due_raw else ""
        task = {"id": uuid.uuid4().hex, "title": title[:160], "subject": "Microsoft Teams", "due": due,
                "priority": "high" if due and due <= time.strftime("%Y-%m-%d") else "normal", "done": False,
                "created_at": time.time(), "source": "microsoft_teams", "external_id": aid, "web_url": _safe_url(a.get("webUrl"))}
        tasks.append(task); imported += 1
    _sanitize_student(record["student"], username); _save_student(username, record["student"])
    return redirect(f"/?teams=connected&imported={imported}#tasks")


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

