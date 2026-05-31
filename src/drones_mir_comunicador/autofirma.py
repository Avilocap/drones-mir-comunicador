from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote_plus, urlparse
from xml.etree import ElementTree

from drones_mir_comunicador.har import load_har


@dataclass(frozen=True)
class BatchResult:
    masked_id: str
    result: str
    description: str


def summarize_autofirma(path: str) -> dict[str, Any]:
    from pathlib import Path

    har = load_har(Path(path))
    entries = har["log"]["entries"]

    choose_entry = _find_entry(entries, "/fire-signature/public/ChooseCertificateOrigin.jsp")
    choose_post = _find_entry(entries, "/fire-signature/public/chooseCertificateOriginService")
    success_post = _find_entry(entries, "/fire-signature/public/miniappletSuccessService")
    polls = [
        (index, entry)
        for index, entry in enumerate(entries)
        if urlparse(entry["request"].get("url", "")).path
        == "/fire-signature/public/afirma/retrieve"
        and entry["request"].get("method") == "POST"
    ]

    return {
        "choose_certificate": _summarize_choose(choose_entry) if choose_entry else None,
        "choose_certificate_post": _summarize_post(choose_post) if choose_post else None,
        "retrieve_poll_count": len(polls),
        "retrieve_polls": [
            {
                "index": index,
                "status": entry["response"].get("status"),
                "response_size": (entry["response"].get("content") or {}).get("size"),
                "params": sorted(_params(entry["request"]).keys()),
            }
            for index, entry in polls
        ],
        "success_post": _summarize_success(success_post) if success_post else None,
    }


def render_autofirma(summary: dict[str, Any]) -> str:
    lines: list[str] = []

    choose = summary["choose_certificate"]
    if choose:
        lines.append("ChooseCertificateOrigin:")
        lines.append(f"  entry: #{choose['index']}")
        lines.append(f"  op: {choose['op']}")
        lines.append(f"  transactionid: {'present' if choose['has_transactionid'] else 'missing'}")
        lines.append(f"  subjectid: {'present' if choose['has_subjectid'] else 'missing'}")
        lines.append(f"  errorurl: {choose['errorurl']}")

    choose_post = summary["choose_certificate_post"]
    if choose_post:
        lines.append("")
        lines.append("chooseCertificateOriginService POST:")
        lines.append(f"  entry: #{choose_post['index']}")
        lines.append(f"  params: {', '.join(choose_post['params'])}")

    lines.append("")
    lines.append(f"Retrieve polls: {summary['retrieve_poll_count']}")
    for poll in summary["retrieve_polls"]:
        lines.append(
            f"  - #{poll['index']} status={poll['status']} "
            f"size={poll['response_size']} params={','.join(poll['params'])}"
        )

    success = summary["success_post"]
    if success:
        lines.append("")
        lines.append("miniappletSuccessService POST:")
        lines.append(f"  entry: #{success['index']}")
        lines.append(f"  status: {success['status']}")
        lines.append(f"  redirect: {success['redirect']}")
        lines.append(f"  params: {', '.join(success['params'])}")
        lines.append("  batch results:")
        for item in success["batch_results"]:
            lines.append(
                f"    - id={item.masked_id} result={item.result} "
                f"description={item.description or '-'}"
            )

    return "\n".join(lines)


def _find_entry(entries: list[dict[str, Any]], path: str) -> tuple[int, dict[str, Any]] | None:
    for index, entry in enumerate(entries):
        if urlparse(entry["request"].get("url", "")).path == path:
            return index, entry
    return None


def _summarize_choose(found: tuple[int, dict[str, Any]]) -> dict[str, Any]:
    index, entry = found
    query = {param["name"]: param.get("value", "") for param in entry["request"].get("queryString", [])}
    return {
        "index": index,
        "op": query.get("op", ""),
        "has_transactionid": bool(query.get("transactionid")),
        "has_subjectid": bool(query.get("subjectid")),
        "errorurl": query.get("errorurl", ""),
    }


def _summarize_post(found: tuple[int, dict[str, Any]]) -> dict[str, Any]:
    index, entry = found
    return {
        "index": index,
        "params": sorted(_params(entry["request"]).keys()),
    }


def _summarize_success(found: tuple[int, dict[str, Any]]) -> dict[str, Any]:
    index, entry = found
    params = _params(entry["request"])
    response = entry.get("response") or {}
    return {
        "index": index,
        "status": response.get("status"),
        "redirect": response.get("redirectURL") or _response_header(response, "location"),
        "params": sorted(params.keys()),
        "batch_results": _decode_batch_results(params.get("afirmabatchresult", "")),
    }


def _decode_batch_results(value: str) -> list[BatchResult]:
    if not value:
        return []

    raw = base64.b64decode(unquote_plus(value))
    root = ElementTree.fromstring(raw)

    results: list[BatchResult] = []
    for node in root.findall("signresult"):
        results.append(
            BatchResult(
                masked_id=_mask_sign_id(node.attrib.get("id", "")),
                result=node.attrib.get("result", ""),
                description=node.attrib.get("description", ""),
            )
        )
    return results


def _params(request: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    post_data = request.get("postData") or {}
    for param in post_data.get("params", []):
        result[unquote_plus(param.get("name", ""))] = param.get("value", "")
    for param in request.get("queryString", []):
        result[unquote_plus(param.get("name", ""))] = param.get("value", "")
    return result


def _response_header(response: dict[str, Any], name: str) -> str:
    for header in response.get("headers", []):
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def _mask_sign_id(value: str) -> str:
    if "-" not in value:
        return "<redacted>"
    return "<subject>-" + value.split("-", 1)[1]

