from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from drones_mir_comunicador.autofirma import render_autofirma, summarize_autofirma


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="drones-har-autofirma",
        description="Extrae el flujo AutoFirma de un HAR sin mostrar certificados ni datos personales.",
    )
    parser.add_argument("har", help="Ruta al archivo .har")
    parser.add_argument("--json", action="store_true", help="Imprime el resumen como JSON")
    args = parser.parse_args()

    summary = summarize_autofirma(args.har)
    if args.json:
        print(json.dumps(_jsonable(summary), ensure_ascii=False, indent=2))
    else:
        print(render_autofirma(summary))


def _jsonable(value: object) -> object:
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    return value

