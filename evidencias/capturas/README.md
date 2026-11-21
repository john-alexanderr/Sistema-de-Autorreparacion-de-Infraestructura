# Screenshots

This directory stores redacted screenshots that support the verification
matrix and role evidence.

## Naming convention

```text
YYYY-MM-DD_Fxx_short-name.png
```

Examples:

- `2026-11-21_F01-queue-attributes.png`
- `2026-11-21_F08-dlq-message.png`
- `2026-11-21_F02-ec2-running.png`

Use lowercase words separated by hyphens. Include the F-code when the image
maps to one row.

## Screenshot index

Keep a short index so a reviewer can find each artifact. Add entries only for
real screenshots.

| Date | F-code | What it shows | File | Sanitized |
|---|---|---|---|---|
| `[PENDING]` | `[PENDING]` | `[PENDING]` | `[PENDING]` | `[PENDING]` |

## Redaction checklist

- [ ] No `.env` window, terminal history, or environment dump is visible.
- [ ] No bot token, chat ID, webhook secret, AWS key, or LocalStack token.
- [ ] No receipt handle is visible.
- [ ] No private URL, email address, phone number, or personal data.
- [ ] Cropped or redacted with `<redacted>` where needed.
- [ ] The screenshot was reopened after editing to confirm nothing leaked.

Prefer a terminal screenshot with only the command and its sanitized output over
a full desktop capture.
