from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from drones_mir_comunicador.html_forms import HtmlForm, find_form, parse_forms
from drones_mir_comunicador.p12 import temporary_pem_pair
from drones_mir_comunicador.secrets import (
    find_certificate_path,
    load_env,
    require_certificate_password,
)


PROVIDER_INDEX_URL = (
    "https://provider.ses.mir.es/SP2/IndexPage"
    "?redirectUrl=https://drones.ses.mir.es/drones-web/clave"
    "&returnUrl=https://provider.ses.mir.es/SP2/ReturnPage"
    "&providerName=S2816021F_E00003801"
    "&spApplication=Sede+electronica+"
    "&nodeServiceUrl=https://pasarela.clave.gob.es/Proxy2/ServiceProvider"
    "&eidasloa=http://eidas.europa.eu/LoA/low"
    "&afirmaCheck=false"
    "&gissCheck=false"
    "&aeatCheck=false"
    "&eidasCheck=true"
    "&forceCheck=true"
)
NAVIGATION_HEADERS = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,"
        "image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
    ),
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
}
CHROME_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="drones-login-probe",
        description="Prueba el login SAML hacia drones usando el P12 local. No presenta comunicaciones.",
    )
    parser.add_argument("--env", type=Path, default=Path(".env"), help="Ruta al .env")
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Desactiva verificacion TLS del servidor solo para diagnostico local",
    )
    parser.add_argument(
        "--enter-comunicaciones",
        action="store_true",
        help="Pulsa el boton de entrada a Comunicaciones despues de autenticarse",
    )
    args = parser.parse_args()

    env = load_env(args.env)
    p12_path = find_certificate_path(env, args.env.parent)
    password = require_certificate_password(env)

    with temporary_pem_pair(p12_path, password) as (cert_path, key_path):
        with httpx.Client(
            cert=(str(cert_path), str(key_path)),
            verify=not args.insecure,
            timeout=60,
            follow_redirects=False,
            headers={
                "User-Agent": CHROME_USER_AGENT,
                "Accept-Language": "es-ES,es;q=0.9",
            },
        ) as client:
            session = LoginProbe(client)
            final_response = session.run(enter_comunicaciones=args.enter_comunicaciones)

    print("")
    print(f"Resultado: HTTP {final_response.status_code} {safe_url(final_response.url)}")
    print(f"Content-Type: {final_response.headers.get('content-type', '-')}")


class LoginProbe:
    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def run(self, *, enter_comunicaciones: bool) -> httpx.Response:
        response = self.client.get(PROVIDER_INDEX_URL)
        self._log(response, "provider index")

        response = self._submit_hidden_form(response, "provider -> clave", {"SAMLRequest", "RelayState"})
        response = self._submit_idp_selection(response)
        response = self._submit_action_form(
            response, "clave -> afirma", "AuthenticateCitizen", {"SAMLRequest", "RelayState"}
        )
        response = self._submit_action_form(
            response, "afirma -> clave", "ResponseRedirect", {"SAMLResponse", "RelayState"}
        )
        response = self._submit_action_form(
            response, "clave -> provider", "ReturnPage", {"SAMLResponse", "RelayState"}
        )

        response = self._follow_redirects(response, "drones redirect")

        self._log(response, "drones acceso")

        if enter_comunicaciones:
            response = self._enter_comunicaciones(response)
            if response.is_redirect:
                response = self._follow_redirect(response, "acceso -> comunicaciones")
            self._log(response, "drones comunicaciones")

        return response

    def _follow_redirects(self, response: httpx.Response, label: str, limit: int = 5) -> httpx.Response:
        current = response
        for index in range(limit):
            if not current.is_redirect:
                return current
            current = self._follow_redirect(current, f"{label} {index + 1}")
        return current

    def _submit_idp_selection(self, response: httpx.Response) -> httpx.Response:
        forms = parse_forms(response.text)
        form = self._find_action_form(forms, "ServiceRedirect", {"SAMLRequest", "RelayState"})
        data = dict(form.fields)
        data["SelectedIdP"] = "AFIRMA"
        submitted = self._submit_form(response, form, data)
        self._log(submitted, "clave selected AFIRMA")
        return submitted

    def _submit_hidden_form(
        self, response: httpx.Response, label: str, required_fields: set[str]
    ) -> httpx.Response:
        form = find_form(parse_forms(response.text), required_fields)
        submitted = self._submit_form(response, form, dict(form.fields))
        self._log(submitted, label)
        return submitted

    def _submit_action_form(
        self,
        response: httpx.Response,
        label: str,
        action_fragment: str,
        required_fields: set[str],
    ) -> httpx.Response:
        form = self._find_action_form(parse_forms(response.text), action_fragment, required_fields)
        submitted = self._submit_form(response, form, dict(form.fields))
        self._log(submitted, label)
        return submitted

    def _enter_comunicaciones(self, response: httpx.Response) -> httpx.Response:
        form = find_form(parse_forms(response.text), {"javax.faces.ViewState"})
        data = dict(form.fields)
        data["formInicio"] = "formInicio"
        data["formInicio:btnComunicaciones"] = ""
        submitted = self._submit_form(response, form, data)
        self._log(submitted, "post acceso")
        return submitted

    def _submit_form(
        self, response: httpx.Response, form: HtmlForm, data: dict[str, str]
    ) -> httpx.Response:
        action = form.absolute_action(str(response.url))
        if form.method == "POST":
            return self.client.post(action, data=data, headers={"Referer": str(response.url)})
        return self.client.get(action, params=data, headers={"Referer": str(response.url)})

    def _find_action_form(
        self, forms: list[HtmlForm], action_fragment: str, required_fields: set[str]
    ) -> HtmlForm:
        for form in forms:
            if action_fragment in form.action and required_fields.issubset(form.fields.keys()):
                return form
        return find_form(forms, required_fields)

    def _follow_redirect(self, response: httpx.Response, label: str) -> httpx.Response:
        location = response.headers.get("location")
        if not location:
            raise RuntimeError("Redireccion sin cabecera Location")
        target = urljoin(str(response.url), location)
        followed = self.client.get(target, headers=self._redirect_headers(response.url, target))
        self._log(followed, label)
        return followed

    def _redirect_headers(self, source: httpx.URL | str, target: str) -> dict[str, str]:
        headers = dict(NAVIGATION_HEADERS)
        headers["Referer"] = _drones_login_referer(source, target)
        headers["Sec-Fetch-Site"] = _sec_fetch_site(source, target)
        return headers

    def _log(self, response: httpx.Response, label: str) -> None:
        print(f"{label}: HTTP {response.status_code} {safe_url(response.url)}")


def safe_url(url: httpx.URL | str) -> str:
    parsed = urlparse(str(url))
    suffix = "?..." if parsed.query else ""
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}{suffix}"


def _host(url: httpx.URL | str) -> str:
    return urlparse(str(url)).netloc


def _path(url: httpx.URL | str) -> str:
    return urlparse(str(url)).path


def _is_drones_login_redirect(target: str) -> bool:
    return _host(target) == "drones.ses.mir.es" and _path(target) in {
        "/drones-web/clave",
        "/drones-web/acceso",
    }


def _drones_login_referer(source: httpx.URL | str, target: str) -> str:
    if _is_drones_login_redirect(target):
        return "https://pasarela.clave.gob.es/"
    return str(source)


def _sec_fetch_site(source: httpx.URL | str, target: str) -> str:
    return "same-origin" if _host(source) == _host(target) else "cross-site"


if __name__ == "__main__":
    main()
