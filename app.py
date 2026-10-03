"""Rian AI Gen 2 — a built-in Ollama-powered student hub."""
import json
import math
import mimetypes
import os
import re
import secrets
import textwrap
import threading
import time
import uuid
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path, PurePosixPath
from urllib.parse import quote

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


def load_users():
    remote = _gist_load()
    if remote is not None: return remote
    if not USERS_FILE.exists(): return {}
    try:
        return json.loads(USERS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_users(users):
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    USERS_FILE.write_text(json.dumps(users, indent=2))
    _gist_save(users)


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

# Pollinations.ai — free, keyless text-to-image API. Used for the "image" file kind.
POLLINATIONS_URL = "https://image.pollinations.ai/prompt/{prompt}"

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
BEST_MODEL = "gpt-oss:120b"  # largest/most capable in our catalogue — auto-used for 3D modeling requests, see chat()
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}

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

_3D_REQUEST_PATTERN = re.compile(
    r"\b(3d|three[\s-]?dimensional|stl|cad|\bprint(?:able|ed)?\b.*\b(model|part|object|design)|"
    r"model.*\bprint\b|design.*\bprint\b|mount(?:ing)?\s*bracket|\bbracket\b|\bfigurine\b|\bmini(?:ature)?\b|"
    r"\bsculpt|\bmesh\b|\bmold\b)\b", re.IGNORECASE)

def looks_like_3d_request(prompt):
    """Heuristic used to auto-select the strongest available model (and force
    max reasoning effort) specifically for 3D-modeling requests, regardless
    of whatever model/power the person has picked — 3D geometry is the one
    output type here where model capability directly limits build quality."""
    return bool(_3D_REQUEST_PATTERN.search(prompt))

SYSTEM = '''You are Rian AI Gen 2, the built-in student AI assistant.

Return ONLY a helpful plain-text/Markdown response to the user's request. NEVER create, describe, attach, encode, save, preview, download, or return files or file-generation instructions. Do not output JSON wrappers or artifact metadata. If a user asks for a file, explain the content directly in the chat instead and offer a copyable text version when appropriate.

You are especially good at explaining school subjects, making quizzes, exam-style questions, revision plans, study techniques, homework guidance, course planning, and helping students understand questions. Be concise but useful, use clear headings/bullets when helpful, and do not pretend to have access to school systems or private information you were not given.'''



class ReplyStreamExtractor:
    """Incrementally decodes the "reply" string field out of a partial JSON
    buffer as it streams in from the model, token chunk by token chunk —
    without waiting for the whole (reply + files) JSON object to finish, so
    the person sees the chat text appear live instead of staring at a
    spinner for the full generation. Only ever emits fully-decoded
    characters (correctly unescaping \\", \\n, \\uXXXX, etc.); an incomplete
    trailing escape sequence is held back until more of the buffer arrives.
    If the model never emits a well-formed "reply" key, this simply never
    finds a start point and emits nothing — falling back to no worse than
    the old "type indicator until done" behavior."""

    _KEY_PATTERN = re.compile(r'"reply"\s*:\s*"')
    _SIMPLE_ESCAPES = {'"': '"', '\\': '\\', '/': '/', 'n': '\n', 't': '\t', 'r': '\r', 'b': '\b', 'f': '\f'}

    def __init__(self):
        self.buffer = ""
        self.reply_start = None
        self.emitted = ""
        self.finished = False

    def feed(self, chunk):
        if self.finished or not chunk:
            return ""
        self.buffer += chunk
        if self.reply_start is None:
            match = self._KEY_PATTERN.search(self.buffer)
            if not match:
                return ""
            self.reply_start = match.end()
        decoded, closed = self._decode_partial(self.buffer, self.reply_start)
        new_text = decoded[len(self.emitted):]
        self.emitted = decoded
        if closed:
            self.finished = True
        return new_text

    @classmethod
    def _decode_partial(cls, buf, start):
        out = []
        i, n = start, len(buf)
        while i < n:
            c = buf[i]
            if c == '"':
                return "".join(out), True  # unescaped closing quote — string is complete
            if c == '\\':
                if i + 1 >= n:
                    break  # incomplete escape at the buffer's end — wait for more to arrive
                nxt = buf[i + 1]
                if nxt in cls._SIMPLE_ESCAPES:
                    out.append(cls._SIMPLE_ESCAPES[nxt]); i += 2; continue
                if nxt == 'u':
                    if i + 6 > n:
                        break  # incomplete \\uXXXX — wait for more
                    try:
                        out.append(chr(int(buf[i + 2:i + 6], 16))); i += 6; continue
                    except ValueError:
                        i += 2; continue  # malformed escape — skip it rather than crash the stream
                out.append(nxt); i += 2; continue  # unrecognized escape — drop the backslash, keep the char
            out.append(c); i += 1
        return "".join(out), False  # ran out of buffer without hitting the closing quote yet


def decode_model_result(content):
    """Accept strict JSON, fenced JSON, and imperfect free-model output."""
    text = str(content or "").strip()
    if not text:
        raise ValueError("The selected model returned an empty response. Try another free model or retry.")
    candidates = [text]
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if fenced: candidates.append(fenced.group(1))
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start: candidates.append(text[start:end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict): return parsed
        except json.JSONDecodeError:
            continue
    # Free models sometimes ignore structured-output instructions. Preserve their work.
    return {"reply": "The model returned unstructured output, saved below.", "files": [{"path": "generation.md", "kind": "text", "content": text}]}


def safe_path(value):
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.parts or path.name in ("", "."):
        raise ValueError("Unsafe output filename")
    if len(path.parts) > 1 and re.match(r"^[a-zA-Z]:$", path.parts[0]):
        raise ValueError("Unsafe output filename")  # reject Windows-style drive prefixes too
    return path


# ---- Parametric solid-build engine for the "stl" kind ---------------------
# Rather than trust free models to emit raw, hand-rolled vertex/face lists
# (which are easy to get non-manifold or malformed), Rian AI Gen 2 exposes a small
# instruction set — add a primitive, repeat it with a rotation/translation —
# and executes that program itself. The model writes the build steps; Forge
# turns them into real, valid geometry.
MAX_TRIANGLES = 260_000  # generous cap (user explicitly OK with slower/bigger builds) so a runaway program still can't hang the worker indefinitely
MAX_OPS = 160
MAX_REPEAT_COUNT = 120


def _clamp_segments(value, lo=6, hi=64):
    try: return max(lo, min(int(round(float(value))), hi))
    except (TypeError, ValueError): return 16


def _auto_segments(size_metric, explicit):
    """When the model doesn't specify a segment count, scale it with the
    part's own size instead of using one fixed default — bigger round parts
    get smoother curves automatically, which reads as far more realistic
    without requiring the model to reason about facet counts itself."""
    if explicit is not None: return _clamp_segments(explicit)
    return _clamp_segments(round(abs(size_metric) * 1.3) + 12, 14, 64)


def _box_triangles(size):
    w, d, h = ((size, size, size) if not isinstance(size, (list, tuple)) else (list(size) + [size[0] if size else 20]*3)[:3])
    w, d, h = float(w), float(d), float(h)
    hw, hd, hh = w/2, d/2, h/2
    v = [(-hw,-hd,-hh),(hw,-hd,-hh),(hw,hd,-hh),(-hw,hd,-hh),(-hw,-hd,hh),(hw,-hd,hh),(hw,hd,hh),(-hw,hd,hh)]
    faces = [(0,2,1),(0,3,2),(4,5,6),(4,6,7),(0,1,5),(0,5,4),(1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,0,4),(3,4,7)]
    return [(v[a], v[b], v[c]) for a, b, c in faces]


def _box_with_bore_canonical(size, radius, segments):
    """A box with a round hole bored straight through it along its local
    z-axis. Built directly with an explicit, hand-verified triangulation
    (radial "rim" bridge between the bore circle and the box's rectangular
    cross-section) rather than a general boolean/CSG algorithm — an earlier,
    general-purpose triangle-mesh boolean engine was tried for this and
    discarded after testing found it produced subtly self-intersecting
    geometry on realistic (non-axis-trivial) shapes; this construction is
    provably correct by how it's built, and is verified watertight (manifold)
    and hole-correct (via ray-casting) for every supported axis."""
    w, d, h = size
    hw, hd, hh = w / 2, d / 2, h / 2
    radius = min(float(radius), min(hw, hd) * 0.92)  # keep the hole comfortably inside the footprint

    def rim_point(theta):
        c, s = math.cos(theta), math.sin(theta)
        candidates = []
        if abs(c) > 1e-9: candidates.append(hw / abs(c))
        if abs(s) > 1e-9: candidates.append(hd / abs(s))
        t = min(candidates)
        return (t * c, t * s)

    circle = [(radius * math.cos(2*math.pi*i/segments), radius * math.sin(2*math.pi*i/segments)) for i in range(segments)]
    rim = [rim_point(2 * math.pi * i / segments) for i in range(segments)]

    tris = []
    for i in range(segments):
        j = (i + 1) % segments
        c0, c1, r0, r1 = circle[i], circle[j], rim[i], rim[j]
        # top/bottom annular faces (rectangle-with-round-hole)
        tris += [((c0[0],c0[1],hh), (c1[0],c1[1],hh), (r1[0],r1[1],hh)),
                 ((c0[0],c0[1],hh), (r1[0],r1[1],hh), (r0[0],r0[1],hh)),
                 ((c0[0],c0[1],-hh), (r0[0],r0[1],-hh), (r1[0],r1[1],-hh)),
                 ((c0[0],c0[1],-hh), (r1[0],r1[1],-hh), (c1[0],c1[1],-hh))]
        # inner bore wall
        top0, top1, bot0, bot1 = (c0[0],c0[1],hh), (c1[0],c1[1],hh), (c0[0],c0[1],-hh), (c1[0],c1[1],-hh)
        tris += [(bot1, bot0, top0), (bot1, top0, top1)]
        # outer side wall — deliberately subdivided to match the annulus's own
        # rim points exactly (not one flat quad per box side), since that
        # mismatch is what caused the seam bug found during testing.
        rtop0, rtop1, rbot0, rbot1 = (r0[0],r0[1],hh), (r1[0],r1[1],hh), (r0[0],r0[1],-hh), (r1[0],r1[1],-hh)
        tris += [(rbot0, rbot1, rtop1), (rbot0, rtop1, rtop0)]
    return tris


def _box_with_bore(size, radius, segments=24, axis="z"):
    sx, sy, sz = ((size, size, size) if not isinstance(size, (list, tuple)) else (list(size) + [size[0] if size else 20]*3)[:3])
    sx, sy, sz = float(sx), float(sy), float(sz)
    segments = _clamp_segments(segments, 12, 64)
    axis = str(axis).lower()
    if axis == "x":
        canonical_size, permute = (sy, sz, sx), (lambda u, v, w: (w, u, v))
    elif axis == "y":
        canonical_size, permute = (sz, sx, sy), (lambda u, v, w: (v, w, u))
    else:
        canonical_size, permute = (sx, sy, sz), (lambda u, v, w: (u, v, w))
    raw = _box_with_bore_canonical(canonical_size, radius, segments)
    return [tuple(permute(*p) for p in tri) for tri in raw]


def _wedge_triangles(size):
    """A ramp/doorstop/roof shape: a rectangular base tapering up to a ridge
    along one edge, sloped down along x. Useful for ramps, roofs, chocks."""
    w, d, h = ((size, size, size) if not isinstance(size, (list, tuple)) else (list(size) + [size[0] if size else 20]*3)[:3])
    w, d, h = float(w), float(d), float(h)
    hw, hd, hh = w/2, d/2, h/2
    b0,b1,b2,b3 = (-hw,-hd,-hh),(hw,-hd,-hh),(hw,hd,-hh),(-hw,hd,-hh)
    t0,t1 = (-hw,0,hh),(hw,0,hh)
    return [
        (b0,b2,b1),(b0,b3,b2),          # bottom
        (b0,b1,t1),(b0,t1,t0),          # front slope (y=-hd side)
        (b3,t0,t1),(b3,t1,b2),          # back slope (y=+hd side)
        (b0,t0,b3),                     # left end cap
        (b1,b2,t1),                     # right end cap
    ]


def _pyramid_triangles(size, height=None):
    h = float(size) / 2; height = float(height) if height is not None else float(size); z0, z1 = -height/2, height/2
    v = [(-h,-h,z0),(h,-h,z0),(h,h,z0),(-h,h,z0),(0,0,z1)]
    faces = [(0,2,1),(0,3,2),(0,1,4),(1,2,4),(2,3,4),(3,0,4)]
    return [(v[a], v[b], v[c]) for a, b, c in faces]


def _sphere_triangles(radius, segments=16):
    segments = _clamp_segments(segments); stacks = max(4, segments // 2)
    tris = []
    for i in range(stacks):
        lat0 = math.pi * (-0.5 + i / stacks); lat1 = math.pi * (-0.5 + (i + 1) / stacks)
        for j in range(segments):
            lon0 = 2 * math.pi * j / segments; lon1 = 2 * math.pi * (j + 1) / segments
            def pt(lat, lon): return (radius*math.cos(lat)*math.cos(lon), radius*math.cos(lat)*math.sin(lon), radius*math.sin(lat))
            p00, p01, p10, p11 = pt(lat0,lon0), pt(lat0,lon1), pt(lat1,lon0), pt(lat1,lon1)
            if i != 0: tris.append((p00, p01, p11))
            if i != stacks - 1: tris.append((p00, p11, p10))
    return tris


def _hemisphere_triangles(radius, segments=16, upper=True):
    """Half a sphere, flat/open side on the z=0 plane — used to cap capsules
    so they seal flush against the cylinder body. Unlike a full sphere, only
    ONE end (the pole, away from z=0) collapses to a point; the z=0 ring is
    a full-radius rim and must keep both triangles of every quad so its
    boundary edges exist to seal against the adjoining cylinder wall."""
    segments = _clamp_segments(segments); stacks = max(3, segments // 4)
    sign = 1 if upper else -1
    tris = []
    for i in range(stacks):
        lat0 = sign * (math.pi/2) * (i / stacks); lat1 = sign * (math.pi/2) * ((i + 1) / stacks)
        pole_row = (i == stacks - 1)  # only the far row degenerates to a point
        for j in range(segments):
            lon0 = 2 * math.pi * j / segments; lon1 = 2 * math.pi * (j + 1) / segments
            def pt(lat, lon): return (radius*math.cos(lat)*math.cos(lon), radius*math.cos(lat)*math.sin(lon), radius*math.sin(lat))
            p00, p01, p10, p11 = pt(lat0,lon0), pt(lat0,lon1), pt(lat1,lon0), pt(lat1,lon1)
            if upper:
                tris.append((p00, p01, p11))
                if not pole_row: tris.append((p00, p11, p10))
            else:
                tris.append((p00, p11, p01))
                if not pole_row: tris.append((p00, p10, p11))
    return tris


def _cylinder_side_triangles(radius, height, segments=16):
    segments = _clamp_segments(segments); h = height / 2
    tris = []
    for j in range(segments):
        a0, a1 = 2*math.pi*j/segments, 2*math.pi*(j+1)/segments
        x0,y0,x1,y1 = radius*math.cos(a0), radius*math.sin(a0), radius*math.cos(a1), radius*math.sin(a1)
        top0,top1,bot0,bot1 = (x0,y0,h),(x1,y1,h),(x0,y0,-h),(x1,y1,-h)
        tris += [(bot0,bot1,top1),(bot0,top1,top0)]
    return tris


def _cylinder_triangles(radius, height, segments=16):
    segments = _clamp_segments(segments); h = height / 2
    tris = _cylinder_side_triangles(radius, height, segments)
    for j in range(segments):
        a0, a1 = 2*math.pi*j/segments, 2*math.pi*(j+1)/segments
        x0,y0,x1,y1 = radius*math.cos(a0), radius*math.sin(a0), radius*math.cos(a1), radius*math.sin(a1)
        top0,top1,bot0,bot1 = (x0,y0,h),(x1,y1,h),(x0,y0,-h),(x1,y1,-h)
        tris += [(top0,top1,(0,0,h)), (bot1,bot0,(0,0,-h))]
    return tris


def _cone_triangles(radius, height, segments=16):
    segments = _clamp_segments(segments); apex = (0,0,height/2); h = height/2
    tris = []
    for j in range(segments):
        a0, a1 = 2*math.pi*j/segments, 2*math.pi*(j+1)/segments
        x0,y0,x1,y1 = radius*math.cos(a0), radius*math.sin(a0), radius*math.cos(a1), radius*math.sin(a1)
        base0, base1 = (x0,y0,-h), (x1,y1,-h)
        tris += [(base0, base1, apex), (base1, base0, (0,0,-h))]
    return tris


def _torus_triangles(major_radius, tube_radius, segments=24, tube_segments=12):
    segments = _clamp_segments(segments, 8, 64); tube_segments = _clamp_segments(tube_segments, 6, 32)
    tris = []
    def pt(u, v): return ((major_radius+tube_radius*math.cos(v))*math.cos(u), (major_radius+tube_radius*math.cos(v))*math.sin(u), tube_radius*math.sin(v))
    for i in range(segments):
        u0, u1 = 2*math.pi*i/segments, 2*math.pi*(i+1)/segments
        for j in range(tube_segments):
            v0, v1 = 2*math.pi*j/tube_segments, 2*math.pi*(j+1)/tube_segments
            p00, p01, p10, p11 = pt(u0,v0), pt(u0,v1), pt(u1,v0), pt(u1,v1)
            tris += [(p00, p10, p11), (p00, p11, p01)]
    return tris


def _tube_triangles(outer_radius, inner_radius, height, segments=16):
    """A hollow pipe/ring/washer: two concentric cylindrical walls joined by
    flat annular caps top and bottom — genuinely hollow, not an approximation."""
    segments = _clamp_segments(segments); inner_radius = max(0.001, min(inner_radius, outer_radius - 0.001)); h = height / 2
    tris = []
    for j in range(segments):
        a0, a1 = 2*math.pi*j/segments, 2*math.pi*(j+1)/segments
        ox0,oy0,ox1,oy1 = outer_radius*math.cos(a0), outer_radius*math.sin(a0), outer_radius*math.cos(a1), outer_radius*math.sin(a1)
        ix0,iy0,ix1,iy1 = inner_radius*math.cos(a0), inner_radius*math.sin(a0), inner_radius*math.cos(a1), inner_radius*math.sin(a1)
        o_top0,o_top1,o_bot0,o_bot1 = (ox0,oy0,h),(ox1,oy1,h),(ox0,oy0,-h),(ox1,oy1,-h)
        i_top0,i_top1,i_bot0,i_bot1 = (ix0,iy0,h),(ix1,iy1,h),(ix0,iy0,-h),(ix1,iy1,-h)
        tris += [(o_bot0,o_bot1,o_top1),(o_bot0,o_top1,o_top0)]           # outer wall
        tris += [(i_bot1,i_bot0,i_top0),(i_bot1,i_top0,i_top1)]           # inner wall (reversed so it faces inward)
        tris += [(o_top0,o_top1,i_top1),(o_top0,i_top1,i_top0)]           # top annulus
        tris += [(o_bot1,o_bot0,i_bot0),(o_bot1,i_bot0,i_bot1)]           # bottom annulus
    return tris


def _capsule_triangles(radius, height=0.0, segments=16):
    """A pill/stadium shape: a straight cylindrical section capped with two
    hemispheres — for handles, pills, rounded rods, fingers, rounded ends."""
    segments = _clamp_segments(segments); half = max(float(height), 0.0) / 2
    tris = _cylinder_side_triangles(radius, height, segments) if height > 0 else []
    tris += [tuple((x, y, z + half) for x, y, z in tri) for tri in _hemisphere_triangles(radius, segments, upper=True)]
    tris += [tuple((x, y, z - half) for x, y, z in tri) for tri in _hemisphere_triangles(radius, segments, upper=False)]
    return tris


def _shape_radius(s, default=10):
    if "radius" in s: return float(s["radius"])
    if "size" in s and not isinstance(s["size"], (list, tuple)): return float(s["size"]) / 2
    return float(default)


def build_local_shape(spec):
    """Build a shape centered on its own local origin, unrotated/unscaled/unplaced."""
    shape = spec.get("shape", "box")
    if shape in ("box", "cube"):
        bore = spec.get("bore")
        if bore and isinstance(bore, dict):
            size = spec.get("size", 20)
            footprint = (size, size, size) if not isinstance(size, (list, tuple)) else (list(size) + [size[0] if size else 20]*3)[:3]
            return _box_with_bore(size, float(bore.get("radius", min(footprint[0], footprint[1]) * 0.25)), bore.get("segments", 24), bore.get("axis", "z"))
        return _box_triangles(spec.get("size", 20))
    if shape == "wedge": return _wedge_triangles(spec.get("size", 20))
    if shape == "pyramid": return _pyramid_triangles(spec.get("size", 20), spec.get("height"))
    if shape == "sphere":
        r = _shape_radius(spec); return _sphere_triangles(r, _auto_segments(r, spec.get("segments")))
    if shape == "cylinder":
        r = _shape_radius(spec); return _cylinder_triangles(r, float(spec.get("height", spec.get("size", 20))), _auto_segments(r, spec.get("segments")))
    if shape == "cone":
        r = _shape_radius(spec); return _cone_triangles(r, float(spec.get("height", spec.get("size", 20))), _auto_segments(r, spec.get("segments")))
    if shape == "torus":
        r = float(spec.get("radius", 20)); return _torus_triangles(r, float(spec.get("tube", spec.get("minor_radius", 5))), _auto_segments(r, spec.get("segments")), spec.get("tube_segments", 12))
    if shape == "tube":
        outer = _shape_radius(spec, 15); inner = float(spec.get("inner_radius", spec.get("inner", outer * 0.6)))
        return _tube_triangles(outer, inner, float(spec.get("height", 20)), _auto_segments(outer, spec.get("segments")))
    if shape == "capsule":
        r = _shape_radius(spec, 8); return _capsule_triangles(r, float(spec.get("height", 0)), _auto_segments(r, spec.get("segments")))
    raise ValueError(f"Unknown shape '{shape}'")


def _rotate_point(p, rotation_deg):
    x, y, z = p
    rx, ry, rz = (math.radians(v) for v in rotation_deg)
    y, z = y*math.cos(rx)-z*math.sin(rx), y*math.sin(rx)+z*math.cos(rx)
    x, z = x*math.cos(ry)+z*math.sin(ry), -x*math.sin(ry)+z*math.cos(ry)
    x, y = x*math.cos(rz)-y*math.sin(rz), x*math.sin(rz)+y*math.cos(rz)
    return (x, y, z)


def _place_triangles(tris, scale=(1,1,1), rotation=(0,0,0), position=(0,0,0)):
    sx, sy, sz = scale
    out = []
    for tri in tris:
        placed = []
        for (x, y, z) in tri:
            x, y, z = x*sx, y*sy, z*sz
            x, y, z = _rotate_point((x, y, z), rotation)
            placed.append((x+position[0], y+position[1], z+position[2]))
        out.append(tuple(placed))
    return out


def _rotate_triangles_around(tris, rotation_deg, pivot):
    px, py, pz = pivot
    out = []
    for tri in tris:
        rotated = []
        for (x, y, z) in tri:
            rx, ry, rz = _rotate_point((x-px, y-py, z-pz), rotation_deg)
            rotated.append((rx+px, ry+py, rz+pz))
        out.append(tuple(rotated))
    return out


def _vec3(value, default=(0.0, 0.0, 0.0)):
    if not value: return default
    values = list(value) + list(default)
    return tuple(float(v) for v in values[:3])


def _mirror_triangles(tris, axis, offset=0.0):
    """Mirror a set of triangles across an axis-aligned plane (x=offset,
    y=offset, or z=offset). Mirroring flips handedness, so winding is
    reversed to keep normals pointing outward after the flip."""
    idx = {"x": 0, "y": 1, "z": 2}.get(axis, 0)
    out = []
    for tri in tris:
        mirrored = []
        for p in tri:
            p = list(p); p[idx] = 2 * offset - p[idx]; mirrored.append(tuple(p))
        out.append((mirrored[0], mirrored[2], mirrored[1]))
    return out


def run_stl_program(spec):
    """Interpret the model's ordered build steps ("ops") into world-space
    triangles. Supports "add" (place a primitive, optionally scaled/rotated),
    "repeat" (duplicate the previous add with a cumulative rotation and/or
    translation per copy — radial or linear patterns), and "mirror" (reflect
    the previous add across an axis-aligned plane — symmetric designs like
    wings, hulls, or matched brackets). Each op is executed independently: if
    one is malformed, it's skipped with a recorded note instead of failing
    the whole model, so a single bad part never throws away an otherwise-good
    design. Returns (triangles, notes) — notes are pre-formatted, human
    readable strings (warnings and a final size summary)."""
    ops = spec.get("ops") if isinstance(spec, dict) else None
    if not ops:
        # Back-compat with the earlier, simpler schemas.
        if isinstance(spec, dict) and spec.get("shapes"): ops = [{"op": "add", **item} for item in spec["shapes"]]
        elif isinstance(spec, dict) and spec.get("shape"): ops = [{"op": "add", **spec}]
        else: raise ValueError("STL spec has no ops/shapes/shape to build from")

    triangles, last_placed, notes = [], None, []
    for index, op in enumerate(ops[:MAX_OPS]):
        kind = op.get("op", "add")
        try:
            if kind == "add":
                local = build_local_shape(op)
                placed = _place_triangles(local, _vec3(op.get("scale"), (1, 1, 1)), _vec3(op.get("rotation")), _vec3(op.get("position")))
                triangles += placed
                last_placed = placed
            elif kind == "repeat":
                if not last_placed: raise ValueError("repeat with nothing preceding it to repeat")
                count = max(1, min(int(op.get("count", 1)), MAX_REPEAT_COUNT))
                translate_step, rotate_step, pivot = _vec3(op.get("translate")), _vec3(op.get("rotate")), _vec3(op.get("around"))
                for i in range(1, count):
                    step = last_placed
                    if any(rotate_step): step = _rotate_triangles_around(step, tuple(a*i for a in rotate_step), pivot)
                    if any(translate_step):
                        dx, dy, dz = (a*i for a in translate_step)
                        step = [tuple((x+dx, y+dy, z+dz) for x, y, z in tri) for tri in step]
                    triangles += step
            elif kind == "mirror":
                if not last_placed: raise ValueError("mirror with nothing preceding it to mirror")
                axis = str(op.get("axis", "x")).lower()
                if axis not in ("x", "y", "z"): raise ValueError(f"mirror axis must be x/y/z, got '{axis}'")
                triangles += _mirror_triangles(last_placed, axis, float(op.get("offset", 0)))
            else:
                notes.append(f"⚠️ Step {index+1}: unknown op '{kind}' — skipped.")
        except (ValueError, TypeError, KeyError, ZeroDivisionError, ArithmeticError) as error:
            notes.append(f"⚠️ Step {index+1} ({kind}): {error} — skipped, rest of the model was still built.")
        if len(triangles) > MAX_TRIANGLES:
            raise ValueError("That design is too complex to build (too many triangles) — simplify it")
    if not triangles:
        raise ValueError("STL program produced no geometry")

    xs = [p[0] for tri in triangles for p in tri]; ys = [p[1] for tri in triangles for p in tri]; zs = [p[2] for tri in triangles for p in tri]
    notes.append(f"ℹ️ Model size: {max(xs)-min(xs):.1f} × {max(ys)-min(ys):.1f} × {max(zs)-min(zs):.1f} units, {len(triangles)} triangles.")
    return triangles, notes


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
    }


def _student_record(username):
    with _users_lock:
        users = load_users()
        key = username.lower()
        record = users.get(key)
        if not record:
            return None, None, None
        record.setdefault("student", _default_student())
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
                    courses.append({"name": name[:120], "course": str(item.get("course", "")).strip()[:120], "exam_board": str(item.get("exam_board", item.get("examBoard", ""))).strip()[:80], "specification": str(item.get("specification", item.get("spec_link", ""))).strip()[:500], "progress": progress})
        current["subjects"] = courses
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
    for key in ("title", "subject", "due", "priority", "done"):
        if key in data: task[key] = data[key]
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
    messages = [{"role":"system","content":SYSTEM}]
    for m in data.get("history", [])[-10:]:
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
                piece=(chunk.get("message") or {}).get("content","")
                if piece: yield json.dumps({"type":"delta","text":piece},ensure_ascii=False)+"\n"
                if chunk.get("done"): yield json.dumps({"type":"done"})+"\n"; break
        except requests.RequestException as error: yield json.dumps({"type":"error","error":f"Connection to Ollama Cloud dropped: {error}"})+"\n"
        except Exception as error: yield json.dumps({"type":"error","error":f"Generation failed: {error}"})+"\n"
        finally: upstream.close()
    return Response(stream_with_context(generate()),mimetype="application/x-ndjson")

