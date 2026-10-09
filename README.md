# Rian AI Gen 2 Built In — Render ready

Rian is a Flask-based student hub with flashcards, Learn rounds, tasks, courses, and optional server-side AI/search/Teams integrations.

## Persistent login and data (free setup)

This build uses a **private GitHub Gist** to persist account records and student data across Render restarts/redeployments. It does not require Supabase or Cloudflare.

Follow [`docs/GITHUB_GIST_SETUP.md`](docs/GITHUB_GIST_SETUP.md):

1. Create a private Gist with file `rian_ai_gen2_users.json` containing `{}`.
2. Create a GitHub token with only the `gist` scope.
3. Add `GITHUB_TOKEN` and `GITHUB_GIST_ID` to your Render web service's Environment settings.
4. Deploy this project and verify a test account and study set survive a redeploy.

Optional integrations use environment variables for Ollama Cloud, Tavily search, and Microsoft Teams. See `.env.example` for names. Never commit API keys or tokens.

## Run locally

```bash
pip install -r requirements.txt
python -m flask --app app run
```

Without `GITHUB_TOKEN` and `GITHUB_GIST_ID`, local development uses `data/users.json`; that local file is not durable on Render's free filesystem.
