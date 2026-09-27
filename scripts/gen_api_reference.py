"""Generates docs/api-reference.md from the code, so the endpoint reference can't drift.

For every FastAPI endpoint: service, handler (file:line), auth dependency, request/response models,
gateway route and its policies, idempotency, frontend callers (file:line), and what the handler touches
(DB session, caches, other services, events, blobs).

    python scripts/gen_api_reference.py          # rewrites docs/api-reference.md
"""

import ast
import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUTH_DEPS = {"Agent": "agent or admin", "Admin": "admin", "User": "signed in", "CurrentUserDep": "signed in", "OptionalUser": "optional"}

# What a handler body touches → label. Matched against the handler's source text.
TOUCHES = [
    (r"\bsession\b|Session\b", "Postgres (own DB)"),
    (r"listing_cache|search_cache|facts_cache|get_or_load", "two-level cache"),
    (r"\bcache\.(get|set)\(", "Redis cache"),
    (r"store\[|store\.query|store\.client", "Cosmos DB"),
    (r"blobs\.", "Blob Storage"),
    (r"add_event|_stage_state", "outbox → Service Bus"),
    (r"publisher\.publish|publish_enquiry_event", "Service Bus (direct publish)"),
    (r"listing_http|fetch_facts|_listing_summary", "listing service (internal HTTP)"),
    (r"\bai\.(embed|parse_query)", "ai service (internal HTTP)"),
    (r"otp\.", "Redis (OTP) + SMTP"),
    (r"tokens\.|issue_access_token", "signing keys / refresh tokens"),
    (r"store\.set\(f\"jwt", "Redis revocation list"),
    (r"describe\.generate|qa\.answer|nl_search\.parse|get_embedder", "Gemini (via LLM gateway)"),
    (r"ai_log\.", "Cosmos AI request log"),
]


def gateway_routes() -> list[dict]:
    config = json.loads((ROOT / "services/gateway/src/Gateway/appsettings.json").read_text(encoding="utf-8"))
    routes = []
    for route_id, route in config["ReverseProxy"]["Routes"].items():
        path = route["Match"]["Path"]
        regex = re.escape(path).replace(r"\{\*\*rest\}", ".*").replace("/.*", "(/.*)?")
        regex = re.sub(r"\\\{[^}]+\\\}", "[^/]+", regex)
        routes.append({
            "id": route_id, "regex": re.compile(f"^{regex}$"), "methods": set(route["Match"].get("Methods", [])),
            "policies": {k: route[k] for k in ("AuthorizationPolicy", "RateLimiterPolicy", "OutputCachePolicy", "TimeoutPolicy")
                         if k in route},
            "specificity": (path.count("{**") == 0, len(path)),
        })
    return routes


def idempotent_paths() -> list[re.Pattern[str]]:
    found = []
    for main in ROOT.glob("services/*/app/main.py"):
        # the list ends with `])` — a plain `]` can appear inside the regexes themselves ([^/])
        for match in re.finditer(r"IdempotencyMiddleware.*?paths=\[(.*?)\]\)", main.read_text(encoding="utf-8"), re.S):
            found += [re.compile(p) for p in re.findall(r'r"([^"]+)"', match.group(1))]
    return found


def frontend_callers() -> dict[tuple[str, str], list[str]]:
    callers: dict[tuple[str, str], list[str]] = {}
    call = re.compile(r'\b(api|post|patch|postSSE)(?:<[^>()]*>)?\(\s*[`"](/[^`"]+)[`"]|fetch\(\s*[`"]/api/v1(/[^`"]+)[`"]')
    for source in sorted((ROOT / "web/src").rglob("*.ts*")):
        text = source.read_text(encoding="utf-8")
        for m in call.finditer(text):
            fn, path = m.group(1), m.group(2) or m.group(3)
            tail = text[m.end(): m.end() + 200]
            if t := re.search(r'method:\s*[^,}]*\?\s*"(\w+)"\s*:\s*"(\w+)"', tail):
                methods = set(t.groups())
            elif e := re.search(r'method:\s*"(\w+)"', tail[:120]):
                methods = {e.group(1)}
            elif m.group(3):
                methods = {"POST"} if "POST" in tail[:80] else {"GET"}
            else:
                methods = {{"api": "GET", "post": "POST", "patch": "PATCH", "postSSE": "POST"}[fn]}
            norm = re.sub(r"\{[^}]+\}", "{}", re.sub(r"\$\{[^}]+\}", "{}", re.sub(r"(?<=[^/])\$\{.*$", "", path.split("?")[0])))
            line = text[: m.start()].count("\n") + 1
            where = f"`{source.relative_to(ROOT / 'web/src').as_posix()}:{line}`"
            targets = ["/listings/{}/images", "/listings/{}/documents"] if norm == "/listings/{}/{}" else [norm]
            for target in targets:
                for method in (methods if norm != "/listings/{}/{}" else {"POST"}):
                    callers.setdefault((method, "/api/v1" + target), []).append(where)
    return callers


def main() -> None:
    gw, idem, callers = gateway_routes(), idempotent_paths(), frontend_callers()
    rows: dict[str, list[str]] = {}
    for main_py in sorted(ROOT.glob("services/*/app/main.py")):
        service = main_py.parts[-3]
        source = main_py.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
                continue
            for dec in node.decorator_list:
                if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr in
                        {"get", "post", "put", "patch", "delete"} and dec.args and isinstance(dec.args[0], ast.Constant)):
                    continue
                method, path = dec.func.attr.upper(), dec.args[0].value
                annotations = {a.arg: ast.unparse(a.annotation) for a in node.args.args + node.args.kwonlyargs if a.annotation}
                auth = next((AUTH_DEPS[a] for a in annotations.values() if a in AUTH_DEPS), "public")
                if path.startswith(("/internal", "/.well-known")):
                    auth = "network-internal (not routed by the gateway)"
                body_models = [a for n, a in annotations.items() if a[0].isupper() and a not in AUTH_DEPS
                               and a not in {"Session", "Request", "Response"} and not a.startswith(("Annotated", "Literal"))]
                returns = ast.unparse(node.returns) if node.returns else "—"
                handler_src = ast.get_source_segment(source, node) or ""
                touches = sorted({label for pattern, label in TOUCHES if re.search(pattern, handler_src)})
                concrete = re.sub(r"\{[^}]+\}", "x", path)
                if path.startswith("/api/"):
                    matches = [r for r in gw if r["regex"].match(concrete) and (not r["methods"] or method in r["methods"])]
                    route = max(matches, key=lambda r: r["specificity"], default=None)
                    gateway = (f"`{route['id']}`" + "".join(f"<br>{k.removesuffix('Policy').lower()}: `{v}`"
                                                             for k, v in route["policies"].items())) if route else "❌ not routed"
                else:
                    gateway = "— (internal only)" if path.startswith("/internal") else "— (service-to-service)"
                idempotent = "yes" if method == "POST" and any(p.fullmatch(concrete) for p in idem) else ""
                norm = re.sub(r"\{[^}]+\}", "{}", path)
                ui = "<br>".join(callers.get((method, norm), [])) or ("`<img src>`" if path.startswith("/api/v1/media") else "—")
                doc = (ast.get_docstring(node) or "").split("\n")[0]
                rows.setdefault(service, []).append(
                    f"| `{method} {path}` | [{node.name}](../services/{service}/app/main.py#L{node.lineno}){(' — ' + doc) if doc else ''} "
                    f"| {auth} | {', '.join(body_models) or '—'} → `{returns}` | {gateway} | {idempotent} | {', '.join(touches) or '—'} | {ui} |")

    out = [
        "# API reference (generated)",
        "",
        f"> Generated by `python scripts/gen_api_reference.py` on {date.today().isoformat()} from the service code,",
        "> the gateway config and the frontend source. **Don't edit by hand** — rerun the script after API changes.",
        "> How to follow any of these calls through logs and traces: [api-tracing.md](api-tracing.md).",
        "",
        "Columns: **Auth** = FastAPI dependency in the handler (the gateway may also enforce a policy) · "
        "**Body → response** = Pydantic models · **Gateway** = YARP route id and policies · "
        "**Idem.** = `Idempotency-Key` honoured · **Touches** = dependencies seen in the handler · "
        "**Frontend** = where the web app calls it.",
        "",
    ]
    for service, service_rows in rows.items():
        out += [f"## {service}", "", "| Endpoint | Handler | Auth | Body → response | Gateway | Idem. | Touches | Frontend |",
                "|---|---|---|---|---|---|---|---|", *service_rows, ""]
    (ROOT / "docs/api-reference.md").write_text("\n".join(out), encoding="utf-8")
    print(f"docs/api-reference.md: {sum(len(r) for r in rows.values())} endpoints across {len(rows)} services")


if __name__ == "__main__":
    main()
