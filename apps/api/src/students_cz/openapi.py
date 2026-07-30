"""Print the OpenAPI document to stdout.

The client in `apps/web/src/lib/generated` is generated from this and committed,
so something has to produce the document without a server: the generator's
default is to fetch it from a running API, and CI has no reason to start one to
read a description of itself.

Importing the app is enough — the routes and schemas are declared at import
time, and the lifespan that needs a database never runs.

    uv run python -m students_cz.openapi > openapi.json
"""

import json
import sys

from students_cz.main import app


def main() -> int:
    # Exactly what `/openapi.json` serves, key order included. Sorting here
    # would be tidier and would silently rewrite the committed client the first
    # time anybody ran the check: the generator emits declarations in document
    # order, so the whole file reshuffles for a reason that has nothing to do
    # with the API.
    json.dump(app.openapi(), sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
