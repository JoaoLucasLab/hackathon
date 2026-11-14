"""Write the app's OpenAPI schema (the same document `/openapi.json` serves) to a file.

Used by `npm run gen:types`, so type generation needs no running server.
Usage: python backend/scripts/export_openapi.py <out.json>
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402

out = Path(sys.argv[1])
out.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
