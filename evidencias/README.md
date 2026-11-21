# Evidence index

This directory holds the course evidence for the Fénix local infrastructure
self-repair project. Every file must come from a real command, test run, cloud
inspection, Telegram confirmation, or recording performed by the team.

> **Never fabricate evidence.** A placeholder stays as a placeholder until the
> real command runs. Do not copy expected output into an "Observed" column, do
> not invent screenshots, and do not create a fake Telegram success or video
> link. Course reviewers must be able to reproduce the command and compare the
> observed result.

## Privacy and redaction checklist

Before committing any evidence, confirm all of the following.

- [ ] No `.env`, `.env.example` values, or local environment dumps are included.
- [ ] No bot tokens, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, webhook secrets,
      LocalStack authorization tokens, or AWS secret keys appear.
- [ ] No AWS access key IDs, session tokens, or real account identifiers appear.
- [ ] No private URLs, private chat links, email addresses, phone numbers, or
      raw personal data appear.
- [ ] Secret-like fields are replaced with `<redacted>`, including tokens,
      passwords, credentials, authorization headers, signatures, and receipt
      handles.
- [ ] `git status` and `git diff --cached` were inspected before committing.
- [ ] Screenshots and logs were opened after redaction to confirm nothing leaked.

## Directory layout

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

## Required artifacts

| Artifact | Location | Requirement |
|---|---|---|
| Team and individual evidence | `roles/I1/` … `roles/I6/` | One folder per assigned role, based on `roles/PLANTILLA.md`. |
| F01-F16 integration matrix | `matriz-verificacion.md` | Every row has a real command or pytest reference and observed result before submission. |
| Real Telegram send evidence | `telegram/` | Redacted screenshot or JSON showing `ok: true`, plus date and command. No token or chat ID. |
| Video and timestamps | `video/` | Real recording link and topic timestamps. No placeholder URL presented as final. |
| AI-assistance declaration | Course submission document | State where AI assistance was used and what the team reviewed. |
| Cleanup evidence | `ejecuciones/` or `capturas/` | Show `docker compose down` or equivalent approved cleanup and final state. |

## How to capture evidence

Run all commands from the repository root and save output with `tee` so the log
is both visible and stored.

### Start the local emulator

```bash
docker compose up -d localstack
```

Only use the course-approved LocalStack image and authorization configuration.

### Offline tests

```bash
./.venv/bin/python -m pytest -m "not integracion" -q | tee evidencias/ejecuciones/YYYY-MM-DD_offline-tests.log
```

### Opt-in integration tests

Obtain course approval first, prepare the approved emulator, then export the
opt-in variables for that shell only:

```bash
FENIX_CATEDRA_APPROVED=1 FENIX_RUN_LOCALSTACK=1 \
  ./.venv/bin/python -m pytest -m integracion -q \
  | tee evidencias/ejecuciones/YYYY-MM-DD_F01-integration.log
```

Do not write these variables into a committed file.

### Queue and DLQ inspection

```bash
./.venv/bin/python scripts/check_dlq.py | tee evidencias/ejecuciones/YYYY-MM-DD_F08-dlq-inspection.log
```

The script is read-only. `--peek` reads one DLQ message with
`VisibilityTimeout=0` and never deletes it; it prints only safe message metadata
such as body length and receive count, never the message body or message ID.

### Resource inspection

```bash
./.venv/bin/python scripts/inspect_resources.py | tee evidencias/ejecuciones/YYYY-MM-DD_F01-resource-inspection.log
```

The script is read-only and compares the inventory with S3, EC2, and security
group ownership tags.

### Sanitize before committing

1. Open the saved log or screenshot.
2. Redact secrets, tokens, chat IDs, receipt handles, and personal data with
   `<redacted>`.
3. Save the sanitized copy under the correct directory.
4. Run `git status` and inspect the staged diff.
5. Commit only sanitized evidence.

## Naming convention

Use the same base name for a scenario across formats.

| Artifact | Pattern | Example |
|---|---|---|
| Command log | `YYYY-MM-DD_Fxx_short-name.log` | `2026-11-21_F01-queue-setup.log` |
| Screenshot | `YYYY-MM-DD_Fxx_short-name.png` | `2026-11-21_F01-queue-setup.png` |
| Telegram evidence | `YYYY-MM-DD_F02_telegram-ok.png` | `2026-11-21_F02_telegram-ok.png` |

Use lowercase words separated by hyphens. Include the F-code when the artifact
maps to one matrix row; use `offline-tests` or `cleanup` when it maps to several.

## Related documents

- [Verification matrix](matriz-verificacion.md)
- [Role evidence template](roles/PLANTILLA.md)
- [Role guide](roles/README.md)
