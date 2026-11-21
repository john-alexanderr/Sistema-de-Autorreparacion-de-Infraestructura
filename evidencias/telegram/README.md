# Telegram evidence

This directory is reserved for proof that a real Telegram notification was sent
by the Fénix flow. Mocked tests do not count as real Telegram evidence.

## Automated redacted capture

Set the following in the gitignored `.env` file (never commit it):

```text
NOTIFY_PROVIDER=telegram
TELEGRAM_BOT_TOKEN=<bot token>
TELEGRAM_CHAT_ID=<chat id>
```

Validate the configuration without sending:

```bash
./.venv/bin/python scripts/telegram_evidence.py --dry-run
```

Send one real message and write the sanitized evidence:

```bash
./.venv/bin/python scripts/telegram_evidence.py
```

The script uses the production `fenix.services.notifications.notify` adapter. It
writes a minimal JSON confirmation in this directory with the provider, status,
`"ok": true`, and UTC timestamp. Output is restricted to this repository
directory. The Telegram message ID, sent text, credentials, chat ID, and Bot API
URL are not stored or printed.

## Required evidence

The sanitized confirmation file is sufficient; do not attach a screenshot or raw
API response. Record only:

- The date of the real send.
- The command or flow that triggered it.
- The generic confirmation status that `ok: true`.

## Never include

- `TELEGRAM_BOT_TOKEN` or any bot token.
- `TELEGRAM_CHAT_ID` or any private chat identifier.
- The bot API URL containing the token.
- Telegram message IDs or message text/body.
- Private chat links, usernames, phone numbers, or personal data.
- Screenshots or response bodies that reveal message content or identifiers.

## Template

| Field | Value |
|---|---|
| Date | `[PENDING: YYYY-MM-DD]` |
| Trigger command or flow | `[PENDING]` |
| Evidence file | `[PENDING: relative path under evidencias/telegram/]` |
| Confirmation status | `[PENDING: sent; ok=true]` |
| Message ID or text recorded | `No` |
| Sanitized by | `[PENDING]` |

The script creates a timestamped JSON confirmation in this directory.
Placeholders stay until the real send happens; never add message IDs or content
to the evidence filename.
