"""Checks that the backend, the gateway and the frontend agree on the public API.

Reports:
  1. Backend endpoints the frontend never calls (a feature with no UI).
  2. Frontend calls with no backend endpoint (a UI calling nothing).
  3. Backend endpoints the gateway doesn't route (unreachable from the browser).
Exits 1 if anything is reported, so it can run in CI.   Usage:  python scripts/check_api_sync.py
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Endpoints deliberately without a frontend caller, with the reason. Keep this list short and honest.
BACKEND_ONLY = {
    ("GET", "/api/v1/media/{}"): "loaded by <img src>, not fetch",
}

BACKEND_ROUTE = re.compile(r'@app\.(get|post|put|patch|delete)\(\s*"(/api/v1/[^"]+)"')
# api("/x"), post<T>(`/x/${id}`), put/del/download(...), postSSE(...), fetch("/api/v1/x") — first argument only
FRONTEND_CALL = re.compile(r'\b(api|post|patch|put|del|download|postSSE)(?:<[^>()]*>)?\(\s*[`"](/[^`"]+)[`"]|fetch\(\s*[`"]/api/v1(/[^`"]+)[`"]')
METHOD_OPTION = re.compile(r'method:\s*"(GET|POST|PUT|PATCH|DELETE)"')
# api(`/me/favourites/${id}`, { method: saved ? "DELETE" : "PUT" }) — a ternary covers both methods
TERNARY_METHOD = re.compile(r'method:\s*[^,}]*\?\s*"(\w+)"\s*:\s*"(\w+)"')


def normalise(path: str) -> str:
    path = path.split("?")[0]
    path = re.sub(r"(?<=[^/])\$\{.*$", "", path)       # `/admin/users${query ? "?email=" : ""}` → query suffix
    path = re.sub(r"\$\{[^}]+\}", "{}", path)           # `${listingId}`
    path = re.sub(r"\{[^}]+\}", "{}", path)              # {listing_id} / {key:path}
    return path.rstrip("/") or "/"


def backend_endpoints() -> set[tuple[str, str]]:
    found = set()
    for main in ROOT.glob("services/*/app/main.py"):
        for method, path in BACKEND_ROUTE.findall(main.read_text(encoding="utf-8")):
            found.add((method.upper(), normalise(path)))
    return found


def frontend_calls() -> set[tuple[str, str]]:
    found = set()
    for source in (ROOT / "web/src").rglob("*.ts*"):
        text = source.read_text(encoding="utf-8")
        for match in FRONTEND_CALL.finditer(text):
            fn, path, fetch_path = match.group(1), match.group(2), match.group(3)
            path = "/api/v1" + (path or fetch_path)
            tail = text[match.end(): match.end() + 200].split("\n\n")[0]
            if ternary := TERNARY_METHOD.search(tail):
                methods = set(ternary.groups())
            elif explicit := METHOD_OPTION.search(tail[:120]):
                methods = {explicit.group(1)}
            elif fetch_path:
                methods = {"POST"} if "POST" in tail[:80] else {"GET"}
            else:
                methods = {{"api": "GET", "post": "POST", "patch": "PATCH", "put": "PUT", "del": "DELETE", "download": "GET", "postSSE": "POST"}[fn]}
            base = normalise(path)
            # `/listings/${id}/${kind}` stands for several concrete endpoints
            if base == "/api/v1/listings/{}/{}":
                found.update({("POST", "/api/v1/listings/{}/images"), ("POST", "/api/v1/listings/{}/documents")})
                continue
            for method in methods:
                found.add((method, base))
    return found


def gateway_patterns() -> list[tuple[set[str] | None, re.Pattern[str]]]:
    config = json.loads((ROOT / "services/gateway/src/Gateway/appsettings.json").read_text(encoding="utf-8"))
    patterns = []
    for route in config["ReverseProxy"]["Routes"].values():
        path = route["Match"]["Path"]
        regex = re.escape(path).replace(r"\{\*\*rest\}", ".*").replace("/.*", "(/.*)?")
        regex = re.sub(r"\\\{[^}]+\\\}", "[^/]+", regex)
        methods = set(route["Match"].get("Methods", [])) or None
        patterns.append((methods, re.compile(f"^{regex}$")))
    return patterns


def main() -> int:
    backend, frontend, gateway = backend_endpoints(), frontend_calls(), gateway_patterns()
    concrete = lambda p: p.replace("{}", "x")  # noqa: E731

    no_ui = sorted(e for e in backend - frontend if e not in BACKEND_ONLY)
    no_backend = sorted(frontend - backend)
    unrouted = sorted(
        (m, p) for m, p in backend
        if not any((methods is None or m in methods) and rx.match(concrete(p)) for methods, rx in gateway)
    )

    problems = 0
    for title, items in [
        ("Backend endpoints with no frontend caller", no_ui),
        ("Frontend calls with no backend endpoint", no_backend),
        ("Backend endpoints the gateway doesn't route", unrouted),
    ]:
        print(f"\n{title}: {len(items)}")
        for method, path in items:
            print(f"  {method:6} {path}")
        problems += len(items)
    print(f"\nBackend endpoints: {len(backend)} · frontend calls: {len(frontend)} · "
          f"backend-only by design: {len(BACKEND_ONLY)}")
    print("IN SYNC" if problems == 0 else f"OUT OF SYNC ({problems} issue(s))")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
