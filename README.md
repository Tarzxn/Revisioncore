# Rian AI Gen 2 Built In — Student Hub

A Flask student hub: timetable, tasks and deadlines, courses with exam board and progress, school quick links, and a streaming AI study assistant (Ollama Cloud).

## Run locally
1. `pip install -r requirements.txt`
2. `export OLLAMA_API_KEY=...` (optional: `TAVILY_API_KEY` to enable web search)
3. `flask --app app run`, then choose "Create an account".

## Deploy on Render
Build `pip install -r requirements.txt`, start with Gunicorn (see `render.yaml`). Keep `workers = 1`; sessions live in memory. For accounts and student data that survive redeploys on the free plan, set `GITHUB_TOKEN` (gist scope) and, after first boot, `GITHUB_GIST_ID`. Optional seed account: `RIAN_USERNAME` / `RIAN_PASSWORD`.

## Notes
- Tokens are held in `sessionStorage` and sent as bearer headers; no cookies are set.
- Student data is validated server-side; only http(s) links are accepted.
- Sign-in and sign-up are rate-limited per IP.
- Accounts are cached in memory and written atomically; gist sync runs in the background.
