Status: ready-for-agent
Blocked by: 01

# Background ingest, new upload types and limits, and review UI

## What to build
- `POST /api/reports`:
  - validates the type (PDF/DOCX/PPTX/MD/TXT) and size (about 50 pages or 20 MB), replacing `MAX_CHARS`;
  - stores the Report as `extraction_status="pending"`;
  - records `report_ingested`;
  - schedules extraction via FastAPI `BackgroundTasks` with its own DB session.
- The API exposes the status. Regenerate `frontend/openapi.json`.
- **Frontend:**
  - the upload dialog accepts the new types;
  - the Report shows pending, complete or failed, and polls while pending;
  - Insight Review shows the Chunk's section heading next to the page.

## Acceptance criteria
- [x] One commit for this ticket
- [x] APIs checked via Context7 (FastAPI `BackgroundTasks`)
- [x] Upload returns immediately with `pending`. The background job reaches `complete` or `failed` and records the same events as ticket 01
- [x] Oversized or unsupported uploads are rejected with a clear 4xx
- [x] Frontend tests and build pass, and so does the backend suite

## Notes
- Context7 (FastAPI): a background task must open its own DB session and take ids, since the request's dependency session closes with the response. `extraction.process` does that. `Status` stays `pending` until the job ends; any exception ends it `failed`.
- `report_ingested` is recorded by the request and carries `size_bytes`; `page_count` and `chunk_count` are only known after Docling, so they ride on `insight_extracted`.
- The 50-page limit is a 413 at upload for PDFs (pypdf counts them cheaply). A DOCX/PPTX over the limit is only known after Docling, so it ends `failed` with a clear error.
- Not done (out of scope): sweeping `pending` Reports left by a server restart, and removing vector entries after a partial index failure (ticket 05, re-index).
- Existing tests are the frontend gate (typecheck, lint, build); there is no frontend test runner in the repo.
