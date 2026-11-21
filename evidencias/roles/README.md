# Role evidence guide

The course defines six roles, labeled I1 through I6. This repository does not
assign names, emails, or ownership to any role. Do not invent a person, a
sign-off, or a role assignment. Fill those fields only from the approved course
guide.

| Role | Module focus | Evidence focus |
|---|---|---|
| I1 Entradas y Excepciones | `receiver.py`, `events.py`, validation, and signature handling | Signed-input rejection and HTTP error evidence (F04-F07, F13). |
| I2 Mensajería e Inventario Cloud | `sqs.py`, `demo.py`, and settings | Queue/DLQ behavior, group-owned inventory, and reconciliation evidence (F01, F08, F10). |
| I3 Webhooks y Reparación | `receiver.py` and `remediation.py` | Webhook acceptance and verified EC2/S3 remediation (F02-F07). |
| I4 Observabilidad y Comunicación | `notifications.py` and `logging_json.py` | Telegram delivery/retry evidence and redacted rotating logs (F02, F14, F16). |
| I5 Integración y Worker | `worker.py`, `state.py`, and `sqs.py` | Durable processing, visibility retries, recovery, and acknowledgment (F08-F12). |
| I6 Pruebas y Diagnóstico | Test reports mapped to the verification matrix | Offline versus integration evidence for F01-F16. |

## Folder rules

1. Create `I1/` through `I6/` only when the course assigns the role. Empty
   folders for unassigned roles add noise and imply an assignment that does not
   exist.
2. Copy `PLANTILLA.md` into each assigned folder and rename it after the role,
   for example `I2/evidencia.md`.
3. Keep personal data minimal. A role label and an institutional identifier are
   enough; do not commit national IDs, addresses, phone numbers, or private
   emails unless the course explicitly requires them.
4. Each role keeps its own commands, observed results, screenshots, log paths,
   defense explanation, AI-assistance declaration, and sign-off.
5. Do not copy another role's evidence into your folder. Reference the shared
   artifact in `ejecuciones/` or `capturas/` and explain your part.

## Defense notes

Every role must be able to explain:

- Which module and verification rows the role owns.
- Which commands or tests were actually run and what they observed.
- Why the design is fail-closed or read-only where the assignment requires it.
- What AI assistance produced and what the role owner personally reviewed.
- Which evidence is offline-only and which required the approved emulator.

Use [PLANTILLA.md](PLANTILLA.md) as the starting point. Return to the
[evidence index](../README.md) for redaction and capture rules.
