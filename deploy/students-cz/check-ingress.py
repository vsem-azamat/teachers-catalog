#!/usr/bin/env python3
"""Assert that the compose stack exposes exactly one loopback port.

Publishing the router on a wildcard address would put the application on the
internet without TLS, going around the shared edge entirely — and it would look
like a working deployment while doing it. Run against the output of
`docker compose config`.

    docker compose config > resolved.yml && ./check-ingress.py resolved.yml
"""

import sys

import yaml


def main(path: str) -> int:
    spec = yaml.safe_load(open(path, encoding="utf-8"))
    services = spec.get("services", {})

    problems: list[str] = []

    router = services.get("caddy")
    if router is None:
        return fail(["no 'caddy' service in the resolved compose file"])

    ports = router.get("ports") or []
    if len(ports) != 1:
        problems.append(f"caddy should publish exactly one port, found {len(ports)}")
    else:
        port = ports[0]
        host_ip = port.get("host_ip") if isinstance(port, dict) else None
        target = port.get("target") if isinstance(port, dict) else None
        if host_ip != "127.0.0.1":
            problems.append(f"caddy must bind 127.0.0.1, binds {host_ip!r}")
        if int(target or 0) != 80:
            problems.append(f"caddy must publish container port 80, publishes {target!r}")

    for name, service in services.items():
        if name != "caddy" and service.get("ports"):
            problems.append(f"{name} must not publish a port: {service['ports']}")

    if problems:
        return fail(problems)

    print("ingress: one loopback port on caddy, nothing else published")
    return 0


def fail(problems: list[str]) -> int:
    for problem in problems:
        print(f"FATAL: {problem}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
