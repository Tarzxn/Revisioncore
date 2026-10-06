# Rian AI Gen 2 Built In — Student Hub

A polished, Apple-minimal student hub with timetable, tasks, courses, exam-board/specification tracking, flashcards, round-based adaptive Learn, Write, Spell, Test and Match study modes practice, focus sessions, school links and a text-only Ollama study assistant.

## Run locally
1. `pip install -r requirements.txt`
2. `export OLLAMA_API_KEY=...` (optional: `TAVILY_API_KEY` to enable web search)
3. `flask --app app run`, then choose **Create an account**.

## Deploy on Render
Build with `pip install -r requirements.txt` and start with the Gunicorn command in `render.yaml`. The app uses a secure HttpOnly session cookie and persists session hashes with the account record.

### Keeping accounts logged in across Render wake-ups
For Render's free/ephemeral filesystem, configure `GITHUB_TOKEN` with permission to create/update private gists. The app automatically discovers an existing Rian account gist or creates one and reuses it on later starts. `GITHUB_GIST_ID` can be supplied explicitly, but is no longer required when the token can list gists.

If you use a Render persistent disk instead, the local `data/` store can also survive restarts.

## Student features
- Persistent account-owned flashcard sets with CSV/TXT import and duplicate detection
- Flashcard decks, subjects, study mode and progress
- **Learn** adaptive practice using recognition → active recall, targeted repetition and spaced review
- Course/exam-board/specification/progress tracking
- Timetable, tasks and quick links
- Apple-style light/dark/system-ready interface
- Server-side Ollama AI; responses are text-only and never generate files

## Security
- Passwords use Werkzeug password hashing.
- Session tokens are random, stored in an HttpOnly cookie, and only their SHA-256 hashes are persisted.
- Sessions expire after 30 days by default (`RIAN_SESSION_DAYS`).
- Sign-in/sign-up are rate-limited per IP.
- Student data, flashcard sets, cards and learning progress are validated and persisted server-side; GitHub Gist sync is synchronous so completed study edits are not left waiting in a background task.


### Learn v13
Learn uses deterministic full-set rounds: every active card gets a multiple-choice recognition question and then a typed-recall question for the same card. Cards missed during typed recall move into the next checkpoint round until every selected card has been cleared.


## Persistent Cloudflare authentication

For production, Rian can keep passwords and login sessions in a Cloudflare Worker + Workers KV namespace while Render remains the application server. Set `RIAN_AUTH_URL` and `RIAN_AUTH_SERVICE_KEY` on Render. When enabled, Render never receives the user's plaintext password and never stores the password hash; it receives an opaque HttpOnly session token from the Worker and asks the Worker to verify it. The existing GitHub Gist account store remains the durable home for student data/flashcards as a compatibility layer. Cloudflare Workers KV is designed for authentication tokens and user configuration, and Cloudflare encrypts KV values at rest.

See `cloudflare/README.md` for deployment. Cloudflare Secrets should hold the service key.

## Microsoft Teams assignments

Rian includes an optional **Connect Teams** button in Tasks. It uses Microsoft Graph Education assignments to import published assignments from the signed-in student's school Microsoft 365 account. Microsoft documents `GET /education/me/assignments` and the least-privileged delegated permission `EduAssignments.ReadBasic`; personal Microsoft accounts are not supported for this Education API. Your school's Entra administrator may need to approve the permission.

Configure on Render:
- `MICROSOFT_CLIENT_ID`
- `MICROSOFT_CLIENT_SECRET`
- `MICROSOFT_REDIRECT_URI` = `https://YOUR-RENDER-DOMAIN/api/teams/callback`

In Microsoft Entra ID, register a web application, add the exact redirect URI, and grant delegated `EduAssignments.ReadBasic` plus `openid`, `profile`, and `offline_access`. Rian imports assignment title and due date and avoids duplicate imports. It does not submit or modify Teams assignments.
