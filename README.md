# Forge (Gen 2)

Forge is a Flask-based AI build workspace with a ChatGPT-style chat interface: sign in, describe what to create, watch the reply stream in live, then download the generated files as a ZIP. It runs on **Ollama Cloud** (https://ollama.com) for text/code, **Pollinations.ai** for images, and optionally **Tavily** for live web search — all server-authenticated, so nothing but your own Forge login is entered in the browser.

## Look and feel

The UI uses a "liquid glass" style: translucent, blurred panels (sidebar, header, composer, message bubbles, code blocks, file cards, the login card) floating over an animated, colorful blurred backdrop, each with a soft specular highlight along its top edge.

## Chat architecture

- **Real token streaming.** Replies appear live, word by word, as the model generates them — Forge incrementally decodes the `"reply"` field straight out of the model's still-in-progress JSON output (a small custom streaming-JSON-string parser), so you see text immediately instead of waiting for the whole generation (which, for a file-heavy request, can take a while). Verified correct against Python's own JSON decoder across chunk boundaries that split mid-escape-sequence, mid-unicode-escape, and mid-key.
- **Power level** (Low/Medium/High/Max, in the composer) controls how much reasoning effort the model spends before answering, mapped to Ollama's native "think" parameter plus a scaled token budget — the model's reasoning streams live as a collapsible "Thinking…" trace above the reply. 3D-modeling requests are detected automatically and forced to the strongest available model at Max effort regardless of the selected model/power, since build quality there is directly limited by model capability.
- **Stop generating** mid-stream — the send button becomes a Stop button; any text that had already streamed in is kept rather than thrown away.
- **Regenerate** any assistant reply (not just the latest) — drops it and everything after it, then re-asks the same prompt.
- **Copy buttons** on individual code blocks and on whole replies.
- **Rich Markdown rendering** — headings, bulleted/numbered lists, blockquotes, links, bold/italic, and syntax-styled code blocks.
- **Automatic retry** for transient upstream failures (a 502/503/504 or dropped connection from Ollama Cloud gets one quick retry before surfacing an error), and a single bad file in a response never discards the rest of a good reply — each file, and each step of a 3D build program, is attempted independently.

## Authentication

Forge sits behind a login screen, with self-service account creation:

- **Accounts persist**, sessions don't. Usernames and password hashes (via Werkzeug's `generate_password_hash`, never plaintext) are saved to a small JSON file on disk (`USERS_FILE`, default `data/users.json`), and optionally also synced to a private GitHub Gist for free (see below) — either way, people don't have to re-register every time the server restarts. Being logged *in*, and conversation history, are the opposite: session tokens live only in an in-memory dict (wiped on restart) and conversation history lives in the browser's `sessionStorage` — both gone the moment the tab/browser closes or the server restarts.
- **No cookies, ever.** The server never sets one. On login/signup it hands back an opaque bearer token, which the browser holds in `sessionStorage` (not `localStorage`) and sends explicitly (`Authorization: Bearer ...`) on every request. There is no mechanism for a returning visitor to be silently auto-logged-in.
- **Creating the first account.** There's no hardcoded default login. The first time you open Forge with zero accounts on the server, signing in automatically offers "Create one" — fill in a username and an 8+ character password and you're in. You can also seed a standing account via env vars (see below) instead, e.g. for automated deployments.
- **Optional seed account.** Set `FORGE_USERNAME` + `FORGE_PASSWORD` to have Forge create that account automatically on startup (matches how earlier versions of this app worked, before self-signup existed). Being an env var, this one always survives redeploys on any host, disk or not.

### Making self-signup accounts survive redeploys for free

Hosts like Render's free tier don't offer a persistent disk at all, so `data/users.json` alone gets wiped on every redeploy there. Rather than requiring a paid plan, Forge can sync accounts to a **private GitHub Gist** instead — free, and you likely already have a GitHub account, so there's nothing new to sign up for:

1. Create a personal access token at https://github.com/settings/tokens with just the `gist` scope, and set it as `GITHUB_TOKEN`.
2. Leave `GITHUB_GIST_ID` unset for the very first boot — Forge creates a new private gist automatically and prints its ID in the startup logs (`[Forge] Created a private gist for account storage: <id>`).
3. Copy that ID into a `GITHUB_GIST_ID` env var and redeploy. From then on every account (self-signup or seeded) is synced to that same gist, and survives every future redeploy — the disk being ephemeral no longer matters.

This is layered on top of the local file, not a replacement for it: every write still saves locally too, and any GitHub failure (unset token, network hiccup, bad ID) is caught and silently falls back to the local file — a login can never fail *because* Gist sync had a problem. If you'd rather use a real paid persistent disk instead, that still works too: just don't set `GITHUB_TOKEN`/`GITHUB_GIST_ID`, and attach a disk mounted at `data/` in the Render dashboard (or `render.yaml`) on a paid plan.

## What it can build

- Code and text files, `.docx`, `.xlsx`, `.pptx`, `.pdf` — each with real formatting: `.docx`/`.pdf` understand a Markdown-lite subset (`#`/`##`/`###` headings, `- ` bullets, `**bold**`, and `| a | b |` tables with a `|---|---|` separator row render as real formatted tables — grid tables with a bold header row in Word, aligned columns in PDF), `.xlsx` gets a bold auto-width header row with the top row frozen, and `.pptx` splits multi-line bodies into proper bullet points.
- **Images** — raster PNG/JPG via a free, keyless call to Pollinations.ai, with optional aspect-ratio control (`square`/`portrait`/`landscape`), or vector `.svg` written directly as text. Generated images/SVGs get an inline thumbnail gallery in chat.
- **Data charts** — real bar/line/pie/scatter charts rendered from actual numbers via matplotlib (not an AI-generated approximation of a chart). Distinct from "image": use this when the user wants their data plotted accurately.
- **3D models (.stl)** — a real parametric CAD-lite engine. The model is asked to reason like an engineer: write a design "plan" (what parts, roughly what size, how they connect) before an ordered build program ("ops") of primitives — box, sphere, cylinder, cone, torus, a genuinely hollow **tube** (pipe/ring/washer), a **capsule** (pill/rounded-rod shape with true hemispherical caps), a **wedge** (ramp/roof), and pyramid — each with position/rotation/scale. A box can also have a **bore**: a real round hole drilled straight through it along any axis (mounting holes, screw holes, cable pass-throughs) — built with an explicit, hand-verified construction (not a general boolean engine; see below) and confirmed watertight and geometrically hole-correct via ray-casting for every axis. `repeat` creates radial or linear patterns (gear teeth, table legs, fence posts, fins, stair treads, a row of mounting holes); `mirror` reflects a part across an axis-aligned plane for symmetric designs (wings, hull halves, paired brackets) without describing both sides by hand. Segment counts auto-scale with part size for smooth curves. Every op runs independently — a malformed step is skipped with a warning instead of failing the whole model. Every individual primitive (including a bored box) ships tested watertight (manifold — every edge shared by exactly two triangles) with outward-facing normals, and the reply includes the model's overall size (bounding box) and triangle count.

  *A note on what this isn't*: there's deliberately no general boolean subtract/union/intersect between arbitrary shapes. A first attempt at one (a standard BSP-tree mesh-boolean algorithm) was built and then removed after testing — with a watertightness checker and ray-casting, not just eyeballing it — found it produced subtly self-intersecting geometry on realistic (non-trivially-aligned) shapes, which is worse than not having the feature. So a multi-part model is an *assembly* of independently-solid pieces, not one fused manifold — each piece prints/renders fine on its own, and two pieces positioned to touch or overlap (like a bracket's two plates meeting at a joint) will generally look and 3D-print correctly since slicers merge touching/overlapping solids on their own, but the combined file isn't guaranteed to pass a strict single-manifold check exactly at that seam.

  A **Power** selector (Low/Medium/High/Max, next to the composer) controls how much reasoning effort the model spends before answering — mapped to Ollama's native "think" parameter — and 3D-modeling requests are detected automatically and forced to the strongest available model at Max effort regardless of what's selected, since geometry quality is the one output type here where model capability is the main limiting factor. The model's reasoning streams live as a collapsible "Thinking…" trace above the reply.
- **Live web research** — an optional "🔎 Web search" toggle in the composer runs the request through Tavily first and feeds the results to the model as context. Off by default; only enabled if `TAVILY_API_KEY` is set.
- Arbitrary base64 binary payloads for anything else.
- Plain-text answers with no files render as ordinary chat replies.

All generated paths are restricted to a per-request workspace and delivered as a ZIP, with individual files also downloadable (or, for images/SVGs, previewable) on their own.

## Models

Forge deliberately sticks to Ollama's own `gpt-oss` family rather than third-party cloud models (Qwen, DeepSeek, etc.) whose Ollama Cloud offerings churn heavily — DeepSeek's alone has been retired and replaced multiple times (v3.1 → v4-flash → v4-pro) in the time this app has existed. `gpt-oss` has stayed stable:

- **GPT-OSS 20B** (default) — fast, capable, and the best balance of speed vs. quality for interactive use.
- GPT-OSS 120B — larger, slower, stronger reasoning; also what Forge auto-switches to for 3D-modeling requests (see below).

## Run locally

1. Install Python 3.12+.
2. Create a virtual environment and install dependencies: `pip install -r requirements.txt`.
3. Just run it and use "Create account" on first launch — no env vars are required to get a login working. Optionally seed a standing account instead:
   ```
   export FORGE_USERNAME="admin"
   export FORGE_PASSWORD="choose-a-real-password"
   ```
4. Forge ships with an Ollama Cloud API key already set as the default in `app.py`, so text/code/file generation works immediately once you've logged in. To use a different key, set it in the environment instead — it overrides the built-in default:
   ```
   export OLLAMA_API_KEY="<your-ollama-cloud-api-key>"
   ```
   Optionally enable live web search too — no default is baked in for this one, since none was provided:
   ```
   export TAVILY_API_KEY="<your-tavily-api-key>"
   ```
5. Run `flask --app app run` and open the displayed address. Log in with the username/password you set above. Image generation needs no key at all.

## Deploy to Render

Push this directory to a Git repository and create a Render Blueprint from it (or a Python Web Service with the commands in `render.yaml`) — this now works fully on the **free plan**, no paid disk required. Set `OLLAMA_API_KEY` if you want to use a key other than the one built into `app.py`, and optionally `FORGE_USERNAME`/`FORGE_PASSWORD` (seed account) and `GITHUB_TOKEN`/`GITHUB_GIST_ID` (free account persistence across redeploys — see the Authentication section above for setup) — all declared as non-synced secrets in `render.yaml`. `render.yaml` and `gunicorn.conf.py` both set a longer worker timeout (300s) since Ollama Cloud generations — especially file-heavy ones — routinely exceed gunicorn's 30s default, and use threaded (`gthread`) workers so one process can serve several concurrent streaming chats instead of a single request occupying a whole worker.

**On accounts surviving redeploys**: without `GITHUB_TOKEN`/`GITHUB_GIST_ID` configured, self-signup accounts live only in `data/users.json` on Render's ephemeral disk and are lost on every redeploy — only the env-var seed account (`FORGE_USERNAME`/`FORGE_PASSWORD`) is guaranteed to survive on the free plan, since Render never wipes env vars. Set up Gist sync (free, five minutes, see above) to make *every* account — including ones created via self-signup — survive redeploys too. On startup Forge logs how many accounts it loaded, and whether Gist sync is active, so a drop back to 0 accounts after a redeploy is easy to spot. Generated files remain intentionally ephemeral either way — pruned after 2 hours regardless.

## Security and privacy

**The Ollama Cloud API key is currently hardcoded as the default value in `app.py`, at the person's explicit request, so the app runs without extra setup.** This is fine for personal/local use but means anyone with access to this source (e.g. if pushed to a public repo) can read and use the key. Before deploying anywhere shared or public, either remove the hardcoded default and require `OLLAMA_API_KEY` to be set, or rotate the key at https://ollama.com/settings/keys if it's ever exposed. The key is never sent to or stored in the browser — only the server holds it. Passwords are hashed (never stored in plaintext) and every API route requires a valid login session. Prompts and generated content are sent to Ollama Cloud (text), Pollinations.ai (image prompts), and — only when you enable the toggle — Tavily (your search query), so do not enter credentials, private keys, regulated data, or sensitive files unless you've reviewed each provider's retention/privacy terms. Workspaces are stored only on the server's ephemeral local disk, pruned automatically after 2 hours, and reachable only by someone holding both a valid login session and the unguessable 128-bit workspace ID — but they are not encrypted at rest.
