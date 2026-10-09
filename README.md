# Rian AI Gen 2 Built In

Render-ready Flask student hub with Quizlet-style flashcards/Learn, Microsoft Teams assignment import, server-side Ollama, and durable free-tier account storage using Supabase PostgreSQL.

## Architecture

`Browser → Render Flask → Supabase PostgreSQL`

The browser receives only an opaque, `HttpOnly` session cookie. Passwords are hashed with Werkzeug before storage. Student data, flashcards, Learn progress, tasks and sessions are stored in the same Supabase account row, so they survive Render restarts and redeploys.

There is **no Cloudflare dependency** in this version and no GitHub Gist dependency.

## Supabase setup

1. Create a Supabase project on the free tier.
2. Open **SQL Editor**.
3. Paste the complete contents of `supabase.sql` and run it.
4. In Supabase, open **Project Settings → API**.
5. Copy the project URL and the **service-role key**.
6. Put them into Render as:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

Never put the service-role key into frontend JavaScript or expose it to students.

## Render environment variables

Required:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `OLLAMA_API_KEY`

Optional:

- `TAVILY_API_KEY`
- `MICROSOFT_CLIENT_ID`
- `MICROSOFT_CLIENT_SECRET`
- `MICROSOFT_REDIRECT_URI`
- `RIAN_SESSION_DAYS` (defaults to 30)

Do **not** add the old Cloudflare variables `RIAN_AUTH_URL` or `RIAN_AUTH_SERVICE_KEY`.

## Teams

The existing Microsoft Graph Education integration remains server-side. Configure the Microsoft Entra application and set the three Microsoft environment variables above if Teams assignment importing is wanted.

## Local development

Without Supabase variables, the app can run against `data/users.json` for development. Production should always configure Supabase; if Supabase is configured but unavailable, the app refuses to silently fall back to ephemeral Render storage.

## Deploy

The included `render.yaml` uses:

```text
pip install -r requirements.txt
gunicorn app:app --workers 1 --worker-class gthread --threads 8 --timeout 340
```
