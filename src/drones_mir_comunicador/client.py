from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx


DEFAULT_BASE_URL = "https://drones.ses.mir.es/drones-web/"
SUBMIT_ENV_FLAG = "DRONES_MIR_ALLOW_SUBMIT"


class SubmitBlocked(RuntimeError):
    """Raised when code tries to submit without explicit operator approval."""


@dataclass(frozen=True)
class MirSessionConfig:
    base_url: str = DEFAULT_BASE_URL
    timeout_seconds: float = 30.0


class MirSession:
    """Small HTTP client skeleton for the JSF flow.

    The project will grow this class only after each request is understood.
    Real POSTs stay blocked unless DRONES_MIR_ALLOW_SUBMIT=1.
    """

    def __init__(self, config: MirSessionConfig | None = None) -> None:
        self.config = config or MirSessionConfig()
        self.client = httpx.Client(
            base_url=self.config.base_url,
            timeout=self.config.timeout_seconds,
            follow_redirects=True,
            headers={
                "User-Agent": "drones-mir-comunicador/0.1 research",
                "Accept-Language": "es-ES,es;q=0.9",
            },
        )

    def close(self) -> None:
        self.client.close()

    def get(self, path: str) -> httpx.Response:
        return self.client.get(path)

    def post_form(self, path: str, data: dict[str, str], *, allow_submit: bool = False) -> httpx.Response:
        if not allow_submit and os.environ.get(SUBMIT_ENV_FLAG) != "1":
            target = urljoin(self.config.base_url, path)
            raise SubmitBlocked(
                f"POST bloqueado hacia {target}. Define {SUBMIT_ENV_FLAG}=1 solo para pruebas controladas."
            )

        return self.client.post(
            path,
            data=data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Faces-Request": "partial/ajax",
                "X-Requested-With": "XMLHttpRequest",
            },
        )

    def __enter__(self) -> "MirSession":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

