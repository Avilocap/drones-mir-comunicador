# drones-mir-comunicador

Educational project for researching whether the Spanish MIR/SES drone flight
communication flow can be automated over HTTP, without using the interactive
website.

Current status: the HTTP client can log in with a certificate, clone an existing
communication, update flight data, validate the JSF form, sign either with
AutoFirma or with the experimental headless signer, and submit a real filing
when `--sign` is used.

## Goals

- Analyze browser-exported HAR files without printing personal data.
- Understand the JSF/PrimeFaces and AutoFirma flow.
- Build a reproducible HTTP client incrementally.
- Keep every real filing behind an explicit action.

## Installation

```bash
uv sync
```

## Usage

Analyze a HAR:

```bash
uv run drones-har-summary /path/to/drones.ses.mir.es.har
```

Show the JSF/AutoFirma sequence without form values:

```bash
uv run drones-har-flow /path/to/drones.ses.mir.es.completo.har
```

Extract only the AutoFirma flow and batch result:

```bash
uv run drones-har-autofirma /path/to/drones.ses.mir.es.completo.all.har
```

Check that the local `.p12` can be used as a TLS client certificate:

```bash
uv run drones-cert-probe
```

Test direct SAML login to the drone procedure without submitting anything:

```bash
uv run drones-login-probe --insecure
```

Clone the latest communication, update activity data, validate, sign with
AutoFirma, and submit:

```bash
uv run drones-communication --insecure \
  --date 10/06/2026 \
  --place "Charco de la Pava, Triana, Sevilla" \
  --height 120 \
  --sign
```

Without `--sign`, the command only validates the form against the government
site and does not submit a filing.

Prepare the headless signing bridge without signing or submitting anything:

```bash
uv run drones-headless-signer
```

Sign without opening the AutoFirma desktop app, using the local `.p12` and the
official @firma batch client:

```bash
uv run drones-communication --insecure \
  --date 10/06/2026 \
  --place "Charco de la Pava, Triana, Sevilla" \
  --height 120 \
  --sign \
  --sign-mode headless
```

`--sign --sign-mode headless` still submits a real communication. It only avoids
opening the AutoFirma UI.

Export a JSON summary:

```bash
uv run drones-har-summary /path/to/drones.ses.mir.es.har --json
```

## Initial HAR Findings

- The app uses JSF/PrimeFaces and `javax.faces.ViewState`.
- The main form posts to `/drones-web/formulario`.
- The signing flow goes through `servicio.mir.es/fire-signature/public/afirma`.
- After AutoFirma, the browser returns to `/drones-web/firmaOk`, `/resultado`,
  and `/comunicacion`.
- The first HAR did not contain the full initial `altaComunicacion` HTML, only
  later requests.

## Complete HAR Findings

- New communications start with `GET /drones-web/altaComunicacion`.
- The create button posts to `/drones-web/altaComunicacion` and redirects to
  `/drones-web/formulario?enNombrePropio=true&accion=INSERTAR`.
- `formCampos:btnFirmar` validates the complete form.
- `formFirma:btnFirmar` starts the signature flow.
- The site opens `ChooseCertificateOrigin.jsp` with `op=batch`,
  `transactionid`, `subjectid`, and `errorurl`.
- `chooseCertificateOriginService` receives `certorigin`, `op`, `subjectid`,
  `transactionid`, and `errorurl`.
- AutoFirma works against `/fire-signature/public/afirma/retrieve` and returns
  to `miniappletSuccessService`.
- AutoFirma's final result is an `afirmabatchresult` with two `DONE_AND_SAVED`
  entries: the data XML and the PDF.
- A clean unauthenticated request to `/altaComunicacion` redirects to
  `https://sede.interior.gob.es`; the script must resolve authentication and
  session state before reaching the form.

## Approach

1. Reproduce login, cloning, and validation from a clean HTTP session.
2. Extract `ViewState` and dynamic fields from HTML/partial responses.
3. Invoke AutoFirma through `afirma://batch`.
4. Alternatively, sign the batch in headless mode with the official
   `BatchSigner`.
5. Complete post-signature registration at `/firmaOk` and confirm `/resultado`.

## Security

Do not commit real HAR files, certificates, signatures, official PDFs,
acknowledgements, or personal data. The project ignores `*.har`, `.env`,
certificate files, and `artifacts/` by default.

`--sign` submits real communications. Review date, location, height, and polygon
before using it. Headless mode loads the `.p12` and password in local memory; it
does not print the password or pass the batch data as process arguments.
