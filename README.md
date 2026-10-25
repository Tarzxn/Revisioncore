# RevisionCore - clean course edition

This is the active Flask application, with the unused legacy files removed. Upload the contents of this folder to the repository connected to the existing Render service. Keep your existing environment variables and account store. Do not replace live user data with a sample database.

## What changed

- Notes take priority. Every one of the 126 topics has a plain-English introduction. The 90 earlier topics each have two added teaching sections; the 36 denser topics were rewritten with shorter sentences, shorter paragraphs and a further explanatory section. Technical exam terms remain, with clearer explanations around them.
- Explanatory text increased from 33,172 to 47,202 words, including introductions: 42.3% more. The additions explain methods, processes, causes and examples. Flashcards, practice questions and existing worked-example records were kept unchanged.
- The reader separates paragraphs properly, shows the main idea before the detailed notes, and makes reading progress the primary action. Existing topic IDs, course choices, saved work and study modes are retained. The six selected courses with Resistant Materials show 124 lessons; two further lessons belong to the alternative DT specialist routes.
- Notes PDFs contain explanations, vocabulary, practical detail and teaching examples. They no longer repeat the question bank and answer-guide pages. Six subject books have clickable contents; topic notes remain available individually. Questions are still available in the website's practice section.
- Course selection, personal notebooks, Rian AI feedback, study planning and Flashcards/Learn/Write/Spell/Test/Match remain available. This edition does not add more flashcards or questions.

## Course editions

| Subject | Course | Chapters |
| --- | --- | --- |
| Mathematics | Pearson Edexcel 4MA1 | 21 |
| Biology | Pearson Edexcel 4BI1 | 23 |
| Chemistry | Pearson Edexcel 4CH1 | 22 |
| Physics | Pearson Edexcel 4PH1 | 21 |
| Computer Science | OCR J277 | 19 |
| Design & Technology | Cambridge 0445 | 20 (18 for Resistant Materials) |

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

Thirteen Python tests passed, including real PDF generation, course validation, save-failure preservation and strict AI-result validation. Route tests use request/storage/provider doubles. The real Flask account-isolation test is included but skipped here because Flask and requests could not be installed in this environment.

Chromium tests with simulated API responses passed course onboarding and filtering, note save/retry/reload, topic bookmarks and read tracking, flashcard creation and offline export, Rian marking UI and accepting a suggestion, practice results, planner generation, session completion, folders, set duplication, due filtering, rejection of an incorrect negative-number answer, single-card True/False, Spell workspace, Match completion, Learn workspace, dark appearance, keyboard search and mobile overflow checks. The expanded reader checks include tab navigation, answer reveals, key-term search, practical tables, pseudocode, course overview and lesson navigation. A complete three-card Learn session with incorrect multiple-choice and written retries was also checked with simulated progress saves. Missing Learn styles were added for all session states, including mobile, dark appearance, keyboard focus and feedback, and the mastery ring now reflects progress. Completion accuracy includes both multiple-choice and written successes. Browser speech sound, actual Ollama responses and external Teams/Gist services were not verified.

All 132 PDFs (126 topic downloads and six subject books) were parsed for text; every topic’s core page was rendered in contact sheets, and representative full pages were inspected. A text check confirms that the PDFs include the new introductions and exclude the repeated question-bank sections. PDF downloads are generated on demand in the app, so the 19-file application package does not contain duplicate PDF assets. All 126 topic IDs and 738 question IDs remain stable to preserve bookmarks, read tracking and practice history. Existing personal notes and cards are not replaced.


The notes-edition browser checks cover all six course readers, plain introductions, separate paragraphs, the primary reading action, retained practice flows, connected lessons, SQL labelling, mobile overflow and dark appearance. Representative calculations and an executable SQL example were checked independently. Practice results now use bounded unique attempt IDs so storage limits do not truncate different questions to the same record ID.

The Render website has not been deployed from this chat. Before release, install the requirements and run `python -m unittest discover -s tests -v`, including the real Flask test, verify two-account isolation and a persistent restart, and make one real AI-marking request using the configured provider.

## Reference specifications

Each course links to its official specification in static/curriculum.json, the notes interface and the PDFs. The course organisation was checked against Pearson's 4MA1/4BI1/4CH1/4PH1 specifications, OCR J277 and Cambridge 0445 for 2027. The chapter prose and questions are original.
