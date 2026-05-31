# AGENTS.md

Act as a senior engineer: concise, direct, execution-focused, and pragmatic.
Keep this project small, explicit, and easy to debug.

## Safety Rules

- Do not run real submissions without explicit user authorization in the current
  turn. In this project, `--sign` submits real communications, including when
  `--sign-mode headless` is used.
- Do not delete, cancel, modify, or replace already registered communications
  unless explicitly requested.
- Do not print or document passwords, `.p12` contents, PEM keys, full SAML
  payloads, cookies, certificates, signatures, or raw AutoFirma payloads.
- Treat `*.har`, `.env`, `*.p12`, `artifacts/`, and official PDFs as sensitive
  material. Do not commit them.
- If official PDFs or acknowledgements are downloaded, save them under
  `artifacts/` unless the user asks for another path.

## Execution

- Use `uv run ...` for project Python commands.
- In this environment, prefix shell commands with `rtk`.
- Use `--insecure` for network diagnostics against the government site only
  because it was required during this local investigation.
- Before claiming something works, verify with a real run or with
  `python -m compileall src/drones_mir_comunicador` when applicable.

## Implementation Style

- Prefer small functions and explicit data.
- Do not introduce frameworks or large dependencies for simple HTTP or parsing
  tasks.
- Reuse the existing login, form, P12, and AutoFirma helpers.
- Use `apply_patch` for manual file edits.
- Keep code and docs ASCII unless the file already needs non-ASCII text.

## Site-Specific Notes

- The app is JSF/PrimeFaces and depends on `javax.faces.ViewState`.
- Partial responses update `ViewState`; keep the latest value.
- Do not include every HTML button as a form field. In JSF, sending a button by
  mistake can execute unwanted actions such as clearing pilot or UAS data.
- The local parser should collect `input`, `select`, and `textarea`; buttons are
  added only for the intended action.
- To enter drones from Cl@ve, the `Referer` for `/drones-web/clave` and
  `/drones-web/acceso` must be `https://pasarela.clave.gob.es/`.
- After `/firmaOk`, reproduce the automatic registration AJAX before going to
  `/resultado`; otherwise the communication may not appear in the listing.

## Reference Commands

Validate without submitting:

```bash
rtk proxy uv run drones-communication --insecure \
  --date 10/06/2026 \
  --place "Charco de la Pava, Triana, Sevilla" \
  --height 120
```

Submit for real:

```bash
rtk proxy uv run drones-communication --insecure \
  --date 10/06/2026 \
  --place "Charco de la Pava, Triana, Sevilla" \
  --height 120 \
  --sign
```

Submit for real without opening AutoFirma:

```bash
rtk proxy uv run drones-communication --insecure \
  --date 10/06/2026 \
  --place "Charco de la Pava, Triana, Sevilla" \
  --height 120 \
  --sign \
  --sign-mode headless
```

Compile:

```bash
rtk proxy uv run python -m compileall src/drones_mir_comunicador
```

## Living Documentation

- Update `lessons.md` when a new endpoint, parameter, failure, or workaround is
  discovered. This file is intentionally ignored because it may contain
  sensitive investigation notes.
- Update `README.md` only with stable usage information.
