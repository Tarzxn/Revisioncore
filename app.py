"""Forge (Gen 2) — an Ollama Cloud-powered, downloadable file workspace."""
import base64
import io
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
import zipfile
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import requests
from flask import Flask, Response, abort, jsonify, render_template, request, send_file, stream_with_context
from werkzeug.security import check_password_hash, generate_password_hash
from docx import Document
from docx.shared import Pt
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from pptx import Presentation
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import matplotlib
matplotlib.use("Agg")  # headless rendering — must be set before importing pyplot
import matplotlib.pyplot as plt

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024
WORKSPACES = Path(os.environ.get("WORKSPACE_DIR", "data/workspaces"))
WORKSPACES.mkdir(parents=True, exist_ok=True)
WORKSPACE_MAX_AGE_SECONDS = 2 * 60 * 60  # ephemeral disk: prune old workspaces so it never fills up

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
FORGE_USERNAME = os.environ.get("FORGE_USERNAME", "").strip()  # optional seed account, see seed_admin_account()
FORGE_PASSWORD = os.environ.get("FORGE_PASSWORD", "").strip()
SESSION_TOKENS = {}  # token -> expiry unix timestamp
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
GITHUB_GIST_FILENAME = "forge_users.json"
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
        print(f"[Forge] Warning: could not sync accounts to GitHub Gist: {error}")


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
            json={"description": "Forge account store — do not edit by hand", "public": False,
                  "files": {GITHUB_GIST_FILENAME: {"content": "{}"}}},
            timeout=10,
        )
        response.raise_for_status()
        GITHUB_GIST_ID = response.json()["id"]
        print(f"[Forge] Created a private gist for account storage: {GITHUB_GIST_ID}")
        print(f"[Forge] IMPORTANT: set GITHUB_GIST_ID={GITHUB_GIST_ID} as an env var now — "
              f"without it, the next restart creates a new, empty gist instead of reusing this one.")
    except (requests.RequestException, KeyError, ValueError) as error:
        print(f"[Forge] Warning: could not create a gist for account storage: {error}. Falling back to local-file-only persistence.")


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
print(f"[Forge] {len(load_users())} account(s) loaded"
      f"{' (synced via GitHub Gist ' + GITHUB_GIST_ID + ')' if GITHUB_TOKEN and GITHUB_GIST_ID else f' from {USERS_FILE.resolve()}'}")


def issue_token():
    token = secrets.token_urlsafe(32)
    with _session_lock:
        SESSION_TOKENS[token] = time.time() + SESSION_TTL_SECONDS
    return token


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
            return False
        return True


def require_auth(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not is_valid_token(token_from_request()):
            return jsonify(error="Not authenticated. Please log in."), 401
        return view(*args, **kwargs)
    return wrapped


# Single server-side token for Ollama Cloud (https://ollama.com). Falls back
# to the key provided at setup time so this runs out of the box; override by
# setting OLLAMA_API_KEY in the environment (preferred for anything but a
# quick local test, since env vars don't end up committed to source control).
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "38a2805ec9ba40abb2cfbece6d81b664.fcj4jrAZ0Vz8FVPPU3OF3joq").strip()
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
# There's no official "max" level at the Ollama API — Forge's "Max" instead
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

SYSTEM = '''You are Forge, an expert software and artifact builder. Turn the request into a concise response plus files. Respond with ONLY valid JSON, no prose before or after it, no markdown code fences, using this schema:
{"reply":"short helpful Markdown response","files":[{"path":"safe relative filename.ext","kind":"text|docx|xlsx|pptx|pdf|stl|image|chart|base64","content":"content for artifact"}]}
Create useful, complete files. Use text for code, HTML, CSS, JSON, CSV, SVG (vector images), Markdown and arbitrary plain text.

For docx/pdf, content is Markdown-lite: lines starting "# "/"## "/"### " become headings, lines starting "- " become bullets, **bold** spans are rendered bold, and a `| col | col |` table (with a `|---|---|` separator row under the header) becomes a real formatted table; separate paragraphs with blank lines.
For xlsx, content is JSON rows like [["Header1","Header2"],["value",1]] — the first row is treated as a header and gets bold styling and auto-sized columns automatically.
For pptx, content is JSON slides like [{"title":"...","body":"one bullet per line, separated by \\n"}] — each line in "body" becomes its own bullet point.
For a raster/photographic or artistic image, use kind "image" with a .png/.jpg path. content is either a plain English image-generation prompt, or JSON {"prompt":"...","aspect":"square|portrait|landscape"} for more control over framing — use vivid, specific, detailed prompts.
For an actual DATA chart (bar/line/pie/scatter of real numbers) rather than an artistic picture, use kind "chart" with a .png path. content is JSON: {"type":"bar|line|pie|scatter","title":"...","x_label":"...","y_label":"...","labels":["A","B","C"],"series":[{"name":"Series 1","values":[1,2,3]}]}. Use "chart" whenever the user wants to see numbers plotted — it renders a real, accurate chart from the data instead of an AI-generated approximation of one.

For a 3D model, use kind "stl" with a .stl path. Take real time to think this through — you are the CAD engineer: mentally model the object as an assembly of real, distinct parts and their spatial relationships before writing anything. content is JSON describing a BUILD PROGRAM that Forge parses and executes step by step:
{"plan":"a few sentences: what real-world parts does this object have, roughly what size is each, and how do they connect/align?","ops":[
  {"op":"add","shape":"box|sphere|cylinder|cone|torus|tube|capsule|wedge|pyramid","size":20,"radius":10,"height":20,"tube":4,"segments":16,"position":[x,y,z],"rotation":[rx,ry,rz],"scale":[sx,sy,sz]},
  {"op":"repeat","count":6,"rotate":[0,0,60],"around":[0,0,0]}
]}
Shape params — "box": size [w,d,h] (or one number for a cube); optionally add "bore":{"axis":"x|y|z","radius":R,"segments":N} to punch a clean round hole straight through the box along that axis (e.g. a screw hole, a mounting hole, a cable pass-through, a pivot hole) — this is a real hole through solid material, not a decoration. "sphere"/"cylinder"/"cone": "radius" (+"height" for cylinder/cone). "torus": "radius" (ring) + "tube" (thickness). "tube": a hollow pipe/ring — "radius" (outer) + "inner_radius" + "height". "capsule": a pill shape — "radius" + "height" (straight section length; total length is height + 2*radius). "wedge": a ramp/doorstop/roof — size [w,d,h], sloped down along x. "pyramid": "size" (+optional "height"). "cylinder" with a low "segments" (e.g. 5, 6, 8) becomes a pentagonal/hexagonal/octagonal prism — use this for nuts, bolts, multi-sided posts, etc. instead of a separate prism shape. Leave "segments" unset to let Forge auto-pick a smooth value from the part's size; only set it explicitly for a deliberately low-poly/faceted look.
Every shape is centered on its own local origin, then: scaled by "scale" [sx,sy,sz] (stretch into an ellipsoid, plank, etc.), rotated by "rotation" [rx,ry,rz] degrees (X then Y then Z, e.g. tilt a fin or lay a cylinder on its side), then moved to "position" [x,y,z]. All optional, default no scale/rotation, position [0,0,0].
"repeat" duplicates the shape from the immediately preceding "add" "count"-1 more times: "rotate":[rx,ry,rz] rotates each successive copy further around the "around" pivot (default world origin) — radial patterns (gear teeth, wheel spokes, flower petals, fins around a body). "translate":[dx,dy,dz] offsets each successive copy further along that vector — linear patterns (fence posts, stair treads, table legs, shelf slats, a row of mounting holes). Combine both for a spiral/helix.
"mirror" reflects the immediately preceding "add" across an axis-aligned plane through the origin (or through "offset" along that axis): {"op":"mirror","axis":"x|y|z","offset":0} — use for symmetric designs (matched wings, a hull's two sides, paired brackets) instead of specifying both halves by hand.
There is deliberately no general subtract/union/intersect between arbitrary shapes — Forge tried a general boolean engine and it produced subtly broken (self-intersecting) geometry on realistic shapes during testing, so it was removed rather than shipped unreliable. Work within what's actually available: "bore" for holes through a box, "tube" for hollow cylinders/pipes/rings, overlapping "add"s for anything that reads fine as visually-merged solids (most non-precision parts don't need true CSG to look and print correctly).
Design like an engineer, not an illustrator: before writing ops, work out in "plan" what the real object is made of (its distinct functional parts), roughly how big each one is relative to the others, and exactly how they align and connect (shared axis, shared face, a specific offset) — vague ops with parts floating unconnected or wildly mismatched in scale are the main way these builds go wrong. Build real objects from several parts (roughly 6-20 ops is normal for something detailed) — e.g. a mug = a "tube" body + a "torus" or bent-"capsule" handle positioned at the side; a table = one flat box top + 4 cylinder legs via one add + one repeat with translate; a gear = a short cylinder body + one tooth box at its edge + a repeat rotating around the center; a rocket = a cylinder body + a cone nose + a capsule or sphere tip + fin boxes via one add + a radial repeat; a bracket = a box with a "bore" for its mounting hole. Prefer the shape that is actually hollow/rounded/holed when the real object is (a cup or pipe should be a "tube" not a solid cylinder; a pill or rounded handle should be a "capsule" not a box; a mounting plate should use "bore" not a solid slab). Keep coordinates within roughly -200..200. If one of your ops is invalid Forge will skip just that piece and keep the rest, so don't let one uncertain part stop you from building the others.

Use base64 only for true binary payloads that don't fit the kinds above. If the request only needs a text answer, return an empty files list. Never use absolute paths, traversal, or more than 12 files.'''





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
# (which are easy to get non-manifold or malformed), Forge exposes a small
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


def render_ascii_stl(triangles):
    lines = ["solid forge"]
    for a, b, c in triangles:
        ax, ay, az = a; bx, by, bz = b; cx, cy, cz = c
        ux, uy, uz = bx-ax, by-ay, bz-az
        vx, vy, vz = cx-ax, cy-ay, cz-az
        nx, ny, nz = uy*vz-uz*vy, uz*vx-ux*vz, ux*vy-uy*vx
        length = math.sqrt(nx*nx+ny*ny+nz*nz) or 1.0
        lines += [f" facet normal {nx/length:.6f} {ny/length:.6f} {nz/length:.6f}", "  outer loop"]
        lines += [f"   vertex {p[0]:.4f} {p[1]:.4f} {p[2]:.4f}" for p in (a, b, c)]
        lines += ["  endloop", " endfacet"]
    lines.append("endsolid forge")
    return "\n".join(lines)


def _apply_bold_runs(paragraph, text):
    """Split "**bold**" spans out of a line of text and add them as bold runs."""
    for i, chunk in enumerate(re.split(r"\*\*(.+?)\*\*", text)):
        if not chunk: continue
        run = paragraph.add_run(chunk)
        if i % 2 == 1: run.bold = True


_TABLE_SEPARATOR = re.compile(r"^\|?[\s:|-]+\|?$")


def parse_markdown_blocks(content):
    """Small Markdown-lite block parser shared by the docx and pdf writers.
    Yields ('heading', level, text) | ('bullet', text) | ('table', rows) | ('para', text).
    A table is a "| a | b |" row immediately followed by a "|---|---|"
    separator row, then zero or more further "| ... |" rows."""
    lines = str(content).split("\n")
    i, n = 0, len(lines)
    while i < n:
        stripped = lines[i].strip()
        if not stripped:
            i += 1; continue
        heading_match = re.match(r"^(#{1,3})\s+(.*)", stripped)
        if heading_match:
            yield ("heading", len(heading_match.group(1)), heading_match.group(2)); i += 1; continue
        if stripped.startswith("- "):
            yield ("bullet", stripped[2:]); i += 1; continue
        if stripped.startswith("|") and i + 1 < n and "-" in lines[i + 1] and _TABLE_SEPARATOR.match(lines[i + 1].strip()):
            rows = [[c.strip() for c in stripped.strip("|").split("|")]]
            i += 2  # header row + separator row
            while i < n and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            yield ("table", rows); continue
        yield ("para", stripped); i += 1


CHART_COLORS = ["#2fd68f", "#3f8cf2", "#9c6bf0", "#f2b45c", "#f26b6b", "#39c6c6"]


def render_chart(spec, path):
    """Render a real data chart (matplotlib) — for actual data, not AI art."""
    chart_type = str(spec.get("type", "bar")).lower()
    labels = spec.get("labels") or []
    series = spec.get("series") or [{"name": "Series 1", "values": spec.get("values", [])}]
    if not series or not any(s.get("values") for s in series):
        raise ValueError("Chart spec has no data")

    fig, ax = plt.subplots(figsize=(7.5, 4.6), dpi=150)
    fig.patch.set_alpha(0)

    if chart_type == "pie":
        values = series[0].get("values", [])
        ax.pie(values, labels=labels or None, autopct="%1.0f%%", colors=CHART_COLORS, textprops={"color": "#1a1a1a"})
        ax.axis("equal")
    elif chart_type in ("line", "scatter"):
        x_values = labels if labels else list(range(len(series[0].get("values", []))))
        for i, s in enumerate(series):
            color = CHART_COLORS[i % len(CHART_COLORS)]
            if chart_type == "line":
                ax.plot(x_values, s.get("values", []), marker="o", label=s.get("name", f"Series {i+1}"), color=color)
            else:
                ax.scatter(x_values, s.get("values", []), label=s.get("name", f"Series {i+1}"), color=color)
        if len(series) > 1: ax.legend()
        ax.grid(alpha=0.25)
    else:  # grouped bar (default)
        count = len(labels) if labels else max((len(s.get("values", [])) for s in series), default=0)
        width = 0.8 / max(1, len(series))
        for i, s in enumerate(series):
            xs = [j + i * width for j in range(count)]
            ax.bar(xs, (s.get("values") or [])[:count], width=width, label=s.get("name", f"Series {i+1}"), color=CHART_COLORS[i % len(CHART_COLORS)])
        if len(series) > 1: ax.legend()
        offset = (len(series) - 1) * width / 2
        ax.set_xticks([j + offset for j in range(count)])
        ax.set_xticklabels(labels[:count] if labels else [str(j) for j in range(count)], rotation=20, ha="right")
        ax.grid(axis="y", alpha=0.25)

    if spec.get("title"): ax.set_title(str(spec["title"]))
    if spec.get("x_label"): ax.set_xlabel(str(spec["x_label"]))
    if spec.get("y_label"): ax.set_ylabel(str(spec["y_label"]))
    fig.tight_layout()
    fig.savefig(path, transparent=True)
    plt.close(fig)


def _draw_rich_line(pdf, x, y, text, size, base_font="Helvetica"):
    """Draw one line of text, rendering **bold** spans in a bold font instead
    of leaving the literal asterisks in the output (which reportlab's plain
    drawString has no concept of on its own)."""
    bold_font = f"{base_font}-Bold"
    cursor = x
    for i, chunk in enumerate(re.split(r"\*\*(.+?)\*\*", text)):
        if not chunk: continue
        font = bold_font if i % 2 == 1 else base_font
        pdf.setFont(font, size)
        pdf.drawString(cursor, y, chunk)
        cursor += pdf.stringWidth(chunk, font, size)


def write_artifact(root, item):
    """Writes one artifact to disk. Returns a list of non-fatal warning
    strings (only ever populated for "stl", where a bad build step is
    skipped rather than failing the whole file)."""
    path = root / safe_path(item["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    kind, content = item.get("kind", "text"), item.get("content", "")
    if kind == "text":
        path.write_text(str(content), encoding="utf-8")
    elif kind == "base64":
        path.write_bytes(base64.b64decode(content))
    elif kind == "image":
        # content is either a plain prompt string, or JSON {"prompt":...,"aspect":...}
        # for finer control over framing.
        prompt, aspect = str(content), "square"
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict) and "prompt" in parsed:
                prompt, aspect = str(parsed["prompt"]), str(parsed.get("aspect", "square"))
        except (json.JSONDecodeError, ValueError):
            pass
        width, height = {"portrait": (832, 1216), "landscape": (1216, 832)}.get(aspect, (1024, 1024))
        prompt = prompt.strip()[:800] or "abstract art"
        url = POLLINATIONS_URL.format(prompt=quote(prompt)) + f"?width={width}&height={height}&nologo=true&model=flux"
        response = requests.get(url, timeout=90)
        response.raise_for_status()
        if not response.headers.get("content-type", "").startswith("image/") and len(response.content) < 500:
            raise ValueError("Image generation did not return an image")
        path.write_bytes(response.content)
    elif kind == "chart":
        render_chart(json.loads(content), path)
    elif kind == "docx":
        # Lightweight Markdown: "#"-headings, "- " bullets, **bold** spans,
        # and "| a | b |" tables — instead of dumping everything as identical
        # plain paragraphs.
        doc = Document()
        for block in parse_markdown_blocks(content):
            tag = block[0]
            if tag == "heading":
                doc.add_heading(block[2], level=block[1])
            elif tag == "bullet":
                _apply_bold_runs(doc.add_paragraph(style="List Bullet"), block[1])
            elif tag == "table":
                rows = block[1]
                cols = max(len(r) for r in rows)
                table = doc.add_table(rows=len(rows), cols=cols)
                table.style = "Table Grid"
                for r_idx, row in enumerate(rows):
                    for c_idx in range(cols):
                        cell_text = row[c_idx] if c_idx < len(row) else ""
                        cell = table.cell(r_idx, c_idx)
                        _apply_bold_runs(cell.paragraphs[0], cell_text)
                        if r_idx == 0:
                            for run in cell.paragraphs[0].runs: run.bold = True
            else:
                _apply_bold_runs(doc.add_paragraph(), block[1])
        doc.save(path)
    elif kind == "xlsx":
        wb = Workbook(); sheet = wb.active; sheet.title = "Sheet1"
        rows = json.loads(content)
        for row_index, row in enumerate(rows):
            sheet.append(row if isinstance(row, list) else [row])
            if row_index == 0:
                for cell in sheet[1]: cell.font = Font(bold=True)
        sheet.freeze_panes = "A2"
        widths = {}
        for row in rows:
            for col_index, value in enumerate(row if isinstance(row, list) else [row]):
                widths[col_index] = max(widths.get(col_index, 8), min(len(str(value)) + 2, 40))
        for col_index, width in widths.items():
            sheet.column_dimensions[get_column_letter(col_index + 1)].width = width
        wb.save(path)
    elif kind == "pptx":
        pres = Presentation()
        for slide_data in json.loads(content):
            slide = pres.slides.add_slide(pres.slide_layouts[1])
            slide.shapes.title.text = slide_data.get("title", "Untitled")
            body = slide.placeholders[1].text_frame
            lines = str(slide_data.get("body", "")).split("\n") or [""]
            body.text = lines[0]
            for line in lines[1:]:
                body.add_paragraph().text = line
        pres.save(path)
    elif kind == "pdf":
        pdf = canvas.Canvas(str(path), pagesize=letter)
        page_width, page_height = letter
        margin, y = 54, 750

        def new_page_if_needed(needed=20):
            nonlocal y
            if y < needed:
                pdf.showPage(); y = 750

        for block in parse_markdown_blocks(content):
            tag = block[0]
            if tag == "heading":
                font, size, text = "Helvetica-Bold", {1: 17, 2: 14, 3: 12}[block[1]], block[2]
                pdf.setFont(font, size)
                for line in textwrap.wrap(text, width=95) or [""]:
                    new_page_if_needed(size + 10)
                    pdf.drawString(margin, y, line); y -= (size + 6)
                y -= 4
            elif tag == "bullet":
                wrapped = textwrap.wrap(block[1], width=90) or [""]
                for i, line in enumerate(wrapped):
                    new_page_if_needed()
                    _draw_rich_line(pdf, margin, y, ("• " if i == 0 else "  ") + line, 11); y -= 17
            elif tag == "table":
                rows = block[1]; cols = max(len(r) for r in rows)
                usable = page_width - 2 * margin; col_width = usable / cols
                chars_per_col = max(4, int(col_width / 5.3))
                new_page_if_needed(30)
                pdf.setFont("Helvetica-Bold", 10)
                for c, cell in enumerate(rows[0]):
                    pdf.drawString(margin + c * col_width, y, str(cell).replace("**", "")[:chars_per_col])
                y -= 3; pdf.line(margin, y, margin + usable, y); y -= 15
                for row in rows[1:]:
                    new_page_if_needed()
                    for c in range(cols):
                        cell = row[c] if c < len(row) else ""
                        _draw_rich_line(pdf, margin + c * col_width, y, str(cell)[:chars_per_col], 10)
                    y -= 16
                y -= 6
            else:
                for line in textwrap.wrap(block[1], width=95) or [""]:
                    new_page_if_needed()
                    _draw_rich_line(pdf, margin, y, line, 11); y -= 17
                y -= 4
        pdf.save()
    elif kind == "stl":
        spec = json.loads(content)
        triangles, warnings = run_stl_program(spec)
        path.write_text(render_ascii_stl(triangles), encoding="ascii")
        return warnings
    else:
        raise ValueError(f"Unsupported artifact kind: {kind}")
    return []


def prune_old_workspaces():
    """Ephemeral disk hygiene: delete workspace folders older than the cutoff
    so a long-running process never silently fills its disk with old ZIPs."""
    cutoff = time.time() - WORKSPACE_MAX_AGE_SECONDS
    try:
        for entry in WORKSPACES.iterdir():
            if entry.is_dir() and entry.stat().st_mtime < cutoff:
                for f in sorted(entry.rglob("*"), reverse=True):
                    (f.rmdir() if f.is_dir() else f.unlink())
                entry.rmdir()
    except OSError:
        pass  # best-effort cleanup; never let this break a request


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
    return jsonify(token=issue_token(), expiresIn=SESSION_TTL_SECONDS)


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
    return jsonify(token=issue_token(), expiresIn=SESSION_TTL_SECONDS)


@app.post("/api/logout")
def logout():
    with _session_lock:
        SESSION_TOKENS.pop(token_from_request(), None)
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
        return jsonify(error="Forge isn't configured yet: set the OLLAMA_API_KEY environment variable on the server to an Ollama Cloud API key (ollama.com/settings/keys), then restart."), 500
    # get_json(force=True) raises Flask's own HTML 400 page on a malformed
    # body, which broke the frontend's JSON parsing. silent=True + a manual
    # check keeps every response on this route JSON, even for bad input.
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="Malformed request body."), 400
    prompt = str(data.get("prompt", "")).strip()
    if not prompt: return jsonify(error="Enter a request."), 400
    prune_old_workspaces()

    messages = [{"role": "system", "content": SYSTEM}] + data.get("history", [])[-10:]
    if data.get("web_search"):
        if not TAVILY_API_KEY:
            return jsonify(error="Web search isn't configured yet: set the TAVILY_API_KEY environment variable on the server (get a free key at app.tavily.com), then restart."), 500
        try:
            search_context = tavily_search(prompt)
            messages.append({"role": "system", "content": f"Live web search results for the user's request — use them to inform your answer, and mention where information came from where it's helpful, but don't fabricate beyond what's here:\n{search_context}"})
        except (requests.RequestException, ValueError, KeyError) as error:
            return jsonify(error=f"Web search failed: {error}"), 502
    messages.append({"role": "user", "content": prompt})

    model_id = data.get("model") or DEFAULT_MODEL
    power = str(data.get("power", DEFAULT_POWER)).lower()
    if power not in POWER_LEVELS: power = DEFAULT_POWER
    auto_upgraded_for_3d = looks_like_3d_request(prompt)
    if auto_upgraded_for_3d:
        # 3D geometry quality is directly limited by model capability in a way
        # the other file types mostly aren't, so this overrides whatever the
        # person picked — regardless of their chosen model or power level —
        # to the strongest model available at maximum reasoning effort.
        model_id, power = BEST_MODEL, "max"
    power_config = POWER_LEVELS[power]

    # Ollama's native /api/chat shape differs from OpenAI-style APIs: no
    # response_format, generation options nest under "options". stream:true
    # here (unlike earlier revisions) is what lets Forge show the reply as
    # it's generated instead of one long wait. "think" triggers the model's
    # own extended reasoning before it answers — this is what "take its time
    # and think before building" actually maps to at the API level.
    payload = {"model": model_id, "messages": messages, "stream": True,
               "think": power_config["think"],
               "options": {"temperature": 0.35, "num_predict": power_config["num_predict"]}}

    # Open the upstream connection first — with a couple of retries for
    # transient failures — so a failure here can still return a normal JSON
    # error response. Once we start streaming a 200 body below, the status
    # code can no longer change, so all of this must happen before that.
    # Timeout scales with power level: Max reasoning + the largest token
    # budget genuinely needs more wall-clock room than a quick Low-power reply.
    upstream_timeout = {"low": 150, "medium": 220, "high": 280, "max": 280}[power]
    upstream, last_error = None, None
    for attempt in range(2):
        try:
            candidate = requests.post(OLLAMA_CHAT_URL, headers={"Authorization": f"Bearer {OLLAMA_API_KEY}"}, json=payload, timeout=upstream_timeout, stream=True)
        except requests.RequestException as error:
            last_error = error; time.sleep(0.6); continue
        if candidate.status_code in (502, 503, 504) and attempt == 0:
            candidate.close(); last_error = requests.HTTPError(f"upstream returned {candidate.status_code}"); time.sleep(0.6); continue
        upstream = candidate
        break
    if upstream is None:
        return jsonify(error=f"Ollama Cloud is temporarily unavailable ({last_error}). Please retry."), 502
    if upstream.status_code == 401:
        upstream.close(); return jsonify(error="Ollama Cloud rejected the API key. Check OLLAMA_API_KEY on the server."), 502
    if upstream.status_code == 429:
        upstream.close(); return jsonify(error=f"{model_id} is rate-limited on Ollama Cloud right now. Wait a bit or switch models."), 502
    try:
        upstream.raise_for_status()
    except requests.HTTPError:
        detail = upstream.text[:500]; status = upstream.status_code; upstream.close()
        return jsonify(error=f"Ollama Cloud rejected this request ({status}). {detail}"), 502

    def generate():
        extractor = ReplyStreamExtractor()
        raw_parts, done_reason = [], None
        try:
            if auto_upgraded_for_3d:
                yield json.dumps({"type": "info", "text": f"3D model request detected — auto-using {model_id} at Max power for best build quality."}) + "\n"
            try:
                for line in upstream.iter_lines(decode_unicode=True):
                    if not line: continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    message = chunk.get("message") or {}
                    thinking = message.get("thinking", "")
                    if thinking:
                        yield json.dumps({"type": "thinking", "text": thinking}) + "\n"
                    piece = message.get("content", "")
                    if piece:
                        raw_parts.append(piece)
                        delta = extractor.feed(piece)
                        if delta: yield json.dumps({"type": "delta", "text": delta}) + "\n"
                    if chunk.get("done"):
                        done_reason = chunk.get("done_reason")
                        break
            except requests.RequestException as error:
                yield json.dumps({"type": "error", "error": f"Connection to Ollama Cloud dropped mid-response: {error}"}) + "\n"
                return
            finally:
                upstream.close()

            if done_reason == "length":
                yield json.dumps({"type": "error", "error": "The model ran out of room before finishing its response. Try a shorter request, break it into steps, or switch to a different model."}) + "\n"
                return

            try:
                result = decode_model_result("".join(raw_parts))
            except ValueError as error:
                yield json.dumps({"type": "error", "error": str(error)}) + "\n"
                return

            files = result.get("files", [])[:12]
            workspace_id = uuid.uuid4().hex; root = WORKSPACES / workspace_id; root.mkdir()
            notes = []
            for item in files:
                try:
                    notes += write_artifact(root, item)
                except Exception as error:
                    # Deliberately broad: a single bad file must never throw away an
                    # otherwise-good response (reply text + any other files) — same
                    # per-step fault tolerance principle as the STL build program,
                    # applied to the whole file list.
                    notes.append(f"⚠️ Couldn't create '{item.get('path', '?')}': {error} — skipped, other files were still made.")
            manifest = sorted(
                [{"path": str(p.relative_to(root)).replace("\\", "/"), "bytes": p.stat().st_size,
                  "isImage": p.suffix.lower() in IMAGE_EXTENSIONS}
                 for p in root.rglob("*") if p.is_file()],
                key=lambda f: f["path"],
            )
            reply = result.get("reply", "Done.")
            if notes: reply += "\n\n" + "\n".join(notes)
            yield json.dumps({"type": "done", "reply": reply, "workspace": workspace_id, "files": manifest, "modelUsed": model_id, "powerUsed": power}) + "\n"
        except Exception as error:  # never let the stream just hang or die silently
            yield json.dumps({"type": "error", "error": f"Generation failed: {error}"}) + "\n"

    return Response(stream_with_context(generate()), mimetype="application/x-ndjson")


@app.get("/api/download/<workspace_id>")
@require_auth
def download(workspace_id):
    if not re.fullmatch(r"[a-f0-9]{32}", workspace_id): abort(404)
    root = WORKSPACES / workspace_id
    if not root.is_dir(): abort(404)
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in root.rglob("*"):
            if file.is_file(): archive.write(file, file.relative_to(root))
    payload.seek(0)
    return send_file(payload, as_attachment=True, download_name=f"forge-{workspace_id[:8]}.zip", mimetype="application/zip")


def resolve_workspace_file(workspace_id, filename):
    if not re.fullmatch(r"[a-f0-9]{32}", workspace_id): abort(404)
    root = WORKSPACES / workspace_id
    if not root.is_dir(): abort(404)
    try:
        target = (root / safe_path(filename)).resolve()
    except ValueError:
        abort(404)
    if root.resolve() not in target.parents or not target.is_file(): abort(404)
    return target


@app.get("/api/download/<workspace_id>/<path:filename>")
@require_auth
def download_single(workspace_id, filename):
    target = resolve_workspace_file(workspace_id, filename)
    return send_file(target, as_attachment=True, download_name=target.name)


@app.get("/api/preview/<workspace_id>/<path:filename>")
@require_auth
def preview_single(workspace_id, filename):
    # Same safety checks as the download route, but served inline (not as an
    # attachment) with a guessed mimetype, so <img> tags can render it directly.
    target = resolve_workspace_file(workspace_id, filename)
    mimetype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return send_file(target, as_attachment=False, mimetype=mimetype)


if __name__ == "__main__": app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
