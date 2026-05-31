from __future__ import annotations

import argparse
import base64
import html
import json
import re
import secrets
import string
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote_plus, urljoin, urlparse
from xml.etree import ElementTree

import httpx

from drones_mir_comunicador.headless_signer import sign_batch_headless
from drones_mir_comunicador.html_forms import parse_forms
from drones_mir_comunicador.login_probe_cli import CHROME_USER_AGENT, LoginProbe, safe_url
from drones_mir_comunicador.p12 import temporary_pem_pair
from drones_mir_comunicador.secrets import (
    find_certificate_path,
    load_env,
    require_certificate_password,
)


AJAX_HEADERS = {
    "Faces-Request": "partial/ajax",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/xml, text/xml, */*; q=0.01",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}
NAV_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
ANDALUCIA_CODE = "-860430510"
SEVILLA_NOTIFICATION_PROVINCE = "1878877445"
SEVILLA_NOTIFICATION_CITY = "Sevilla"


@dataclass(frozen=True)
class CommunicationDraft:
    date: str
    place: str
    height_m: int
    ccaa_code: str
    polygon: dict[str, object]


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="drones-communication",
        description="Clona una comunicacion UAS, cambia los datos de actividad y valida el formulario.",
    )
    parser.add_argument("--env", type=Path, default=Path(".env"), help="Ruta al .env")
    parser.add_argument("--insecure", action="store_true", help="Desactiva verificacion TLS")
    parser.add_argument("--clone-row", type=int, default=0, help="Fila de la comunicacion a clonar")
    parser.add_argument("--date", required=True, help="Fecha en formato dd/mm/yyyy")
    parser.add_argument("--place", required=True, help="Lugar de proteccion/recuperacion")
    parser.add_argument("--height", type=int, required=True, help="Altura en metros")
    parser.add_argument(
        "--ccaa-code",
        default=ANDALUCIA_CODE,
        help="Codigo interno de la comunidad autonoma afectada",
    )
    parser.add_argument(
        "--polygon",
        type=Path,
        help="GeoJSON FeatureCollection del poligono. Si se omite, usa Charco de la Pava.",
    )
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=Path("artifacts"),
        help="Carpeta para guardar respuestas de diagnostico",
    )
    parser.add_argument(
        "--start-signature",
        action="store_true",
        help="Tras validar, inicia la transaccion de firma y guarda la respuesta",
    )
    parser.add_argument(
        "--sign",
        action="store_true",
        help="Inicia AutoFirma, espera el resultado y presenta la comunicacion",
    )
    parser.add_argument(
        "--sign-mode",
        choices=("autofirma", "headless"),
        default="autofirma",
        help="Motor de firma cuando se usa --sign",
    )
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=300,
        help="Tiempo maximo de espera para AutoFirma",
    )
    args = parser.parse_args()

    polygon = load_polygon(args.polygon) if args.polygon else charco_de_la_pava_polygon()
    draft = CommunicationDraft(
        date=args.date,
        place=args.place,
        height_m=args.height,
        ccaa_code=args.ccaa_code,
        polygon=polygon,
    )

    env = load_env(args.env)
    p12_path = find_certificate_path(env, args.env.parent)
    password = require_certificate_password(env)
    args.artifacts_dir.mkdir(exist_ok=True)

    with temporary_pem_pair(p12_path, password) as (cert_path, key_path):
        with httpx.Client(
            cert=(str(cert_path), str(key_path)),
            verify=not args.insecure,
            timeout=httpx.Timeout(180, connect=60),
            follow_redirects=False,
            headers={
                "User-Agent": CHROME_USER_AGENT,
                "Accept-Language": "es-ES,es;q=0.9",
            },
        ) as client:
            runner = CommunicationRunner(client, args.artifacts_dir)
            prepared = runner.clone_update_and_validate(draft, clone_row=args.clone_row)
            if args.sign:
                signature_response = runner.start_signature(prepared)
                if args.sign_mode == "headless":
                    final_response = runner.complete_headless_signature(
                        prepared,
                        signature_response,
                        p12_path=p12_path,
                        password=password,
                        insecure=args.insecure,
                    )
                else:
                    final_response = runner.complete_autofirma_signature(
                        prepared,
                        signature_response,
                        wait_seconds=args.wait_seconds,
                    )
                print(f"Presentacion: HTTP {final_response.status_code} {safe_url(final_response.url)}")
            elif args.start_signature:
                signature_response = runner.start_signature(prepared)
                signature_redirect = partial_redirect(signature_response.text)
                print(
                    "Firma inicio: "
                    f"HTTP {signature_response.status_code} "
                    f"redirect={signature_redirect or '-'}"
                )

    print("")
    print(f"Formulario: {safe_url(prepared.form_url)}")
    print(
        "Validacion: "
        f"{'OK' if not partial_validation_failed(prepared.validation_response.text) else 'FALLIDA'}"
    )


class CommunicationRunner:
    def __init__(self, client: httpx.Client, artifacts_dir: Path) -> None:
        self.client = client
        self.artifacts_dir = artifacts_dir

    def clone_update_and_validate(
        self, draft: CommunicationDraft, *, clone_row: int
    ) -> "PreparedCommunication":
        listing = LoginProbe(self.client).run(enter_comunicaciones=True)
        form_page = self._clone_row(listing, clone_row)
        self.artifacts_dir.joinpath("communication_form_initial.html").write_text(
            form_page.text, encoding="utf-8"
        )

        view_state = view_state_from_html(form_page.text)
        data = form_data(form_page.text, "formCampos")
        data = apply_draft(data, draft, view_state)
        url = str(form_page.url)
        referer = str(form_page.url)
        data = self._complete_notification_location(url, referer, data)

        steps = [
            AjaxStep(
                source="formCampos:pestanas:fecha_act1",
                execute="formCampos:pestanas:fecha_act1",
                render=(
                    "formCampos:pestanas:fecha_act1 "
                    "formCampos:pestanas:horaInicio_act1 "
                    "formCampos:pestanas:minutosInicio_act1 "
                    "formCampos:pestanas:horaFin_act1 "
                    "formCampos:pestanas:minutosFin_act1"
                ),
                event="dateSelect",
                ignore_auto_update=True,
            ),
            AjaxStep(
                source="formCampos:pestanas:lugarProteccion_act1",
                execute="formCampos:pestanas:lugarProteccion_act1",
                render="formCampos:pestanas:colLugPro_act1",
                event="change",
            ),
            AjaxStep(
                source="formCampos:pestanas:lugarRecuperacionRem_act1",
                execute="formCampos:pestanas:lugarRecuperacionRem_act1",
                render="formCampos:pestanas:colLugRec_act1",
                event="change",
            ),
            AjaxStep(
                source="formCampos:pestanas:alturaRem_act1",
                execute="formCampos:pestanas:alturaRem_act1",
                render="formCampos:pestanas:colAltura_act1",
                event="change",
            ),
            AjaxStep(
                source="formCampos:pestanas:ccAas_act1",
                execute="formCampos:pestanas:ccAas_act1",
                render="formCampos:pestanas:colCcAa_act1",
                event="change",
            ),
            AjaxStep(
                source="formCampos:pestanas:j_idt335",
                execute="formCampos:pestanas:zona_act1",
                ignore_auto_update=True,
            ),
        ]

        for step in steps:
            response = self._post_ajax(url, referer, apply_draft(data, draft), step)
            self._save_response(f"ajax_{safe_filename(step.source)}.xml", response)
            new_view_state = view_state_from_partial(response.text)
            if new_view_state:
                data["javax.faces.ViewState"] = new_view_state

        response = self._validate(url, referer, apply_draft(data, draft))
        self._save_response("communication_validate.xml", response)
        view_state = view_state_from_partial(response.text) or data["javax.faces.ViewState"]
        return PreparedCommunication(
            form_url=url,
            referer=referer,
            view_state=view_state,
            validation_response=response,
        )

    def start_signature(self, prepared: "PreparedCommunication") -> httpx.Response:
        if partial_validation_failed(prepared.validation_response.text):
            raise RuntimeError("No inicio firma: la validacion del formulario ha fallado")
        payload = {
            "javax.faces.partial.ajax": "true",
            "javax.faces.source": "formFirma:btnFirmar",
            "javax.faces.partial.execute": "@all",
            "javax.faces.partial.render": "mensajes",
            "formFirma": "formFirma",
            "formFirma:btnFirmar": "formFirma:btnFirmar",
            "javax.faces.ViewState": prepared.view_state,
        }
        response = self.client.post(
            prepared.form_url,
            data=payload,
            headers={**AJAX_HEADERS, "Referer": prepared.referer},
        )
        self._save_response("signature_start.xml", response)
        return response

    def complete_autofirma_signature(
        self,
        prepared: "PreparedCommunication",
        signature_response: httpx.Response,
        *,
        wait_seconds: int,
    ) -> httpx.Response:
        session = self._open_signature_session(prepared, signature_response)
        result_b64 = run_autofirma_and_wait(
            self.client,
            session.request,
            wait_seconds=wait_seconds,
            artifacts_dir=self.artifacts_dir,
        )
        return self._submit_signature_result(session, result_b64)

    def complete_headless_signature(
        self,
        prepared: "PreparedCommunication",
        signature_response: httpx.Response,
        *,
        p12_path: Path,
        password: str,
        insecure: bool,
    ) -> httpx.Response:
        session = self._open_signature_session(prepared, signature_response)
        result_b64 = sign_batch_headless(
            session.request,
            p12_path=p12_path,
            password=password,
            insecure=insecure,
        )
        return self._submit_signature_result(session, result_b64)

    def _open_signature_session(
        self,
        prepared: "PreparedCommunication",
        signature_response: httpx.Response,
    ) -> "SignatureSession":
        signature_redirect = partial_redirect(signature_response.text)
        if not signature_redirect:
            raise RuntimeError("La sede no devolvio redireccion de firma")

        choose_response = self.client.get(
            signature_redirect,
            headers={**NAV_HEADERS, "Referer": prepared.form_url},
        )
        self._save_response("choose_certificate.html", choose_response)

        mini_response = self._choose_local_certificate(signature_redirect)
        self._save_response("mini_applet.html", mini_response)

        request = autofirma_request_from_html(mini_response.text)
        form = signature_success_form(mini_response.text)
        success_url = urljoin(str(mini_response.url), form["__action__"])
        return SignatureSession(
            mini_url=str(mini_response.url),
            request=request,
            success_url=success_url,
            success_form=form,
        )

    def _submit_signature_result(
        self,
        session: "SignatureSession",
        result_b64: str,
    ) -> httpx.Response:
        form = dict(session.success_form)
        form["afirmabatchresult"] = result_b64
        form["errortype"] = ""
        form["errormsg"] = ""
        form["cert"] = ""
        form.pop("__action__", None)
        success_response = self.client.post(
            session.success_url,
            data=form,
            headers={
                "Referer": session.mini_url,
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": NAV_HEADERS["Accept"],
            },
        )
        self._save_response("signature_success_response.html", success_response)

        if success_response.is_redirect:
            target = urljoin(str(success_response.url), success_response.headers["location"])
            firma_ok_response = self.client.get(
                target,
                headers={**NAV_HEADERS, "Referer": str(success_response.url)},
            )
        else:
            firma_ok_response = success_response
        self._save_response("firma_ok.html", firma_ok_response)

        register_response = self._register_signed_communication(firma_ok_response)
        self._save_response("firma_ok_register.xml", register_response)

        result_url = urljoin(str(firma_ok_response.url), "resultado")
        result_response = self.client.get(
            result_url,
            headers={**NAV_HEADERS, "Referer": str(firma_ok_response.url)},
        )
        self._save_response("resultado.html", result_response)
        return result_response

    def _register_signed_communication(self, firma_ok_response: httpx.Response) -> httpx.Response:
        page_html = firma_ok_response.text
        source = registration_command_source(page_html)
        form_name = source.split(":", 1)[0]
        view_state = view_state_from_html(page_html)
        payload = {
            "javax.faces.partial.ajax": "true",
            "javax.faces.source": source,
            "javax.faces.partial.execute": "@all",
            "javax.faces.partial.render": "btnVolver spinner",
            source: source,
            form_name: form_name,
            "javax.faces.ViewState": view_state,
        }
        return self.client.post(
            str(firma_ok_response.url),
            data=payload,
            headers={**AJAX_HEADERS, "Referer": str(firma_ok_response.url)},
        )

    def _choose_local_certificate(self, signature_redirect: str) -> httpx.Response:
        query = parse_qs(urlparse(signature_redirect).query)
        payload = {
            "subjectid": query["subjectid"][0],
            "transactionid": query["transactionid"][0],
            "errorurl": query["errorurl"][0],
            "certorigin": "local",
            "op": query.get("op", ["batch"])[0],
        }
        return self.client.post(
            "https://servicio.mir.es/fire-signature/public/chooseCertificateOriginService",
            data=payload,
            headers={
                "Referer": signature_redirect,
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": NAV_HEADERS["Accept"],
            },
        )

    def _complete_notification_location(
        self,
        url: str,
        referer: str,
        data: dict[str, str],
    ) -> dict[str, str]:
        if (
            data.get("formCampos:pestanas:provinciaNotif_input")
            and data.get("formCampos:pestanas:localidadNotif_input")
        ):
            return data

        response = self._post_ajax(
            url,
            referer,
            data,
            AjaxStep(
                source="formCampos:pestanas:provinciaNotif",
                execute="formCampos:pestanas:provinciaNotif",
                render=(
                    "formCampos:pestanas:provinciaNotifFila "
                    "formCampos:pestanas:localidadNotifFila"
                ),
                event="change",
            ),
        )
        self._save_response("ajax_formCampos_pestanas_provinciaNotif.xml", response)
        new_view_state = view_state_from_partial(response.text)
        if new_view_state:
            data["javax.faces.ViewState"] = new_view_state

        locality = option_value_by_label(
            response.text,
            "formCampos:pestanas:localidadNotif_input",
            SEVILLA_NOTIFICATION_CITY,
        )
        data["formCampos:pestanas:localidadNotif_input"] = locality

        response = self._post_ajax(
            url,
            referer,
            data,
            AjaxStep(
                source="formCampos:pestanas:localidadNotif",
                execute="formCampos:pestanas:localidadNotif",
                render="formCampos:pestanas:localidadNotifFila",
                event="change",
            ),
        )
        self._save_response("ajax_formCampos_pestanas_localidadNotif.xml", response)
        new_view_state = view_state_from_partial(response.text)
        if new_view_state:
            data["javax.faces.ViewState"] = new_view_state
        return data

    def _clone_row(self, listing: httpx.Response, clone_row: int) -> httpx.Response:
        view_state = view_state_from_html(listing.text)
        source = f"formListado:listaComunicaciones:{clone_row}:clonar"
        payload = {
            "javax.faces.partial.ajax": "true",
            "javax.faces.source": source,
            "javax.faces.partial.execute": source,
            source: source,
            "formListado": "formListado",
            "formListado:listaComunicaciones_reflowDD": "0_1",
            "formListado:listaComunicaciones_rppDD": "10",
            "javax.faces.ViewState": view_state,
        }
        response = self.client.post(
            str(listing.url),
            data=payload,
            headers={**AJAX_HEADERS, "Referer": str(listing.url)},
        )
        redirect = partial_redirect(response.text)
        if not redirect:
            raise RuntimeError("La accion de clonar no devolvio redireccion")
        form_url = urljoin(str(listing.url), redirect)
        return self.client.get(form_url, headers={**NAV_HEADERS, "Referer": str(listing.url)})

    def _post_ajax(
        self, url: str, referer: str, data: dict[str, str], step: "AjaxStep"
    ) -> httpx.Response:
        payload = dict(data)
        payload["javax.faces.partial.ajax"] = "true"
        payload["javax.faces.source"] = step.source
        payload["javax.faces.partial.execute"] = step.execute
        if step.render:
            payload["javax.faces.partial.render"] = step.render
        if step.event:
            payload["javax.faces.behavior.event"] = step.event
            payload["javax.faces.partial.event"] = step.event
        if step.ignore_auto_update:
            payload["primefaces.ignoreautoupdate"] = "true"
        response = self.client.post(
            url,
            data=payload,
            headers={**AJAX_HEADERS, "Referer": referer},
        )
        print(
            f"{step.source}: HTTP {response.status_code} "
            f"validationFailed={partial_validation_failed(response.text)}"
        )
        return response

    def _validate(self, url: str, referer: str, data: dict[str, str]) -> httpx.Response:
        payload = dict(data)
        payload.update(
            {
                "javax.faces.partial.ajax": "true",
                "javax.faces.source": "formCampos:btnFirmar",
                "javax.faces.partial.execute": "@all",
                "javax.faces.partial.render": "formCampos",
                "formCampos:btnFirmar": "formCampos:btnFirmar",
            }
        )
        return self.client.post(url, data=payload, headers={**AJAX_HEADERS, "Referer": referer})

    def _save_response(self, filename: str, response: httpx.Response) -> None:
        self.artifacts_dir.joinpath(filename).write_text(response.text, encoding="utf-8")


@dataclass(frozen=True)
class AjaxStep:
    source: str
    execute: str
    render: str | None = None
    event: str | None = None
    ignore_auto_update: bool = False


@dataclass(frozen=True)
class PreparedCommunication:
    form_url: str
    referer: str
    view_state: str
    validation_response: httpx.Response


@dataclass(frozen=True)
class SignatureSession:
    mini_url: str
    request: "AutofirmaRequest"
    success_url: str
    success_form: dict[str, str]


def apply_draft(
    data: dict[str, str],
    draft: CommunicationDraft,
    view_state: str | None = None,
) -> dict[str, str]:
    result = dict(data)
    if view_state is not None:
        result["javax.faces.ViewState"] = view_state
    result["formCampos:pestanas:fecha_act1_input"] = draft.date
    result["formCampos:pestanas:horaInicio_act1_input"] = "0"
    result["formCampos:pestanas:minutosInicio_act1_input"] = "0"
    result["formCampos:pestanas:horaFin_act1_input"] = "23"
    result["formCampos:pestanas:minutosFin_act1_input"] = "55"
    result["formCampos:pestanas:lugarProteccion_act1"] = draft.place
    result["formCampos:pestanas:lugarRecuperacionRem_act1"] = draft.place
    result["formCampos:pestanas:alturaRem_act1_input"] = str(draft.height_m)
    result["formCampos:pestanas:alturaRem_act1_hinput"] = str(draft.height_m)
    result["formCampos:pestanas:ccAas_act1_input"] = draft.ccaa_code
    result["formCampos:pestanas:zona_act1:mapa_value"] = json.dumps(
        draft.polygon,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    result["formCampos:pestanas_activeIndex"] = "1"
    apply_notification_defaults(result)
    return result


def apply_notification_defaults(data: dict[str, str]) -> None:
    pairs = {
        "formCampos:pestanas:viaNotif": "formCampos:pestanas:viaoper",
        "formCampos:pestanas:codPostalNotif": "formCampos:pestanas:codPostaloper",
    }
    for notification_key, operator_key in pairs.items():
        if notification_key in data and not data.get(notification_key):
            operator_value = data.get(operator_key)
            if operator_value:
                data[notification_key] = operator_value

    if (
        "formCampos:pestanas:provinciaNotif_input" in data
        and not data.get("formCampos:pestanas:provinciaNotif_input")
    ):
        data["formCampos:pestanas:provinciaNotif_input"] = SEVILLA_NOTIFICATION_PROVINCE


def option_value_by_label(page_html: str, select_name: str, label: str) -> str:
    select_match = re.search(
        rf'<select[^>]+name="{re.escape(select_name)}"[^>]*>(.*?)</select>',
        page_html,
        re.S,
    )
    if not select_match:
        raise RuntimeError(f"No encuentro select {select_name}")

    for value, text in re.findall(
        r'<option[^>]*value="([^"]*)"[^>]*>(.*?)</option>',
        select_match.group(1),
        re.S,
    ):
        if html.unescape(re.sub(r"<.*?>", "", text)).strip() == label:
            return html.unescape(value)
    raise RuntimeError(f"No encuentro opcion {label} en {select_name}")


def form_data(page_html: str, form_name: str) -> dict[str, str]:
    for form in parse_forms(page_html):
        if form_name in form.fields:
            return dict(form.fields)
    raise RuntimeError(f"No encuentro el formulario {form_name}")


def load_polygon(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def charco_de_la_pava_polygon() -> dict[str, object]:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "1",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-6.0218, 37.3842],
                            [-6.0126, 37.3842],
                            [-6.0126, 37.3790],
                            [-6.0218, 37.3790],
                            [-6.0218, 37.3842],
                        ]
                    ],
                },
                "properties": {
                    "tipo": "Generica",
                    "visible": True,
                    "color": "#0000FF",
                    "centrado": False,
                    "editable": False,
                    "precision": 0,
                    "animado": False,
                    "lineaDiscontinua": False,
                    "origen": False,
                    "destino": False,
                    "opacity": "0.3",
                },
            }
        ],
    }


@dataclass(frozen=True)
class AutofirmaRequest:
    batch_xml_b64: str
    pre_sign_url: str
    post_sign_url: str
    storage_url: str
    retrieve_url: str


def autofirma_request_from_html(page_html: str) -> AutofirmaRequest:
    return AutofirmaRequest(
        batch_xml_b64=js_var(page_html, "batchXmlB64"),
        pre_sign_url=js_var(page_html, "preSignUrl"),
        post_sign_url=js_var(page_html, "postSignUrl"),
        storage_url=script_arg(page_html, "AutoScript.setServlets", 0),
        retrieve_url=script_arg(page_html, "AutoScript.setServlets", 1),
    )


def signature_success_form(page_html: str) -> dict[str, str]:
    for form in parse_forms(page_html):
        if "transactionid" in form.fields and "afirmabatchresult" in form.fields:
            data = dict(form.fields)
            data["__action__"] = form.action
            return data
    raise RuntimeError("No encuentro el formulario de exito de AutoFirma")


def run_autofirma_and_wait(
    client: httpx.Client,
    request: AutofirmaRequest,
    *,
    wait_seconds: int,
    artifacts_dir: Path | None = None,
) -> str:
    operation_id = random_autofirma_id()
    url = build_autofirma_batch_url(request, operation_id)
    print(f"AutoFirma: abriendo aplicacion nativa (id={operation_id}, url={len(url)} chars)", flush=True)
    open_autofirma_url(url)

    deadline = time.monotonic() + wait_seconds
    iteration = 0
    while time.monotonic() < deadline:
        response = client.post(
            request.retrieve_url,
            data={"op": "get", "v": "1_0", "id": operation_id, "it": str(iteration)},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        text = response.text.strip()
        if text and not should_keep_waiting_for_autofirma(text):
            if artifacts_dir:
                artifacts_dir.joinpath("autofirma_retrieve_raw.txt").write_text(
                    text, encoding="utf-8"
                )
            result = batch_result_from_retrieve_payload(text)
            validate_batch_result(result)
            print("AutoFirma: resultado recibido")
            return result
        iteration += 1
        time.sleep(2)

    raise TimeoutError("AutoFirma no devolvio resultado dentro del tiempo de espera")


def build_autofirma_batch_url(request: AutofirmaRequest, operation_id: str) -> str:
    params = {
        "jvc": "3",
        "ver": "3",
        "op": "batch",
        "id": operation_id,
        "stservlet": request.storage_url,
        "batchpresignerurl": request.pre_sign_url,
        "batchpostsignerurl": request.post_sign_url,
        "aw": "true",
        "appname": "servicio.mir.es",
        "needcert": "true",
        "dat": base64_to_urlsafe(request.batch_xml_b64),
    }
    return "afirma://batch?" + "&".join(
        f"{key}={quote(value, safe='')}" for key, value in params.items()
    )


def should_keep_waiting_for_autofirma(text: str) -> bool:
    lowered = text.lower()
    if lowered.startswith("err-06"):
        return True
    if lowered.startswith("#wait"):
        return True
    if lowered.startswith("err-"):
        raise RuntimeError(f"AutoFirma devolvio error: {text}")
    if text in {"CANCEL", "CANCEL\r\n", "CANCEL\n"}:
        raise RuntimeError("Operacion cancelada en AutoFirma")
    return False


def batch_result_from_retrieve_payload(text: str) -> str:
    batch_result = unquote_plus(text).split("|", 1)[0]
    if re.match(r"^\d+\.", batch_result):
        raise RuntimeError("AutoFirma devolvio el resultado cifrado; este flujo usa resultado sin clave")
    if batch_result.startswith("<"):
        return base64.b64encode(batch_result.encode("utf-8")).decode("ascii")
    return base64_urlsafe_to_base64(batch_result)


def validate_batch_result(result_b64: str) -> None:
    padding = "=" * (-len(result_b64) % 4)
    decoded = base64.b64decode(result_b64 + padding)
    if b"<signs" not in decoded or b"DONE_AND_SAVED" not in decoded:
        raise RuntimeError("El resultado de AutoFirma no parece un lote firmado correctamente")


def js_var(page_html: str, name: str) -> str:
    match = re.search(rf'var {re.escape(name)} = "([^"]*)"', page_html)
    if not match:
        raise RuntimeError(f"No encuentro variable JavaScript {name}")
    return html.unescape(match.group(1))


def script_arg(page_html: str, function_name: str, index: int) -> str:
    pattern = rf"{re.escape(function_name)}\((.*?)\);"
    match = re.search(pattern, page_html, re.S)
    if not match:
        raise RuntimeError(f"No encuentro llamada {function_name}")
    args = re.findall(r'"([^"]*)"', match.group(1))
    try:
        return html.unescape(args[index])
    except IndexError as exc:
        raise RuntimeError(f"No encuentro argumento {index} de {function_name}") from exc


def random_autofirma_id() -> str:
    alphabet = "1234567890abcdefghijklmnopqrstuwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return "".join(secrets.choice(alphabet) for _ in range(20))


def base64_to_urlsafe(value: str) -> str:
    return value.replace("+", "-").replace("/", "_").replace("\n", "").replace("\r", "")


def base64_urlsafe_to_base64(value: str) -> str:
    return value.replace(" ", "+").replace("-", "+").replace("_", "/")


def open_autofirma_url(url: str) -> None:
    bundle_id = "es.gob.afirma.simpleafirma.osx"
    result = subprocess.run(["open", "-b", bundle_id, url], check=False)
    if result.returncode == 0:
        return
    subprocess.run(["open", url], check=True)


def registration_command_source(page_html: str) -> str:
    match = re.search(r"PrimeFaces\.ab\(\{s:&quot;([^&]+)&quot;,f:&quot;[^&]+&quot;,u:&quot;btnVolver spinner", page_html)
    if match:
        return html.unescape(match.group(1))
    match = re.search(r'PrimeFaces\.ab\(\{s:"([^"]+)",f:"[^"]+",u:"btnVolver spinner"', page_html)
    if match:
        return html.unescape(match.group(1))
    raise RuntimeError("No encuentro el comando de registro post-firma")


def view_state_from_html(text: str) -> str:
    match = re.search(r'name="javax\.faces\.ViewState"[^>]*value="([^"]+)"', text)
    if not match:
        raise RuntimeError("No encuentro javax.faces.ViewState")
    return html.unescape(match.group(1))


def view_state_from_partial(text: str) -> str | None:
    root = parse_partial(text)
    if root is None:
        return None
    for update in root.findall(".//update"):
        if update.attrib.get("id", "").endswith("javax.faces.ViewState:0"):
            return update.text or ""
    return None


def partial_redirect(text: str) -> str | None:
    root = parse_partial(text)
    if root is None:
        return None
    redirect = root.find(".//redirect")
    if redirect is None:
        return None
    return html.unescape(redirect.attrib.get("url", ""))


def partial_validation_failed(text: str) -> bool:
    root = parse_partial(text)
    if root is None:
        return False
    for extension in root.findall(".//extension"):
        if "validationFailed" in (extension.text or ""):
            return True
    return False


def parse_partial(text: str) -> ElementTree.Element | None:
    try:
        return ElementTree.fromstring(text)
    except ElementTree.ParseError:
        return None


def safe_filename(value: str) -> str:
    return value.replace(":", "_").replace("/", "_")


if __name__ == "__main__":
    main()
