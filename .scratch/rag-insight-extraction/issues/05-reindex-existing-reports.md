Status: ready-for-agent
Blocked by: 01

# Re-index script for existing Reports

## What to build
- `scripts/reindex_reports.py`:
  - for each Report without Chunks, chunks its stored page texts with Docling's Markdown path, keeping page numbers;
  - writes `report_chunk` rows and embeds them into the vector store;
  - is idempotent, because uuid5 ids mean a rerun upserts.
- `--rebuild` drops the vector collection and re-embeds it from SQLite. This proves the vector store can be rebuilt.
- It does not touch existing Insights or Audit Events.

## Acceptance criteria
- [x] One commit for this ticket
- [x] Running it twice gives the same Chunks and ids
- [x] `--rebuild` restores retrieval results identical to before
- [x] A test runs on the seeded Reports offline (fake embeddings)
