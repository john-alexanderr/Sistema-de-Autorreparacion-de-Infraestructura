# Capturas de pantalla

Este directorio almacena capturas de pantalla redactadas que respaldan la matriz
de verificación y las evidencias de los roles.

## Convención de nombres

```text
YYYY-MM-DD_Fxx_short-name.png
```

Ejemplos:

- `2026-11-21_F01-queue-attributes.png`
- `2026-11-21_F08-dlq-message.png`
- `2026-11-21_F02-ec2-running.png`

Usa palabras en minúscula separadas por guiones. Incluye el código F cuando la
imagen corresponda a una fila.

## Índice de capturas de pantalla

Mantén un índice breve para que quien revise pueda encontrar cada artefacto.
Agrega entradas únicamente para capturas de pantalla reales.

| Fecha | Código F | Qué muestra | Archivo | Redactada |
|---|---|---|---|---|
| `[PENDING]` | `[PENDING]` | `[PENDING]` | `[PENDING]` | `[PENDING]` |

## Lista de control de redacción

- [ ] No se vea ninguna ventana de `.env`, historial de terminal ni volcado del entorno.
- [ ] No aparezcan tokens de bots, ID de chat, secretos de webhook, claves de AWS ni tokens de LocalStack.
- [ ] No se vea ningún identificador de recepción.
- [ ] No aparezcan URL privadas, correos electrónicos, números de teléfono ni datos personales.
- [ ] Se haya recortado o redactado con `<redacted>` cuando sea necesario.
- [ ] Se haya vuelto a abrir la captura después de editarla para comprobar que no haya filtraciones.

Prefiere una captura de terminal que muestre únicamente el comando y su salida
redactada, en lugar de una captura de todo el escritorio.
