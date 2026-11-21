# Registros de ejecución

Este directorio almacena salidas redactadas de comandos y pytest capturadas con
`tee`. Un registro solo constituye evidencia si proviene de una ejecución real.

## Convención de nombres

```text
YYYY-MM-DD_Fxx_short-name.log
```

Ejemplos:

- `2026-11-21_F01-queue-setup.log`
- `2026-11-21_offline-tests.log`
- `2026-11-21_cleanup.log`

Usa el código F cuando el registro corresponda a una fila de verificación. Usa
un nombre neutro como `offline-tests` cuando abarque varias filas.

## Patrón de captura

```bash
./.venv/bin/python -m pytest -m "not integracion" -q \
  | tee evidencias/ejecuciones/2026-11-21_offline-tests.log
```

```bash
./.venv/bin/python scripts/check_dlq.py \
  | tee evidencias/ejecuciones/2026-11-21_F08-dlq-inspection.log
```

Incluye la línea de comando al principio del registro cuando la terminal no la
registre automáticamente.

## Redacción antes de confirmar los cambios

- Elimina el contenido de `.env` y todos los volcados del entorno.
- Reemplaza por `<redacted>` los tokens, contraseñas, secretos de webhook, encabezados de autorización,
  firmas, identificadores de recepción, ID de chat y secretos de AWS.
- Elimina las URL privadas, direcciones de correo personales, números de teléfono y datos personales
  sin procesar.
- Vuelve a abrir el archivo guardado después de editarlo y busca `token`, `secret`,
  `password`, `credential`, `authorization`, `signature` y `receipt`.
- Ejecuta `git status` e inspecciona los cambios preparados antes de confirmarlos.

Nunca confirmes un registro sin redactar porque «probablemente no contiene nada
confidencial». Revísalo.
