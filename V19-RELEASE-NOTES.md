# Rian AI Gen 2 v19 — Design & workflow polish

## What's new

- Apple-inspired visual refresh: calmer SF-style typography stack, refined spacing, subtle layered surfaces, consistent rounded controls, cleaner study surfaces, and responsive layouts.
- New command palette opened with the Search control or `Ctrl+K` / `⌘K`.
- Command palette supports live filtering, arrow-key navigation, Enter to run, Escape to close, click-outside dismissal, and focus restoration.
- Quick actions for Overview, Timetable, Tasks, Revision, Flashcards, AI study assistant, Settings, creating a task, creating a flashcard, creating a study set, starting a focus session, and refreshing student data.
- Clearer focus-visible styling, reduced-motion support, mobile bottom navigation polish, and touch-friendly controls.
- Existing GitHub Gist persistence and authentication backend left intact. No Supabase or Cloudflare dependency added.
- Existing flashcard modes and 10-card Learn round flow preserved.

## Deploy

Deploy this ZIP using the same Render deployment method and existing environment variables as the working v18 setup. Keep `GITHUB_TOKEN` and `GITHUB_GIST_ID` configured in Render. Do not commit tokens to the project.

## Validation performed

- `python -m py_compile app.py`
- `node --check static/app.js`
- `node --check static/hub.js`
- `node --check static/polish.js`
- No duplicate HTML IDs found.
- CSS braces balanced.
- ZIP integrity check passed.

These checks are static validation; they do not replace live browser testing against your Render deployment and GitHub account.
