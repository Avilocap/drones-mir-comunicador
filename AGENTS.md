# AGENTS.md

Actua como ingeniero senior: conciso, directo y orientado a ejecucion. Mantén
el proyecto pequeno, explicito y facil de depurar.

## Reglas de seguridad

- No ejecutes presentaciones reales sin autorizacion explicita del usuario en el
  turno actual. En este proyecto, `--sign` presenta comunicaciones reales,
  tambien con `--sign-mode headless`.
- No borres, canceles, modifiques ni sustituyas comunicaciones ya registradas
  salvo peticion explicita.
- No imprimas ni guardes en documentacion contrasenas, contenido del `.p12`,
  claves PEM, SAML completo, cookies, certificados, firmas ni payloads crudos de
  AutoFirma.
- Trata `*.har`, `.env`, `*.p12`, `artifacts/` y PDFs oficiales como material
  sensible. No los subas a git.
- Si descargas justificantes o PDFs, guárdalos en `artifacts/` salvo que el
  usuario indique otra ruta.

## Ejecucion

- Usa `uv run ...` para ejecutar comandos Python del proyecto.
- En este entorno, antepon `rtk` a comandos de shell.
- Para diagnosticos de red contra la sede, usa `--insecure` solo porque ya fue
  necesario en esta investigacion local.
- Antes de decir que algo funciona, verifica con una ejecucion real o con
  `python -m compileall src/drones_mir_comunicador` cuando aplique.

## Estilo de implementacion

- Prefiere funciones pequenas y datos explicitos.
- No introduzcas frameworks ni dependencias grandes para resolver parsing o
  peticiones HTTP sencillas.
- Reutiliza los helpers existentes de login, formularios, P12 y AutoFirma.
- Edita ficheros manualmente con `apply_patch`.
- Mantén ASCII en codigo y documentacion salvo que el fichero ya use caracteres
  acentuados o el texto lo necesite claramente.

## Particularidades de la sede

- La app es JSF/PrimeFaces y depende de `javax.faces.ViewState`.
- Los partial responses actualizan el `ViewState`; conserva el ultimo valor.
- No incluyas todos los botones HTML como campos de formulario. En JSF eso puede
  ejecutar acciones no deseadas como limpiar piloto o UAS.
- El parser local debe recoger `input`, `select` y `textarea`; los botones se
  anaden solo cuando se quiere pulsar una accion concreta.
- Para entrar desde Cl@ve a drones, el `Referer` de `/drones-web/clave` y
  `/drones-web/acceso` debe ser `https://pasarela.clave.gob.es/`.
- Despues de `/firmaOk`, reproduce el AJAX automatico de registro antes de ir a
  `/resultado`; si no, la comunicacion puede no aparecer en el listado.

## Comandos de referencia

Validar sin presentar:

```bash
rtk proxy uv run drones-communication --insecure \
  --date 10/06/2026 \
  --place "Charco de la Pava, Triana, Sevilla" \
  --height 120
```

Presentar realmente:

```bash
rtk proxy uv run drones-communication --insecure \
  --date 10/06/2026 \
  --place "Charco de la Pava, Triana, Sevilla" \
  --height 120 \
  --sign
```

Presentar realmente sin abrir AutoFirma:

```bash
rtk proxy uv run drones-communication --insecure \
  --date 10/06/2026 \
  --place "Charco de la Pava, Triana, Sevilla" \
  --height 120 \
  --sign \
  --sign-mode headless
```

Compilar:

```bash
rtk proxy uv run python -m compileall src/drones_mir_comunicador
```

## Documentacion viva

- Actualiza `lessons.md` cuando descubras un endpoint, parametro, fallo o
  workaround nuevo.
- Actualiza `README.md` solo con informacion de uso estable.
