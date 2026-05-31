from __future__ import annotations

import argparse
import json

from drones_mir_comunicador.flow import render_flow, summarize_flow


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="drones-har-flow",
        description="Muestra la secuencia JSF/AutoFirma de un HAR sin valores de formulario.",
    )
    parser.add_argument("har", help="Ruta al archivo .har")
    parser.add_argument("--json", action="store_true", help="Imprime la traza como JSON")
    args = parser.parse_args()

    events = summarize_flow(args.har)
    if args.json:
        print(json.dumps(events, ensure_ascii=False, indent=2))
    else:
        print(render_flow(events))
