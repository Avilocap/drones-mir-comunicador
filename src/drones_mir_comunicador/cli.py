from __future__ import annotations

import argparse
import json
from pathlib import Path

from drones_mir_comunicador.har import render_text, summarize


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="drones-har-summary",
        description="Analiza un HAR del flujo drones.ses.mir.es sin mostrar valores sensibles.",
    )
    parser.add_argument("har", type=Path, help="Ruta al archivo .har")
    parser.add_argument("--json", action="store_true", help="Imprime el resumen como JSON")
    args = parser.parse_args()

    summary = summarize(args.har)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(render_text(summary))


if __name__ == "__main__":
    main()

