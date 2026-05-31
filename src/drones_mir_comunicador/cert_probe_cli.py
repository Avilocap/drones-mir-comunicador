from __future__ import annotations

import argparse
from pathlib import Path

import httpx

from drones_mir_comunicador.p12 import temporary_pem_pair
from drones_mir_comunicador.secrets import (
    find_certificate_path,
    load_env,
    require_certificate_password,
)


DEFAULT_PROBE_URL = "https://pasarela-ident.clave.gob.es/IdP2/AuthenticateCitizen"


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="drones-cert-probe",
        description="Prueba que el certificado P12 puede usarse como certificado TLS de cliente.",
    )
    parser.add_argument("--env", type=Path, default=Path(".env"), help="Ruta al .env")
    parser.add_argument("--url", default=DEFAULT_PROBE_URL, help="URL de prueba")
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Desactiva verificacion TLS del servidor solo para diagnostico local",
    )
    args = parser.parse_args()

    env = load_env(args.env)
    p12_path = find_certificate_path(env, args.env.parent)
    password = require_certificate_password(env)

    print("P12: encontrado")
    print("Password: cargada desde .env")

    with temporary_pem_pair(p12_path, password) as (cert_path, key_path):
        print("PEM temporal: generado")
        with httpx.Client(
            cert=(str(cert_path), str(key_path)),
            verify=not args.insecure,
            timeout=30,
            follow_redirects=False,
        ) as client:
            response = client.get(args.url)

    print(f"URL: {args.url}")
    print(f"HTTP status: {response.status_code}")
    print(f"Content-Type: {response.headers.get('content-type', '-')}")
    print("PEM temporal: eliminado")


if __name__ == "__main__":
    main()
