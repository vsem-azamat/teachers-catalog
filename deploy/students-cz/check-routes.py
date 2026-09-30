"""The router serves the API and sends everything else to the app.

Reads the Caddyfile as Caddy itself understands it (`caddy adapt` output on
stdin) and checks one rule from docs/architecture.md, «The app lives
elsewhere»: `/api/v1/*` and `/healthz` go to this project's API, and every
other path answers 301 to the same path under APP_URL. Checked by behaviour:
walk the routes as Caddy does and see where a sample path of each kind lands,
so no matcher shape or order can hide a misroute.

Usage: caddy adapt ... | python3 check-routes.py <APP_URL as given to caddy>
"""

import fnmatch
import json
import sys

API = "api:8000"
OWN = ["/api/v1/me", "/api/v1/open", "/healthz"]
# The app's screens, a stale asset, and supervisor's API, which this host used
# to proxy: all of them belong to the app's host now.
ELSEWHERE = ["/", "/chats", "/requests/12", "/assets/index-abc.js", "/api/public/catalog"]


def routes(config: dict) -> list[dict]:
    """The server's routes in match order, unwrapped from a host subroute.

    A site address with a host wraps everything in one subroute outside any
    `handle` group; a `handle` block's own subroute is left as it is.
    """
    servers = config["apps"]["http"]["servers"]
    (server,) = servers.values()
    found: list[dict] = []
    for route in server["routes"]:
        wrapped = [
            sub
            for handler in route.get("handle", [])
            if handler.get("handler") == "subroute" and "group" not in route
            for sub in handler["routes"]
        ]
        found.extend(wrapped or [route])
    return found


def matches(route: dict, path: str) -> bool:
    """Whether Caddy would pick this route for `path`. No matcher matches all."""
    if not route.get("match"):
        return True
    patterns = [p for match in route["match"] for p in match.get("path", [])]
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def handlers(route: dict) -> list[dict]:
    """Every handler under a route, however deeply nested in subroutes."""
    out: list[dict] = []
    stack = list(route.get("handle", []))
    while stack:
        handler = stack.pop()
        out.append(handler)
        for sub in handler.get("routes", []):
            stack.extend(sub.get("handle", []))
    return out


def outcome(route: dict) -> str:
    """`proxy <dial>`, `<status> <Location>`, or what else the route does.

    The first terminal handler found, whatever matcher a nested route has: a
    `handle` block here holds one unconditional handler, and one that grows a
    matcher inside is a shape this check would have to learn first.
    """
    for handler in handlers(route):
        if handler.get("handler") == "reverse_proxy":
            dials = [u.get("dial", "?") for u in handler.get("upstreams", [])]
            return "proxy " + ",".join(dials)
        if handler.get("handler") == "static_response":
            location = handler.get("headers", {}).get("Location", ["?"])[0]
            return f"{handler.get('status_code')} {location}"
    return "nothing"


def main() -> int:
    app_url = sys.argv[1]
    terminal = [r for r in routes(json.load(sys.stdin)) if "group" in r]
    expected = {path: f"proxy {API}" for path in OWN}
    # Caddy fills the placeholder per request; the path rides along whole.
    expected |= {path: f"301 {app_url}{{http.request.uri}}" for path in ELSEWHERE}

    failed = False
    for path, want in expected.items():
        chosen = next((r for r in terminal if matches(r, path)), None)
        got = outcome(chosen) if chosen else "nothing"
        if got != want:
            print(f"{path}: {got}, not {want}", file=sys.stderr)
            failed = True
        else:
            print(f"{path} → {got}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
