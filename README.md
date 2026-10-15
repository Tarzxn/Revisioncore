# RevisionCore - clean course edition

This is the active Flask application, with the unused legacy files removed. Upload the contents of this folder to the repository connected to the existing Render service. Keep your existing environment variables and account store. Do not replace live user data with a sample database.

## What changed

- Select the exact course, board, exam year and DT option. These selections are saved to the account and filter the notes, question bank, topic flashcards, progress and weekly plan. Course metadata is chosen from the supported catalogue rather than typed freely.
- Original course library: 90 lessons, 180 worked examples, 450 practice questions and 540 topic flashcards. The six selected courses with Resistant Materials show 88 lessons; two additional chapters belong to the alternative DT specialist routes.
- The reader separates Learn, Worked examples and Quick check, with key vocabulary, practical methods, comparison tables and pseudocode where relevant. Each lesson includes two worked examples, five questions, explicit marking points and six flashcards. Topic PDFs include the lesson, worked reasoning, independent questions and a separate answer guide. Six subject books combine the relevant chapters; the DT book uses common content and Resistant Materials.
- Rian AI marking uses the existing OLLAMA_API_KEY, assesses each stored marking criterion, returns specific evidence and improvement advice, and lets the student review the suggested mark before accepting it. The server calculates the score from validated criteria, rejects malformed output and keeps self assessment available.
- The study-set library adds search, folders, duplication, due-card and still-learning filters, and CSV/offline HTML exports. Flashcards, Learn, Write, Spell, Test and Match remain available. Fixed seconds/milliseconds in review scheduling, actual deck shuffling, single-card True/False logic, continuous Match timing and negative-number answer comparison. Write now supports reviewing equivalent wording explicitly.
- White dashboard, pastel course cards, responsive layouts, dark appearance, keyboard controls and personal notes remain integrated with accounts, tasks, timetable and optional Teams.

## Course editions

| Subject | Course | Chapters |
| --- | --- | --- |
| Mathematics | Pearson Edexcel 4MA1 | 15 |
| Biology | Pearson Edexcel 4BI1 | 17 |
| Chemistry | Pearson Edexcel 4CH1 | 16 |
| Physics | Pearson Edexcel 4PH1 | 15 |
| Computer Science | OCR J277 | 13 |
| Design & Technology | Cambridge 0445 | 14 (12 for Resistant Materials) |

Mathematics is the 4MA1 **Higher revision edition**, which includes the relevant core material as well as Higher ideas. A separately filtered Foundation edition is not supplied. DT is the **2027** 0445 syllabus; the 2028 revision changes the options and requires a separate content edition. The default DT specialist choice is Resistant Materials, editable in the course picker.

The DT 2027 structure is Product Design paper 25%, design-and-make Project 50%, and one specialist paper 25%. Follow the centre's project instructions and authenticated-work rules. Rian provides explanations and feedback; it should not invent project research or complete the assessed project for the student.

## Content depth and limits

These are original revision chapters organised around the course areas. They are concise teaching and recall notes, not a certified statement-by-statement course textbook. A full statement-by-statement coverage audit and independent subject-teacher review are still required before being represented as a complete paid-course replacement. The app and PDFs display the review status. Broad chapter presence does not prove full specification coverage.

This build does not claim every feature of Quizlet or Save My Exams, perfect marking, or superiority to their paid products. Public study-set discovery, live classroom games, teacher analytics, licensed textbook solutions, a video library, mobile apps and a complete document-to-AI study pipeline are not included. Personal-set image/audio uploads are not implemented; browser speech reads text. Official past papers remain links to the boards rather than copied paid material. The notes and design are original; this is not a pixel-identical replica of either service.

## Run

```sh
python -m pip install -r requirements.txt
python -m flask --app app run
```

Render build: `pip install -r requirements.txt`

Render start: `gunicorn app:app --workers 1 --worker-class gthread --threads 8 --timeout 340`

The requirements add ReportLab so authenticated PDF routes work after deployment. Notes and questions do not need an AI key. Rian marking needs OLLAMA_API_KEY; optionally set RIAN_MARKING_MODEL, default gpt-oss:20b. The key remains server-side. Ollama Cloud currently does not support enforced structured outputs, so the response is explicitly requested as JSON and strictly checked locally. Invalid or unavailable responses produce an error and do not record a made-up score.

## Account storage

The inherited account adapter still supports its existing Gist integration. Preserve it during the upgrade if existing accounts depend on it. A secret Gist is unlisted rather than an access-controlled private database; production student records should use a private durable store. The existing JSON adapter can use a private Render persistent disk through USERS_FILE=/var/data/users.json with a disk at /var/data, with Gist variables unset after a planned migration. Plan availability/costs vary. Free ephemeral filesystem storage is not durable. Back up and migrate existing records before changing adapters. The app is configured for a single worker; larger deployments need a transactional database.

## Validation and deployment status

Twelve Python tests passed, including real PDF generation, course validation, save-failure preservation and strict AI-result validation. Route tests use request/storage/provider doubles. The real Flask account-isolation test is included but skipped here because Flask and requests could not be installed in this environment.

Chromium tests with simulated API responses passed course onboarding and filtering, note save/retry/reload, topic bookmarks and read tracking, flashcard creation and offline export, Rian marking UI and accepting a suggestion, practice results, planner generation, session completion, folders, set duplication, due filtering, rejection of an incorrect negative-number answer, single-card True/False, Spell workspace, Match completion, Learn workspace, dark appearance, keyboard search and mobile overflow checks. The expanded reader checks include tab navigation, answer reveals, key-term search, practical tables, pseudocode, course overview and lesson navigation. Browser speech sound, full adaptive Learn completion, actual Ollama responses and external Teams/Gist services were not verified.

All 96 PDFs (90 topic downloads and six subject books) were parsed for text; every topic’s core page was rendered in contact sheets, and representative full pages were inspected. PDF downloads are generated on demand in the app, so the 19-file application package does not contain duplicate PDF assets. All 65 earlier topic IDs remain stable to preserve bookmarks, read tracking and practice history. Existing personal notes and cards are not replaced.

The Render website has not been deployed from this chat. Before release, install the requirements and run `python -m unittest discover -s tests -v`, including the real Flask test, verify two-account isolation and a persistent restart, and make one real AI-marking request using the configured provider.

## Reference specifications

Each course links to its official specification in static/curriculum.json, the notes interface and the PDFs. The course organisation was checked against Pearson's 4MA1/4BI1/4CH1/4PH1 specifications, OCR J277 and Cambridge 0445 for 2027. The chapter prose and questions are original.
