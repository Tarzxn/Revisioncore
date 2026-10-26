# RevisionCore — original topic guides, edition 8

Application source for the existing Flask service on Render. This package has not been deployed from the chat. Replace source in the connected repository while preserving environment variables and live account storage.

## Notes and course organisation

The primary library now contains 175 topic guides, or 173 for the six selected courses with Resistant Materials. It contains 942 explanatory sections and 67,040 explanatory words, excluding intros, examples and the retained reference library. The earlier 172 lesson IDs remain available; 27 DT guides use those existing IDs. There are 320 distinct records in total, not 320 newly written lessons. Text reused from earlier RevisionCore editions is original RevisionCore material, rather than paid publisher prose.

| Course | Primary guides | Default subject-book pages |
| --- | ---: | ---: |
| Edexcel IGCSE Mathematics A 4MA1 Higher | 58 | 113 |
| Edexcel IGCSE Biology 4BI1 | 21 | 90 |
| Edexcel IGCSE Chemistry 4CH1 | 28 | 110 |
| Edexcel IGCSE Physics 4PH1 | 24 | 74 |
| OCR GCSE Computer Science J277 | 17 | 62 |
| Cambridge IGCSE Design & Technology 0445, 2027 | 27, including 25 for Resistant Materials | 100 |

For the first five courses, the public Save My Exams category indexes were checked on 26 October 2026. The primary guides use those standard curriculum category names, with original explanations from the official course specifications and RevisionCore's existing lessons. A category guide can contain several individual learning sections. This is not a verified one-to-one rebuild of every SME subtopic page, its proprietary prose, illustrations or page counts. Source URLs, guide names and the actual section lists are recorded in `static/notes-index.json`.

No public SME notes index was verified for Cambridge DT. Its organisation is explicitly based on Cambridge's 2027 specification. The default route is Resistant Materials; alternative specialist lessons remain available through course selection. For 2027, the design-and-make Project contributes 50%, Product Design 25%, and the specialist paper 25%. The 2028 course requires its own reviewed edition.

Maths now has separate guides for fractions, percentages, compound change, surds, factorising, completing the square, algebraic fractions, rearranging formulae, proof, functions, graphs, geometry and statistics. Chemistry separates crude oil, alkanes, alkenes, alcohols, carboxylic acids, esters and polymers, together with the physical and inorganic categories. Biology separates selective breeding, genetic engineering and cloning, alongside the physiology, inheritance and ecology material. Physics and Computing use their own topic groups rather than the former combined chapter titles.

The reader offers a nested section index, search across section names, related guides, linked detailed lessons, read tracking, saved topics, Rian explanations and PDF downloads. The More detailed lessons view preserves the original reference material. Saved legacy bookmarks can still be opened. Existing 738 question records and 864 flashcards are unchanged; notes guides link to their relevant existing chapter bank. They do not manufacture new topic-specific questions. Guides without their own worked examples link to the detailed reasoning lessons instead.

## Teaching figures and PDFs

There are 152 original vector scenes, including 36 newly detailed or redrawn plates. They include plant and animal cell cutaways, leaf layers, alveolar exchange, heart chambers and valves, nephrons, the eye, synapses, flowers, DNA, digestion, transport tissues, a fermenter, particle models, bonding, chromatography, distillation, titration, electrolysis, energy profiles, geometry, tangent gradients, refraction, oscilloscope traces, stellar classification, CPU buses, Boolean circuits and an exploded isometric joint. Existing displayed organic structures retain explicit bonds and hydrogen atoms, including pentane, hexane, isomers, alcohols, acids, esters and polymer units.

Figures are placed beside the concept they explain. Browser SVG and ReportLab use the same scene data, including curved paths. Enlargement and narrow-screen panning preserve legibility; figures remain sharp when exported. Structural diagrams indicate when they are schematic and not to scale. They do not claim photographic or microscopic realism.

The separate notes archive contains 320 topic PDFs, six subject books and a short reading guide. Its primary topic guides and older detailed lessons are in separate folders. The six books use the primary index and contain 549 pages with clickable contents. On the website, PDF files are generated on request and are not duplicated in application source.

## Content status

These are original teaching notes, with links to official specifications. Independent subject-teacher review, a statement-by-statement specification audit and one-to-one public subtopic-page matching remain pending. Category alignment alone does not establish complete syllabus coverage. The 549 pages are this edition's actual layout, not an attempt to duplicate another publisher's page count.

This update does not claim every paid Save My Exams or Quizlet feature, perfect AI marking or superiority to those services. Public set discovery, classroom games, licensed textbook solutions, video lessons, native mobile apps and personal-set media uploads are not included. Notes, diagrams and downloads work without an AI key.

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

Sixteen Python tests passed; one real Flask account integration test was skipped because the authoring runtime lacks Flask/requests. Route tests use request, storage and provider doubles and generate real PDFs. They cover course selection, workspace preservation, marking validation, existing question/card integrity, guide links, diagram references, curve formats, molecular atom counts and valences.

Chromium checks with simulated APIs passed all 173 selected-course readers, section rendering, examples, source-lesson links, saved topics, read tracking, desktop and mobile layout, light/dark appearance, enlargement and panning. All 152 scenes passed actual browser font-metric checks for labels remaining inside the canvas. The existing broad study-flow suite also passed personal-note save/retry, exams/results, planning, folders, duplication, offline cards, Learn, Spell, Match, backup and course filtering. External accounts, a real provider response and a Render deployment were not exercised.

All 326 PDFs were parsed for text and empty pages, including 1,655 pages across topic PDFs and subject books; no very short pages were found. All 175 primary-guide first pages were rendered. Detailed scene sheets and representative full-size PDF pages across all six subjects were inspected, and figure placement and scientific labelling were corrected after review.

Before live release, install requirements and run `python -m unittest discover -s tests -v`, including the real Flask test. Verify two-account isolation, durable storage across restart and one real configured AI-marking request. No live account data was modified by authoring tests.
