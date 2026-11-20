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
- [ ] One commit for this ticket
- [ ] APIs checked via Context7 (FastAPI `BackgroundTasks`)
- [ ] Upload returns immediately with `pending`. The background job reaches `complete` or `failed` and records the same events as ticket 01
- [ ] Oversized or unsupported uploads are rejected with a clear 4xx
- [ ] Frontend tests and build pass, and so does the backend suite
