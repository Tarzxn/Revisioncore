# Rian AI Gen 2 Built In — Student Hub

A polished, Apple-minimal student hub with timetable, tasks, courses, exam-board/specification tracking, flashcards, adaptive Learn, Write, Spell, Test and Match study modes practice, focus sessions, school links and a text-only Ollama study assistant.

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
- CSV/TXT flashcard import with duplicate detection
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
- Student data and imported flashcards are validated server-side.
