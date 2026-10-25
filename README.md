# RevisionCore - illustrated notes edition

The active Flask application for the existing Render service. Replace application source in the connected repository with this folder's contents; preserve existing environment variables and account storage. Do not replace live user data with an example database. This package has not been deployed from the chat.

## What changed

- 172 original lessons, including 46 new focused lessons: eleven in Chemistry and seven in each of the other five subjects. The six selected courses with Resistant Materials show 170 lessons; the other two belong to alternative DT routes.
- Explanatory text increased from 47,202 to 69,255 words, including plain-English introductions. Additions explain methods, structures, mechanisms, observations, limitations and worked reasoning rather than expanding the question bank.
- 117 original vector teaching diagrams are shared by the browser and PDFs; 158 lessons now contain contextual figures. Molecular structures include explicit hydrogen bonds, pentane and hexane, branched isomers, alkenes, the first four alcohols and carboxylic acids, esters, monomers and polymer repeat units. Every complete molecular scene is checked for atom counts and valency.
- Other figures include cells, osmosis, alveoli, circulation, villi, leaf sections, reflexes, nephrons, geometry, probability trees, graphs, circuits, refraction, lenses, half-life, CPU transfers, sorting, networks, manufacturing and joints. Each has a descriptive label and caption. Scenes distinguish schematic drawings from scale diagrams.
- Broader chapters link directly to their focused lessons. Diagrams can be enlarged; narrow screens can pan within the enlarged image. The normal reader fits figures to its width and supports light and dark appearances.
- Existing 126 topic IDs, 738 question records, 864 cards and 288 worked examples remain intact. Each new focused lesson adds one teaching example, with chapter-linked practice and flashcards using the existing bank. It does not invent extra questions to inflate the library.
- Authenticated topic PDFs and six subject books use the same illustrations. The download archive contains 172 topic PDFs and six subject books; books have clickable contents. PDF files are generated on demand by the website and are not duplicated in application source.

## Courses

| Subject | Course | Included lessons |
| --- | --- | --- |
| Mathematics | Pearson Edexcel International GCSE 4MA1 Higher | 28 |
| Biology | Pearson Edexcel International GCSE 4BI1 | 30 |
| Chemistry | Pearson Edexcel International GCSE 4CH1 | 33 |
| Physics | Pearson Edexcel International GCSE 4PH1 | 28 |
| Computer Science | OCR GCSE J277 | 26 |
| Design & Technology | Cambridge IGCSE 0445, 2027 | 27, or 25 for Resistant Materials |

The Mathematics edition includes the relevant core material and Higher content. A separately filtered Foundation edition is not supplied. The 0445 content is for 2027; the course changes from 2028 and needs a separate reviewed edition. The default specialist option is Resistant Materials and can be changed in the course picker.

For 2027 DT, Product Design is 25%, the design-and-make Project 50%, and the specialist paper 25%. Follow the centre's authenticated-work rules. Rian explains and gives feedback; students must supply their own assessed-project research and evidence.

Chemistry uses separate alkanes and alkenes lessons. Hexane naming falls within the six-carbon nomenclature range, while its displayed formula extends the specific five-carbon alkane drawing statement. The notes identify that distinction. Alcohol and acid structures, addition-polymer examples and the ethanediol/ethanedioic-acid polyester example were checked against the published 4CH1 statements.

## Content status

The included lessons are substantially expanded original teaching material. They are not a certified statement-by-statement textbook for every course. Independent subject-teacher review and a complete specification coverage audit remain pending. Diagram placement and a broad chapter list alone do not certify every syllabus requirement. Links to official specifications are retained in every lesson and PDF.

This is an original product, not a copy of Save My Exams or Quizlet. It does not claim every paid feature, perfect AI marking or superiority to those services. No paid notes or image assets have been copied. Public set discovery, live classroom games, licensed textbook solutions, a video library, native mobile apps and personal-set image/audio uploads are not supplied. Browser speech reads text; official papers remain board links.

## Run and deploy

```sh
python -m pip install -r requirements.txt
python -m flask --app app run
```

Render build: `pip install -r requirements.txt`

Render start: `gunicorn app:app --workers 1 --worker-class gthread --threads 8 --timeout 340`

Keep the complete `static/diagrams.json` and `teaching_diagrams.py` in the application. No external diagram library or image-generation service is required. ReportLab uses available system fonts, with its bundled Vera fallback on minimal hosts. Notes and PDF downloads work without an AI key.

Rian marking requires server-side `OLLAMA_API_KEY`; optional `RIAN_MARKING_MODEL` defaults to `gpt-oss:20b`. Provider replies are requested as JSON and strictly checked against the canonical marking criteria. Invalid or unavailable replies return an error and do not create a fabricated score. The key is not exposed to the browser.

## Account storage

Preserve the inherited account adapter and its existing Gist settings if accounts depend on them. A secret Gist is unlisted rather than an access-controlled private database. A private durable store is preferable for production student records.

The JSON adapter can use a private Render persistent disk with `USERS_FILE=/var/data/users.json` and a disk at `/var/data`, after a backed-up, planned migration and with Gist variables unset. Storage availability and pricing depend on the service plan. Ephemeral filesystem storage is not durable. The configuration uses one worker; larger deployments need transactional storage.

## Validation

Fourteen Python tests passed and one real Flask integration test was skipped because Flask/requests are unavailable in the authoring environment. Passed tests cover course validation, workspace preservation, canonical marking, provider-response rejection, real PDF creation, lesson connections, atom counts and bond valences. Route tests use request, storage and provider doubles.

Chromium checks with simulated APIs passed all 46 focused readers, existing six-subject reader flows, linked chapter practice and cards, bookmarks/read tracking, enlargement, narrow-screen panning, light/dark appearance and mobile overflow. All 117 diagram scenes passed checks that text labels stay within their canvas. The existing broad study-flow suite also passed notes save/retry, exams/results, planning, folders, duplication, offline cards, Learn, Spell, Match, backup and course filtering. Real provider responses and external account services were not tested.

All 178 PDFs were parsed for text and empty pages; no very short pages were found. Every topic's first page and every vector scene were rendered for review; representative full-size lesson pages across all six subjects were inspected. The diagrams were revised after visual review to separate labels from lines and clarify processes. The six subject books contain 669 pages in total.

Before live release, install requirements and run `python -m unittest discover -s tests -v` including the real Flask test. Verify two-account isolation, a persistent restart and a real configured AI-marking request. No live account data was modified by the authoring tests.
