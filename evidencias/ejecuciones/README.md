# Execution logs

This directory stores sanitized command and pytest output captured with `tee`.
A log is evidence only when it comes from a real run.

## Naming convention

```text
YYYY-MM-DD_Fxx_short-name.log
```

Examples:

- `2026-11-21_F01-queue-setup.log`
- `2026-11-21_offline-tests.log`
- `2026-11-21_cleanup.log`

Use the F-code when the log maps to one verification row. Use a neutral name
such as `offline-tests` when it covers several rows.

## Capture pattern

```bash
./.venv/bin/python -m pytest -m "not integracion" -q \
  | tee evidencias/ejecuciones/2026-11-21_offline-tests.log
```

```bash
./.venv/bin/python scripts/check_dlq.py \
  | tee evidencias/ejecuciones/2026-11-21_F08-dlq-inspection.log
```

Include the command line at the top of the log when the shell does not already
record it.

## Redaction before committing

- Remove `.env` contents and all environment dumps.
- Replace tokens, passwords, webhook secrets, authorization headers, signatures,
  receipt handles, chat IDs, and AWS secrets with `<redacted>`.
- Remove private URLs, personal email addresses, phone numbers, and raw personal
  data.
- Reopen the saved file after editing and search for `token`, `secret`,
  `password`, `credential`, `authorization`, `signature`, and `receipt`.
- Run `git status` and inspect the staged diff before committing.

Never commit a raw log because it "probably has nothing sensitive". Check it.
