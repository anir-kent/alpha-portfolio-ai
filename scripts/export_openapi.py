"""Write the backend OpenAPI schema to frontend/openapi.json (the API contract)."""
import json
import sys
from pathlib import Path

from app.main import create_app
from app.settings import Settings

out = Path(sys.argv[1] if len(sys.argv) > 1 else "frontend/openapi.json")
app = create_app(Settings(database_url="sqlite://", seed_user_password="schema-export"))
out.write_text(json.dumps(app.openapi(), indent=2) + "\n")
print(f"wrote {out}")
