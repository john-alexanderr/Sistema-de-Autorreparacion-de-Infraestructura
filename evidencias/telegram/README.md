# Evidencia de Telegram

Este directorio está reservado para demostrar que el flujo de Fénix envió una
notificación real por Telegram. Las pruebas simuladas no cuentan como evidencia
de Telegram real.

## Captura automatizada con datos redactados

Define lo siguiente en el archivo `.env`, ignorado por el control de versiones (nunca lo confirmes):

```text
NOTIFY_PROVIDER=telegram
TELEGRAM_BOT_TOKEN=<bot token>
TELEGRAM_CHAT_ID=<chat id>
```

Valida la configuración sin enviar ningún mensaje:

```bash
./.venv/bin/python scripts/telegram_evidence.py --dry-run
```

Envía un mensaje real y guarda la evidencia redactada:

```bash
./.venv/bin/python scripts/telegram_evidence.py
```

El script usa el adaptador de producción `fenix.services.notifications.notify`.
Escribe en este directorio una confirmación JSON mínima que contiene el
proveedor, el estado, `"ok": true` y una marca de tiempo UTC. La salida se limita
a este directorio del repositorio. El ID del mensaje de Telegram, el texto
enviado, las credenciales, el ID del chat y la URL de Telegram Bot API no se guardan
ni se imprimen.

## Evidencia obligatoria

El archivo de confirmación redactado es suficiente; no adjuntes una captura de
pantalla ni la respuesta sin procesar de la API. Registra únicamente:

- La fecha del envío real.
- El comando o flujo que lo activó.
- El estado de confirmación genérico `ok: true`.

## Elementos que nunca deben incluirse

- `TELEGRAM_BOT_TOKEN` ni ningún token de bot.
- `TELEGRAM_CHAT_ID` ni ningún identificador de chat privado.
- La URL de Telegram Bot API que incluya el token.
- Los ID de mensajes de Telegram ni el texto o cuerpo del mensaje.
- Enlaces a chats privados, nombres de usuario, números de teléfono ni datos personales.
- Capturas de pantalla o cuerpos de respuesta que revelen el contenido o los identificadores del mensaje.

## Evidencia capturada

| Campo | Valor |
|---|---|
| Fecha | `2026-11-21T06:01:38Z` |
| Comando que lo activó | `./.venv/bin/python scripts/telegram_evidence.py` |
| Archivo de evidencia | `telegram/2026-11-21T060138Z_a9b1da_F02_telegram-evidence.json` |
| Confirmación | `"ok": true` |
| ¿Se registró el ID o el texto del mensaje? | `No` |
| Redactado por | Script automatizado; revisión humana pendiente |

La confirmación fue producida por un envío real y no contiene token, chat ID,
URL de Telegram Bot API, ID de mensaje ni texto del mensaje.

## Plantilla

| Campo | Valor |
|---|---|
| Fecha | `[PENDING: YYYY-MM-DD]` |
| Comando o flujo que lo activó | `[PENDING]` |
| Archivo de evidencia | `[PENDING: ruta relativa dentro de evidencias/telegram/]` |
| Estado de confirmación | `[PENDING: enviado; ok=true]` |
| ¿Se registró el ID o el texto del mensaje? | `No` |
| Persona que redactó los datos | `[PENDING]` |

El script crea en este directorio una confirmación JSON con marca de tiempo.
Mantén los marcadores de posición hasta que se realice el envío real; nunca
incluyas ID ni contenido de mensajes en el nombre del archivo de evidencia.
