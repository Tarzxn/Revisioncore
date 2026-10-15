# RevisionCore — reference-led study workspace

This is an upgrade of the Flask website supplied in `Revisioncore-main (1).zip`. The dashboard follows the supplied image: a narrow icon sidebar, a white rounded application surface, blue actions, four pastel course cards, a schedule and an assignment table. Screenshots use demonstration data from the browser test, rather than data seeded into real accounts.

## Included

- Existing account login, courses, timetable, tasks, optional Teams integration and AI tutor.
- Existing Flashcards, adaptive Learn, Write, browser-voice Spell, mixed Test and timed Match modes, set editing, favourites, CSV/TXT imports and stored card progress.
- Original starter library: 20 GCSE overview lessons and 40 questions across biology, chemistry, physics, mathematics, English, computing, geography and history. Each lesson has three explanations, an exam tip, practice questions and flashcards.
- Search, subject filters, saved topics, read tracking and personal notes with text/Markdown import and print-to-PDF using the browser.
- Question builder with subject/topic/difficulty/count filters, timed mocks, model answers and explicit self assessment. Saved scores drive targeted questions and progress bars.
- Exam dates and countdowns, manual study sessions, a seven-day planner, completion tracking and study-time totals. Repeated generation respects time already planned for each day.
- CSV set export and standalone HTML flashcards that can be studied offline or shared as a file.
- Study-workspace JSON backup and restore, dark appearance, mobile navigation, keyboard search, focus indicators and reduced-motion support.

## Run and deploy on Render

Keep the repository layout: `app.py`, `study_api.py`, `requirements.txt`, `templates/` and `static/` belong at the repository root.

```sh
python -m pip install -r requirements.txt
python -m flask --app app run
```

For the existing Render service, commit these source changes to its connected repository and deploy that commit. The existing build/start commands remain:

```sh
pip install -r requirements.txt
gunicorn app:app --workers 1 --worker-class gthread --threads 8 --timeout 340
```

No Render account, repository URL or deployment credentials were available during this upgrade; the live service has not been changed.

Student revision data is stored in the existing per-account `student.revision_workspace` record. Existing profile saves do not replace this field. The app retains the supplied Gist adapter for compatibility. A secret Gist is unlisted, not an access-controlled private database; for production student information use private durable storage. A Render persistent disk can hold the existing JSON account store by setting `USERS_FILE=/var/data/users.json` with a disk mounted at `/var/data`, leaving the Gist variables unset. Disk availability and pricing depend on the Render plan. Keep a secure backup and migrate existing users before changing storage. The free ephemeral filesystem does not preserve accounts across redeploys. This storage adapter is intended for a single worker; a larger deployment needs a transactional database.

The AI tutor still needs `OLLAMA_API_KEY`. Web search and Teams require the original optional environment variables. Core notes, questions, self marking, planner and flashcard exports do not require an AI key.

## Coverage and remaining work

This build does **not** claim complete Quizlet / Save My Exams Pro parity. The included curriculum is an original starter library, not a complete exam-board course or a copy of either publisher's paid content. Board labels on user notes/courses are metadata; the question bank is general GCSE practice.

Further work is needed for comprehensive reviewed specification-by-specification content, licensed textbook solutions, original explanatory videos, PDF/document-to-study-material AI pipelines, AI rubric marking, live multiplayer classrooms, public discovery/sharing with moderation, teacher class analytics, native mobile applications, a full offline account experience, password reset and production database migration. Official past papers are linked to their boards; they are not mirrored or marked inside the app.

Research references used for the feature comparison: [Quizlet study tools](https://quizlet.com/features/ai-study-tools), [Quizlet Learn](https://quizlet.com/features/learn), [Save My Exams](https://www.savemyexams.com/), [Target Test](https://www.savemyexams.com/study-tools/target-test/).

## Validation

Five Python validation/content tests passed; Python source compilation and JavaScript syntax checks passed. A real Flask account-isolation integration test is included but was skipped in this environment because Flask was unavailable and the dependency download failed.

Browser workflow tests used Chromium and simulated API responses. They exercised note save/reload, bookmarks, read progress, generated topic flashcards, offline export and flip, exam completion/marking, weekly planning, completed sessions, progress, dark appearance, keyboard search and mobile overflow. These tests do not verify real Gist storage, Render deployment, AI responses or Teams.

The final browser rerun, including an added storage-failure/retry case, could not start because the browser runtime failed to launch. The earlier successful browser run predates the final note-retry, planner-date and mobile-sign-out refinements. The final Python validation suite passed; the final JavaScript syntax check passed. Generated offline HTML was inspected and opened in a browser; the artificial test origin prevented a native download, so its export was tested by capturing the generated Blob.

After installing requirements, run the real integration test before deployment:

```sh
python -m unittest discover -s tests -v
```

Also verify two separate accounts cannot see each other's data, notes survive a server restart, and existing accounts survive a Render redeploy with the chosen durable store.
