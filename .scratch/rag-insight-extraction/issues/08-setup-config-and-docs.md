Status: ready-for-agent
Blocked by: 02, 03

# Setup, config and architecture docs

## What to build
- `.env.example` and the README get every new setting:
  - `APP_VECTOR_STORE`
  - `APP_CHROMA_DIR`
  - `APP_EMBEDDING_MODEL`
  - `APP_RERANK_MODEL`
  - `APP_RETRIEVAL_K`
  - `APP_RERANK_TOP_N`
  - `APP_COHERE_API_KEY`
- The setup step pre-fetches the Docling models (`docling-tools models download`), and the README notes the install size.
- Update `docs/architecture/` (the runtime view for Report ingest, and crosscutting 8.3) for the RAG flow, and update `scripts/walkthrough.py` if it ingests a Report.

## Acceptance criteria
- [ ] One commit for this ticket
- [ ] A fresh clone can follow the README, upload a PDF and see Insights
- [ ] The architecture docs match the code
