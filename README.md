# drones-mir-comunicador

Proyecto formativo para investigar si la comunicacion de vuelo de drones del MIR/SES puede automatizarse por HTTP, sin usar la web interactiva.

Estado actual: cliente HTTP funcional para login con certificado, clonado, validacion,
firma con AutoFirma o con el prototipo headless, y presentacion real cuando se
usa `--sign`.

## Objetivo

- Analizar HARs exportados desde navegador sin imprimir datos personales.
- Entender el flujo JSF/PrimeFaces y AutoFirma.
- Construir incrementalmente un cliente HTTP reproducible.
- Mantener cualquier envio real detras de una accion explicita.

## Instalacion

```bash
uv sync
```

## Uso inicial

Analizar un HAR:

```bash
uv run drones-har-summary /Users/david/Downloads/drones.ses.mir.es.har
```

Ver la secuencia JSF/AutoFirma sin valores de formulario:

```bash
uv run drones-har-flow /Users/david/Downloads/drones.ses.mir.es.completo.har
```

Extraer solo el flujo AutoFirma y el resultado de lote:

```bash
uv run drones-har-autofirma /Users/david/Downloads/drones.ses.mir.es.completo.all.har
```

Probar que el `.p12` local sirve como certificado TLS de cliente:

```bash
uv run drones-cert-probe
```

Probar el login SAML directo al tramite de drones sin presentar nada:

```bash
uv run drones-login-probe --insecure
```

Clonar la ultima comunicacion, cambiar datos de actividad, validar, firmar con
AutoFirma y presentar:

```bash
uv run drones-communication --insecure \
  --date 10/06/2026 \
  --place "Charco de la Pava, Triana, Sevilla" \
  --height 120 \
  --sign
```

Sin `--sign`, el comando solo valida el formulario contra la sede y no presenta.

Preparar el puente headless de firma sin firmar ni presentar nada:

```bash
uv run drones-headless-signer
```

Firmar sin abrir AutoFirma visual, usando el `.p12` local y el cliente oficial
@firma de lotes:

```bash
uv run drones-communication --insecure \
  --date 10/06/2026 \
  --place "Charco de la Pava, Triana, Sevilla" \
  --height 120 \
  --sign \
  --sign-mode headless
```

`--sign --sign-mode headless` tambien presenta una comunicacion real: solo evita
la ventana de AutoFirma.

Exportar resumen JSON:

```bash
uv run drones-har-summary /Users/david/Downloads/drones.ses.mir.es.har --json
```

## Hallazgos del HAR inicial

- La app usa JSF/PrimeFaces y `javax.faces.ViewState`.
- El formulario principal se publica contra `/drones-web/formulario`.
- El flujo de firma pasa por `servicio.mir.es/fire-signature/public/afirma`.
- Despues de AutoFirma vuelve a `/drones-web/firmaOk`, `/resultado` y `/comunicacion`.
- El HAR no contiene el HTML inicial completo de `altaComunicacion`; solo peticiones posteriores.

## Hallazgos del HAR completo All

- El alta entra por `GET /drones-web/altaComunicacion`.
- El boton de alta hace `POST /drones-web/altaComunicacion` y redirige a `/drones-web/formulario?enNombrePropio=true&accion=INSERTAR`.
- El boton `formCampos:btnFirmar` valida el formulario completo.
- El boton `formFirma:btnFirmar` inicia la firma.
- La sede abre `ChooseCertificateOrigin.jsp` con `op=batch`, `transactionid`, `subjectid` y `errorurl`.
- `chooseCertificateOriginService` recibe `certorigin`, `op`, `subjectid`, `transactionid` y `errorurl`.
- AutoFirma trabaja contra `/fire-signature/public/afirma/retrieve` y devuelve a `miniappletSuccessService`.
- El resultado final de AutoFirma es un `afirmabatchresult` con dos elementos `DONE_AND_SAVED`: XML de datos y PDF.
- Una peticion limpia sin sesion a `/altaComunicacion` redirige a `https://sede.interior.gob.es`; el script necesitara resolver autenticacion/sesion antes de llegar al formulario.

## Enfoque previsto

1. Reproducir login, clonado y validacion desde una sesion HTTP limpia.
2. Extraer `ViewState` y campos dinamicos desde HTML/partial responses.
3. Invocar AutoFirma mediante `afirma://batch`.
4. Alternativamente, firmar el lote en modo headless con `BatchSigner` oficial.
5. Completar el registro post-firma en `/firmaOk` y confirmar `/resultado`.

## Seguridad

No guardes HARs reales, certificados, firmas, justificantes o datos personales en git. El proyecto ignora `*.har`, `.env`, certificados y `artifacts/` por defecto.

`--sign` presenta comunicaciones reales. Revisar fecha, lugar, altura y poligono antes de usarlo.
El modo headless carga el `.p12` y la contrasena en memoria localmente; no
imprime la contrasena ni manda el batch por argumentos de proceso.
