"""Upload helpers. Extraction runs in a FastAPI background task, which Starlette's TestClient finishes before it returns,
so `upload` answers with the Report as it stands once extraction is over; `upload_pending` is the raw `POST` response."""

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

FIXTURES = Path(__file__).parent / "fixtures"


def upload_pending(
    c: TestClient, name: str = "house_view_demo.txt", content: bytes | None = None, **params: Any
) -> Any:
    content = (FIXTURES / name).read_bytes() if content is None else content
    return c.post("/api/reports", files={"file": (name, content)}, params=params)


def upload(c: TestClient, name: str = "house_view_demo.txt", content: bytes | None = None, **params: Any) -> Any:
    """The upload response, its body replaced by the Report after the background extraction has finished."""
    r = upload_pending(c, name, content, **params)
    if r.status_code == 201:
        settled = c.get(f"/api/reports/{r.json()['id']}")
        r._content = settled.content
    return r
