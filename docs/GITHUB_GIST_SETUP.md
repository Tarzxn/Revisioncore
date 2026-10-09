# Persistent Rian accounts and student data with GitHub Gist (free)

Rian stores user records, password hashes, session-token hashes, flashcards, Learn progress, tasks, courses, and settings in a **private GitHub Gist**. The Gist is the durable store; Render's local filesystem is only a cache and is not relied on for redeploy persistence.

## 1. Create a private Gist

1. Sign in to GitHub.
2. Open https://gist.github.com/.
3. In **Gist description**, enter `Rian AI Gen 2 account store — do not edit by hand`.
4. Name the file exactly `rian_ai_gen2_users.json`.
5. Put `{}` in the file.
6. Click **Create secret gist** (not public gist).
7. Copy the Gist ID from the URL. For `https://gist.github.com/YOURNAME/0123456789abcdef0123456789abcdef`, the ID is the final path segment.

A secret Gist is unlisted, not an access-control mechanism: anyone with its URL may be able to view it. Do not share the URL. The account data includes password hashes and private student data.

## 2. Create a GitHub token

1. Open https://github.com/settings/tokens.
2. Under **Tokens (classic)**, choose **Generate new token (classic)**.
3. Give it a label such as `Rian Render Gist storage` and an expiry you can manage.
4. Select **only** the `gist` scope.
5. Generate it and copy it once. Do not paste it into chat or commit it to a repository.

Use a token with the narrowest permissions possible. If GitHub offers you a fine-grained token that does not support Gist access for your account, use a classic token with only the `gist` scope.

## 3. Add the Render environment variables

In Render Dashboard → your Rian web service → **Environment**, add:

- `GITHUB_TOKEN` = the token you generated
- `GITHUB_GIST_ID` = the ID of the private Gist you created
- `RIAN_SESSION_DAYS` = `30` (optional; this is the default)

Remove obsolete `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_TABLE`, `RIAN_AUTH_URL`, and `RIAN_AUTH_SERVICE_KEY` variables if present. This build does not use Supabase or Cloudflare.

Save changes and deploy the updated Rian ZIP.

## 4. Verify persistence

1. Open Render → **Logs** and confirm startup says GitHub Gist persistence is enabled.
2. Sign up for a test account.
3. Create and save a flashcard set or change a student setting.
4. Open the private Gist on GitHub and verify the JSON changed. Do not edit it manually while the app is running.
5. Redeploy Rian and sign in again. Check the saved study data is still present.

If the Gist API is unavailable, configured writes fail rather than silently claiming the data was saved. Check Render logs and the GitHub token/Gist ID. Never post your token or the Gist contents publicly.

## Limitations

- This is a small, free persistence option, not a full database. Every account-data write rewrites the JSON file, so it is best for a small, low-traffic personal/student app.
- GitHub Gist does not provide transactional database semantics. The app uses a single Gunicorn worker and an in-process lock, but concurrent requests across separate service instances can still race. Do not scale this app to multiple instances with a single Gist store.
- GitHub API rate limits and outages can temporarily prevent writes. Rian should show an error when a save fails; verify the actual save in the Gist during testing.
- A secret Gist is unlisted, not truly private. Protect the Gist URL and token; anyone who obtains the URL may be able to read the stored JSON.
- Passwords are stored as Werkzeug password hashes, and browser sessions use random opaque tokens in HttpOnly cookies; only a SHA-256 hash of each session token is stored in the Gist.
