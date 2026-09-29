"""The router sends each path to the backend that owns it.

Reads the Caddyfile as Caddy itself understands it (`caddy adapt` output on
stdin) and checks one rule from docs/architecture.md, «Two backends, one
origin»: `/api/public/*` belongs to supervisor-telegram and is proxied to
SUPERVISOR_ORIGIN over TLS, before the catch-all `/api/*` that goes to this
project's API. A request the router sends to the wrong backend comes back 404,
and nothing else in CI would notice.

Usage: caddy adapt ... | python3 check-routes.py <expected supervisor host>
"""

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


def main() -> int:
    expected_host = sys.argv[1]
    order = routes(json.load(sys.stdin))
    public = next((i for i, r in enumerate(order) if "/api/public/*" in paths(r)), None)
    if public is None:
        print("no route for /api/public/*", file=sys.stderr)
        return 1

    catch_all = next((i for i, r in enumerate(order) if "/api/*" in paths(r)), None)
    if catch_all is not None and catch_all < public:
        print("/api/* is matched before /api/public/*", file=sys.stderr)
        return 1

    (proxy,) = proxies(order[public])
    dials = [u.get("dial") for u in proxy.get("upstreams", [])]
    if dials != [f"{expected_host}:443"]:
        print(f"/api/public/* goes to {dials}, not {expected_host}:443", file=sys.stderr)
        return 1
    if "tls" not in proxy.get("transport", {}):
        print("/api/public/* is proxied without TLS", file=sys.stderr)
        return 1

    print(f"/api/public/* → {expected_host} over TLS, ahead of /api/*")
    return 0


if __name__ == "__main__":
    sys.exit(main())
