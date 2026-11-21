# Índice de evidencias

Este directorio contiene las evidencias del curso para el proyecto de
autorreparación local de infraestructura Fénix. Cada archivo debe provenir de
un comando real, una ejecución de pruebas, una inspección de nube, una
confirmación de Telegram o una grabación realizada por el equipo.

> **Nunca fabriques evidencias.** Los marcadores de posición deben mantenerse
> hasta que se ejecute el comando real. No copies el resultado esperado en una
> columna «Observado», no inventes capturas de pantalla ni crees una confirmación
> falsa de Telegram o un enlace de video ficticio. Quienes revisen el curso deben
> poder reproducir el comando y comparar el resultado observado.

## Lista de control de privacidad y redacción

Antes de confirmar cualquier evidencia, verifica todos los puntos siguientes.

- [ ] No se incluyan `.env`, valores de `.env.example` ni volcados del entorno local.
- [ ] No aparezcan tokens de bots, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, secretos de webhook,
      tokens de autorización de LocalStack ni claves secretas de AWS.
- [ ] No aparezcan ID de claves de acceso de AWS, tokens de sesión ni identificadores reales de cuentas.
- [ ] No aparezcan URL privadas, enlaces a chats privados, correos electrónicos, números de teléfono
      ni datos personales sin procesar.
- [ ] Los campos que parezcan contener secretos se reemplacen por `<redacted>`, incluidos tokens,
      contraseñas, credenciales, encabezados de autorización, firmas e identificadores
      de recepción.
- [ ] Se hayan inspeccionado `git status` y `git diff --cached` antes de confirmar los cambios.
- [ ] Se hayan abierto las capturas de pantalla y los registros después de redactarlos para comprobar que no haya filtraciones.

## Estructura de directorios

```text
evidencias/
├── README.md                  # This index and capture instructions
├── matriz-verificacion.md     # F01-F16 evidence matrix template
├── roles/                     # Role evidence and defense notes
│   ├── README.md
│   └── PLANTILLA.md
├── ejecuciones/               # Sanitized command and pytest logs
├── capturas/                  # Redacted screenshots
├── telegram/                  # Real Telegram confirmation evidence
└── video/                     # Video link and timestamp template
```

## Artefactos obligatorios

| Artefacto | Ubicación | Requisito |
|---|---|---|
| Evidencias del equipo e individuales | `roles/I1/` … `roles/I6/` | Una carpeta por cada rol asignado, basada en `roles/PLANTILLA.md`. |
| Matriz de integración F01-F16 | `matriz-verificacion.md` | Antes de la entrega, cada fila debe incluir un comando real o una referencia de pytest y el resultado observado. |
| Evidencia de envío real por Telegram | `telegram/` | Captura redactada o JSON que muestre `ok: true`, además de la fecha y el comando. Sin token ni ID de chat. |
| Video y marcas de tiempo | `video/` | Enlace a una grabación real y marcas de tiempo de los temas. No presentes como final una URL de marcador de posición. |
| Declaración de asistencia de IA | Documento de entrega del curso | Indica dónde se utilizó asistencia de IA y qué revisó el equipo. |
| Evidencia de limpieza | `ejecuciones/` o `capturas/` | Muestra `docker compose down` o una limpieza aprobada equivalente y el estado final. |

## Cómo recopilar evidencias

Ejecuta todos los comandos desde la raíz del repositorio y guarda la salida con
`tee` para que el registro sea visible y quede almacenado.

### Iniciar el emulador local

```bash
docker compose up -d localstack
```

Usa únicamente la imagen y la configuración de autorización de LocalStack aprobadas para el curso.

### Pruebas sin conexión

```bash
./.venv/bin/python -m pytest -m "not integracion" -q | tee evidencias/ejecuciones/YYYY-MM-DD_offline-tests.log
```

### Pruebas de integración con activación explícita

Primero obtén la aprobación del equipo docente y prepara el emulador aprobado; luego
exporta las variables de activación solo para esa terminal:

```bash
FENIX_CATEDRA_APPROVED=1 FENIX_RUN_LOCALSTACK=1 \
  ./.venv/bin/python -m pytest -m integracion -q \
  | tee evidencias/ejecuciones/YYYY-MM-DD_F01-integration.log
```

No escribas estas variables en un archivo que se vaya a confirmar.

### Inspección de cola y DLQ

```bash
./.venv/bin/python scripts/check_dlq.py | tee evidencias/ejecuciones/YYYY-MM-DD_F08-dlq-inspection.log
```

El script es de solo lectura. `--peek` lee un mensaje de la DLQ con
`VisibilityTimeout=0` y nunca lo elimina; solo imprime metadatos seguros del
mensaje, como la longitud del cuerpo y el número de recepciones, nunca el cuerpo
ni el ID del mensaje.

### Inspección de recursos

```bash
./.venv/bin/python scripts/inspect_resources.py | tee evidencias/ejecuciones/YYYY-MM-DD_F01-resource-inspection.log
```

El script es de solo lectura y compara el inventario con las etiquetas de
pertenencia de S3, EC2 y los grupos de seguridad.

### Redactar antes de confirmar los cambios

1. Abre el registro guardado o la captura de pantalla.
2. Redacta los secretos, tokens, ID de chat, identificadores de recepción y datos personales con
   `<redacted>`.
3. Guarda la copia redactada en el directorio correcto.
4. Ejecuta `git status` e inspecciona los cambios preparados.
5. Confirma únicamente evidencias redactadas.

## Convención de nombres

Usa el mismo nombre base para un escenario en todos los formatos.

| Artefacto | Patrón | Ejemplo |
|---|---|---|
| Registro de comando | `YYYY-MM-DD_Fxx_short-name.log` | `2026-11-21_F01-queue-setup.log` |
| Captura de pantalla | `YYYY-MM-DD_Fxx_short-name.png` | `2026-11-21_F01-queue-setup.png` |
| Evidencia de Telegram | `YYYY-MM-DD_F02_telegram-ok.png` | `2026-11-21_F02_telegram-ok.png` |

Usa palabras en minúscula separadas por guiones. Incluye el código F cuando el
artefacto corresponda a una fila de la matriz; usa `offline-tests` o `cleanup`
cuando corresponda a varias.

## Documentos relacionados

- [Matriz de verificación](matriz-verificacion.md)
- [Plantilla de evidencias por rol](roles/PLANTILLA.md)
- [Guía de roles](roles/README.md)
