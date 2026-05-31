from __future__ import annotations

from typing import Any
from urllib.parse import unquote_plus, urlparse

from drones_mir_comunicador.har import load_har


def summarize_flow(path: str) -> list[dict[str, Any]]:
    har = load_har_path(path)
    events: list[dict[str, Any]] = []

    for index, entry in enumerate(har["log"]["entries"]):
        request = entry.get("request", {})
        response = entry.get("response", {})
        url = request.get("url", "")
        parsed = urlparse(url)

        if not _is_relevant_host(parsed.netloc):
            continue

        params = _params(request)
        source = _decode(params.get("javax.faces.source", ""))
        render = _decode(params.get("javax.faces.partial.render", ""))
        execute = _decode(params.get("javax.faces.partial.execute", ""))
        referer = _header(request, "referer")
        content = response.get("content") or {}

        events.append(
            {
                "index": index,
                "method": request.get("method", ""),
                "status": int(response.get("status") or 0),
                "host": parsed.netloc,
                "path": parsed.path,
                "referer_path": urlparse(referer).path if referer else "",
                "source": source,
                "execute": execute,
                "render": render,
                "param_count": len(params),
                "request_body_size": len((request.get("postData") or {}).get("text") or ""),
                "response_size": int(content.get("size") or 0),
                "response_text_saved": bool(content.get("text")),
                "kind": _classify(parsed.netloc, parsed.path, source),
            }
        )

    return events


def load_har_path(path: str) -> dict[str, Any]:
    from pathlib import Path

    return load_har(Path(path))


def render_flow(events: list[dict[str, Any]]) -> str:
    lines = [
        "idx  kind              method status path                                   source -> render",
        "---  ----------------  ------ ------ --------------------------------------  ----------------",
    ]

    for event in events:
        path = _compact(event["path"], 38)
        source = _compact(event["source"] or "-", 28)
        render = _compact(event["render"] or "-", 34)
        body_note = "" if event["response_text_saved"] else " no-response-text"
        lines.append(
            f"{event['index']:>3}  "
            f"{event['kind']:<16}  "
            f"{event['method']:<6} "
            f"{event['status']:>6} "
            f"{path:<38}  "
            f"{source} -> {render}"
            f"{body_note}"
        )

    return "\n".join(lines)


def _params(request: dict[str, Any]) -> dict[str, str]:
    post_data = request.get("postData") or {}
    result: dict[str, str] = {}
    for param in post_data.get("params", []):
        result[_decode(param.get("name", ""))] = param.get("value", "")
    for param in request.get("queryString", []):
        result[_decode(param.get("name", ""))] = param.get("value", "")
    return result


def _header(request: dict[str, Any], name: str) -> str:
    for header in request.get("headers", []):
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def _decode(value: str) -> str:
    return unquote_plus(value)


def _classify(host: str, path: str, source: str) -> str:
    if "servicio.mir.es" in host:
        if path.endswith("/retrieve"):
            return "afirma-poll"
        if path.endswith("/storage"):
            return "afirma-check"
        return "afirma"

    if path.endswith("/altaComunicacion"):
        return "alta"
    if path.endswith("/firmaOk"):
        return "firma-ok"
    if path.endswith("/resultado"):
        return "resultado"
    if source == "formCampos:btnFirmar":
        return "validar-form"
    if source == "formFirma:btnFirmar":
        return "firmar"
    if "listaPilotos" in source or "misPil" in source or "formPilotoDlg" in source:
        return "piloto"
    if "listaUas" in source or "misUas" in source or "formUasDlg" in source:
        return "uas"
    if "zona_act1" in source or source.endswith(":j_idt335"):
        return "zona"
    return "formulario"


def _is_relevant_host(host: str) -> bool:
    return host.endswith("drones.ses.mir.es") or host.endswith("servicio.mir.es")


def _compact(value: str, max_len: int) -> str:
    if len(value) <= max_len:
        return value
    return f"{value[: max_len - 1]}…"

