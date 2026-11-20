Status: ready-for-agent
Blocked by: 01

# Qdrant adapter behind the vector-store seam, plus contract tests

## What to build
- `uv add langchain-qdrant`. Add `APP_VECTOR_STORE=qdrant` to `get_vector_store`, with `report_filter` returning `models.Filter` for Qdrant. Set cosine distance to match Chroma.
- Write one parametrised contract test suite (add, search with `report_filter`, delete by id, uuid5 ids, flat metadata round-trip). Run it against `memory`, `chroma` (temp dir) and `qdrant` (`QdrantClient(":memory:")`).

## Acceptance criteria
- [x] One commit for this ticket
- [x] APIs checked via Context7
- [x] The same contract passes on all three backends, offline
- [x] No code outside `get_vector_store`/`report_filter` names a backend
