from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


SENSITIVE_HINTS = (
    "apellido",
    "cert",
    "codigoop",
    "codpostal",
    "documento",
    "email",
    "firma",
    "localidad",
    "matricula",
    "nombre",
    "numserie",
    "pais",
    "provincia",
    "telefono",
    "via",
    "viewstate",
)


@dataclass(frozen=True)
class HarRequest:
    index: int
    method: str
    status: int
    host: str
    path: str
    query_names: tuple[str, ...]
    post_param_names: tuple[str, ...]
    post_body_size: int
    response_mime: str
    started_at: str


def load_har(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if "log" not in data or "entries" not in data["log"]:
        raise ValueError("El archivo no parece un HAR valido: falta log.entries")

    return data


def iter_requests(har: dict[str, Any]) -> list[HarRequest]:
    requests: list[HarRequest] = []

    for index, entry in enumerate(har["log"]["entries"]):
        request = entry.get("request", {})
        response = entry.get("response", {})
        post_data = request.get("postData") or {}
        parsed = urlparse(request.get("url", ""))

        requests.append(
            HarRequest(
                index=index,
                method=request.get("method", ""),
                status=int(response.get("status") or 0),
                host=parsed.netloc,
                path=parsed.path,
                query_names=tuple(q.get("name", "") for q in request.get("queryString", [])),
                post_param_names=tuple(p.get("name", "") for p in post_data.get("params", [])),
                post_body_size=len(post_data.get("text") or ""),
                response_mime=(response.get("content") or {}).get("mimeType", ""),
                started_at=entry.get("startedDateTime", ""),
            )
        )

    return requests


def summarize(path: Path) -> dict[str, Any]:
    har = load_har(path)
    requests = iter_requests(har)

    endpoints: Counter[tuple[str, str, str]] = Counter()
    by_host: Counter[str] = Counter()
    form_fields: dict[str, set[str]] = defaultdict(set)
    signature_flow: list[dict[str, Any]] = []

    for request in requests:
        endpoints[(request.method, request.host, request.path)] += 1
        by_host[request.host] += 1

        if request.host.endswith("drones.ses.mir.es") and request.method == "POST":
            form_fields[request.path].update(request.post_param_names)

        if "firma" in request.path.lower() or "afirma" in request.path.lower():
            signature_flow.append(
                {
                    "index": request.index,
                    "method": request.method,
                    "status": request.status,
                    "host": request.host,
                    "path": request.path,
                    "query_names": list(request.query_names),
                    "post_param_names": list(request.post_param_names),
                }
            )

    return {
        "request_count": len(requests),
        "hosts": [{"host": host, "count": count} for host, count in by_host.most_common()],
        "endpoints": [
            {"method": method, "host": host, "path": path, "count": count}
            for (method, host, path), count in endpoints.most_common()
        ],
        "drones_form_fields": {
            path: sorted(fields) for path, fields in sorted(form_fields.items())
        },
        "signature_flow": signature_flow,
        "sensitive_field_count": _count_sensitive_fields(form_fields),
        "has_initial_html_document": _has_initial_html_document(requests),
    }


def _count_sensitive_fields(form_fields: dict[str, set[str]]) -> int:
    count = 0
    for fields in form_fields.values():
        for field in fields:
            normalized = field.lower()
            if any(hint in normalized for hint in SENSITIVE_HINTS):
                count += 1
    return count


def _has_initial_html_document(requests: list[HarRequest]) -> bool:
    for request in requests:
        if request.host.endswith("drones.ses.mir.es") and request.method == "GET":
            if request.response_mime.startswith("text/html"):
                return True
    return False


def render_text(summary: dict[str, Any]) -> str:
    lines = [
        f"Peticiones: {summary['request_count']}",
        f"HTML inicial capturado: {'si' if summary['has_initial_html_document'] else 'no'}",
        f"Campos potencialmente sensibles detectados: {summary['sensitive_field_count']}",
        "",
        "Hosts:",
    ]

    for host in summary["hosts"]:
        lines.append(f"  - {host['host']}: {host['count']}")

    lines.append("")
    lines.append("Endpoints:")
    for endpoint in summary["endpoints"]:
        lines.append(
            "  - "
            f"{endpoint['method']} https://{endpoint['host']}{endpoint['path']} "
            f"({endpoint['count']})"
        )

    lines.append("")
    lines.append("Flujo de firma detectado:")
    for step in summary["signature_flow"]:
        params = ", ".join(step["post_param_names"] or step["query_names"])
        lines.append(
            "  - "
            f"#{step['index']} {step['method']} https://{step['host']}{step['path']} "
            f"status={step['status']} params=[{params}]"
        )

    lines.append("")
    lines.append("Campos JSF por ruta:")
    for path, fields in summary["drones_form_fields"].items():
        lines.append(f"  - {path}: {len(fields)} campos")

    return "\n".join(lines)

