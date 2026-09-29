"""The router sends each path to the backend that owns it.

Reads the Caddyfile as Caddy itself understands it (`caddy adapt` output on
stdin) and checks one rule from docs/architecture.md, «Two backends, one
origin»: `/api/public/*` belongs to supervisor-telegram and is proxied to
SUPERVISOR_ORIGIN over TLS, and `/api/v1/*` stays with this project's API.
Checked by behaviour: walk the routes as Caddy does and see where a sample
path of each lands, so no matcher shape or order can hide a misroute. A
request the router sends to the wrong backend comes back 404, and nothing else
in CI would notice.

Usage: caddy adapt ... | python3 check-routes.py <expected supervisor host>
"""

import fnmatch
import json
import sys


def routes(config: dict) -> list[dict]:
    """The server's routes in match order.

    A site address without a host (`:80`) puts them at the top level; one with
    a host wraps them in a subroute behind a host matcher. Both are read.
    """
    servers = config["apps"]["http"]["servers"]
    (server,) = servers.values()
    found: list[dict] = []
    for route in server["routes"]:
        wrapped = [
            sub
            for handler in route.get("handle", [])
            if handler.get("handler") == "subroute" and not paths(route)
            for sub in handler["routes"]
        ]
        found.extend(wrapped or [route])
    return found


def paths(route: dict) -> list[str]:
    return [p for match in route.get("match", []) for p in match.get("path", [])]


def proxies(route: dict) -> list[dict]:
    """Every reverse_proxy handler under a route, however deeply nested."""
    out: list[dict] = []
    stack = list(route.get("handle", []))
    while stack:
        handler = stack.pop()
        if handler.get("handler") == "reverse_proxy":
            out.append(handler)
        for sub in handler.get("routes", []):
            stack.extend(sub.get("handle", []))
    return out


SAMPLE = "/api/public/catalog"
# And one that must stay here, so widening the supervisor matcher to /api/*
# cannot pass.
OWN = "/api/v1/me"
OWN_DIAL = "api:8000"


def matches(route: dict, path: str) -> bool:
    """Whether Caddy would pick this route for `path`. No matcher matches all."""
    patterns = paths(route)
    if not route.get("match"):
        return True
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def main() -> int:
    expected_host = sys.argv[1]
    # `handle` blocks share a group and exactly one of them runs: the first
    # whose matcher fits. Routes outside a group (encode) pass through.
    terminal = [r for r in routes(json.load(sys.stdin)) if "group" in r]
    chosen = next((r for r in terminal if matches(r, SAMPLE)), None)
    if chosen is None:
        print(f"nothing handles {SAMPLE}", file=sys.stderr)
        return 1

    found = proxies(chosen)
    dials = [u.get("dial") for proxy in found for u in proxy.get("upstreams", [])]
    if dials != [f"{expected_host}:443"]:
        print(
            f"{SAMPLE} goes to {dials or 'no proxy'}, not {expected_host}:443",
            file=sys.stderr,
        )
        return 1
    if not all("tls" in proxy.get("transport", {}) for proxy in found):
        print(f"{SAMPLE} is proxied without TLS", file=sys.stderr)
        return 1

    mine = next((r for r in terminal if matches(r, OWN)), None)
    own_dials = [
        u.get("dial") for proxy in proxies(mine or {}) for u in proxy.get("upstreams", [])
    ]
    if own_dials != [OWN_DIAL]:
        print(f"{OWN} goes to {own_dials or 'nothing'}, not {OWN_DIAL}", file=sys.stderr)
        return 1

    print(f"{SAMPLE} → {expected_host} over TLS, {OWN} → {OWN_DIAL}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
