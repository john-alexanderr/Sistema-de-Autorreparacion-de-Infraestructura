# Guía de evidencias por rol

El curso define seis roles, identificados como I1 a I6. Este repositorio no
asigna nombres, correos electrónicos ni responsabilidades a ningún rol. No
inventes una persona, una aprobación ni una asignación de rol. Completa esos
campos únicamente a partir de la guía aprobada del curso.

| Rol | Enfoque del módulo | Enfoque de las evidencias |
|---|---|---|
| I1 Entradas y Excepciones | `receiver.py`, `events.py`, validación y gestión de firmas | Evidencia de rechazo de entradas firmadas y errores HTTP (F04-F07, F13). |
| I2 Mensajería e Inventario Cloud | `sqs.py`, `demo.py` y configuración | Comportamiento de la cola/DLQ, inventario propiedad del grupo y evidencias de conciliación (F01, F08, F10). |
| I3 Webhooks y Reparación | `receiver.py` y `remediation.py` | Aceptación de webhooks y remediación verificada de EC2/S3 (F02-F07). |
| I4 Observabilidad y Comunicación | `notifications.py` y `logging_json.py` | Evidencias de entrega y reintentos de Telegram, y registros rotativos redactados (F02, F14, F16). |
| I5 Integración y Worker | `worker.py`, `state.py` y `sqs.py` | Procesamiento durable, reintentos mediante cambios del tiempo de visibilidad en SQS, recuperación y confirmación (F08-F12). |
| I6 Pruebas y Diagnóstico | Informes de pruebas vinculados con la matriz de verificación | Evidencias sin conexión y de integración para F01-F16. |

## Reglas de carpetas

1. Crea `I1/` a `I6/` únicamente cuando el curso asigne el rol. Las carpetas
   vacías para roles sin asignar agregan ruido e implican una asignación que no
   existe.
2. Copia `PLANTILLA.md` en cada carpeta asignada y cambia el nombre del archivo
   según el rol; por ejemplo, `I2/evidencia.md`.
3. Limita al mínimo los datos personales. Basta con la etiqueta del rol y un
   identificador institucional; no confirmes documentos de identidad, domicilios,
   teléfonos ni correos privados, salvo que el curso los exija explícitamente.
4. Cada rol conserva sus propios comandos, resultados observados, capturas de
   pantalla, rutas de registros, explicación para la defensa, declaración de
   asistencia de IA y aprobación.
5. No copies en tu carpeta las evidencias de otro rol. Haz referencia al
   artefacto compartido en `ejecuciones/` o `capturas/` y explica tu aporte.

## Notas para la defensa

Cada rol debe poder explicar:

- Qué módulo y filas de verificación corresponden al rol.
- Qué comandos o pruebas se ejecutaron realmente y qué resultados se observaron.
- Por qué el diseño deniega por defecto ante fallos o funciona en modo de solo lectura cuando así lo exige la consigna.
- Qué produjo la asistencia de IA y qué revisó personalmente la persona responsable del rol.
- Qué evidencias son exclusivamente sin conexión y cuáles requirieron el emulador aprobado.

Usa [PLANTILLA.md](PLANTILLA.md) como punto de partida. Consulta el
[índice de evidencias](../README.md) para conocer las reglas de redacción y recopilación.
