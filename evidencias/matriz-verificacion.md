# Verification matrix F01-F16

This matrix records the real LocalStack and offline runs captured on 2026-11-21
in this checkout. Do not add a result that was not produced by a command or test
run. The responsible-person column remains `[PENDING]` until the course role
assignment is confirmed.

> **Real Telegram evidence is captured.** Video and individual role evidence
> remain pending. F02 and F14 still use a mocked Telegram transport in their
> automated tests; the live send is recorded separately in
> `telegram/2026-11-21T060138Z_a9b1da_F02_telegram-evidence.json`.

## How to complete or refresh a row

1. Run the listed pytest test or command from the repository root.
2. Save the sanitized output under `ejecuciones/` and any screenshot under
   `capturas/`.
3. Replace the observed result only when a newer run supersedes this one.
4. Assign the responsible person only after the course role assignment exists.
5. Keep the status `PASS`, `FAIL`, or `PENDING` aligned with the captured log.

## Matrix

| ID | Date | Scenario | Command / pytest test | Expected | Observed | Evidence file | Responsible | Status |
|---|---|---|---|---|---|---|---|---|
| F01 | 2026-11-21 | Run queue and demo setup twice for a unique `it-*` group. | `test_localstack_integration.py::test_f01_queue_and_demo_setup_are_idempotent` | One owned resource set; work queue targets the DLQ; `maxReceiveCount=3`; no nested DLQ redrive policy. | PASS: repeated setup reused the same resources; queue redrive verified. | `ejecuciones/2026-11-21_final-verification.log` | `[PENDING]` | PASS |
| F02 | 2026-11-21 | Signed `evt-node-001` repairs `node-01`; mocked Telegram and real ACK. | `test_localstack_integration.py::test_f02_verified_ec2_repair_durable_ledger_mocked_telegram_and_real_ack` | EC2 `running` verified; ledger complete; mocked Telegram success; current SQS receipt acknowledged. | PASS: EC2 running, ledger complete, mocked Telegram accepted, real SQS ACK observed. Live Telegram confirmation captured in `telegram/2026-11-21T060138Z_a9b1da_F02_telegram-evidence.json`. | `ejecuciones/2026-11-21_integration-tests-verbose.log`; `telegram/2026-11-21T060138Z_a9b1da_F02_telegram-evidence.json` | `[PENDING]` | PASS |
| F03 | 2026-11-21 | Signed `bucket-01` event with missing `Owner` and an unrelated tag. | `test_localstack_integration.py::test_f03_bucket_repair_preserves_unrelated_tags` | Restore required tags and preserve unrelated tags. | PASS: required `Owner` restored; unrelated `Department` tag preserved. | `ejecuciones/2026-11-21_final-verification.log` | `[PENDING]` | PASS |
| F04 | 2026-11-21 | Synthetic body with missing, malformed, stale, or invalid signature. | `test_fenix.py::test_signature_failures_return_401_without_publishing` | HTTP 401 and no SQS publish. | PASS for missing, malformed, wrong, and stale signatures; no publish. | `ejecuciones/2026-11-21_offline-tests-verbose.log` | `[PENDING]` | PASS |
| F05 | 2026-11-21 | Same JSON value serialized to different raw bytes after signing; ambiguous headers. | `test_fenix.py::test_signature_authenticates_raw_bytes_and_rejects_ambiguous_headers` | HMAC fails; HTTP 401 and no publish. | PASS: raw-byte HMAC and ambiguous-header rejection verified. | `ejecuciones/2026-11-21_offline-tests-verbose.log` | `[PENDING]` | PASS |
| F06 | 2026-11-21 | Signed malformed JSON and signed JSON array. | `test_fenix.py::test_signed_invalid_json_is_400_and_signed_list_is_422` | HTTP 400 and 422 respectively; no publish. | PASS: signed malformed JSON returned 400; signed array returned 422. | `ejecuciones/2026-11-21_offline-tests-verbose.log` | `[PENDING]` | PASS |
| F07 | 2026-11-21 | Synthetic unknown alias and event with an extra key. | `test_fenix.py::test_bad_alias_and_extra_event_fields_return_422_without_publish` | HTTP 422; no cloud operation. | PASS: bad alias and extra fields returned 422; no cloud operation. | `ejecuciones/2026-11-21_offline-tests-verbose.log` | `[PENDING]` | PASS |
| F08 | 2026-11-21 | Corrupt synthetic message published directly to the work queue. | `test_localstack_integration.py::test_f08_corrupt_direct_sqs_message_reaches_real_dlq_without_stopping_worker` | Worker continues; original message reaches the real DLQ. | PASS: corrupt body reached the real DLQ; worker continued. | `ejecuciones/2026-11-21_final-verification.log` | `[PENDING]` | PASS |
| F09 | 2026-11-21 | Synthetic event with `simulate_failures=2`. | `test_scenarios.py::test_simulated_failures_persist_across_attempts_then_complete` | Persist attempts; visibility backoff; complete on the third execution. | PASS: attempts persisted and completion occurred on the third execution. | `ejecuciones/2026-11-21_offline-tests-verbose.log` | `[PENDING]` | PASS |
| F10 | 2026-11-21 | Synthetic event with `simulate_failures=5`. | `test_localstack_integration.py::test_f10_persistent_handler_failure_reaches_real_dlq_without_ack` | No repair or ACK; SQS moves the message to the real DLQ. | PASS: persistent failure reached the real DLQ without ACK or repair. | `ejecuciones/2026-11-21_final-verification.log` | `[PENDING]` | PASS |
| F11 | 2026-11-21 | Repeat a completed synthetic event after reloading its ledger. | `test_scenarios.py::test_duplicate_after_restart_does_not_repeat_completed_stages` | No repeated repair or notification. | PASS: completed stages were not repeated after restart. | `ejecuciones/2026-11-21_offline-tests-verbose.log` | `[PENDING]` | PASS |
| F12 | 2026-11-21 | Synthetic repair followed by notification/checkpoint failure. | `test_scenarios.py::test_restart_after_repair_resumes_notification_only`; `test_scenarios.py::test_repair_converges_when_ledger_checkpoint_save_fails` | Resume notification only; if the repair checkpoint fails, re-query and converge without repeating EC2 start. | PASS: notification resumed only; checkpoint failure converged without repeating EC2 start. | `ejecuciones/2026-11-21_offline-tests-verbose.log` | `[PENDING]` | PASS |
| F13 | 2026-11-21 | Valid synthetic event with a missing local queue; mocked SQS failure. | `test_localstack_integration.py::test_f13_missing_local_queue_returns_503_without_acceptance`; `test_fenix.py::test_sqs_failure_returns_503_without_false_acceptance` | HTTP 503; no false acceptance. | PASS: missing queue returned 503; mocked SQS failure returned 503 without acceptance. | `ejecuciones/2026-11-21_final-verification.log` | `[PENDING]` | PASS |
| F14 | 2026-11-21 | Mocked Telegram 429, timeout, and 5xx with `Retry-After`. | `test_scenarios.py::test_f14_rate_limit_and_timeout_resume_notification_without_repair_repeat`; `test_scenarios.py::test_telegram_5xx_retry_after_is_propagated_and_bounded` | Retry notification only; bounded wait; do not repeat confirmed repair. | PASS with mocked Telegram retry behavior; live Telegram confirmation captured separately in `telegram/2026-11-21T060138Z_a9b1da_F02_telegram-evidence.json`. | `ejecuciones/2026-11-21_offline-tests-verbose.log`; `telegram/2026-11-21T060138Z_a9b1da_F02_telegram-evidence.json` | `[PENDING]` | PASS |
| F15 | 2026-11-21 | Same synthetic event ID with different content. | `test_scenarios.py::test_conflicting_event_id_preserves_first_content_and_never_repairs_again` | Preserve original ledger; record conflict; do not repair conflicting event. | PASS: first content preserved; conflict recorded; no conflicting repair. | `ejecuciones/2026-11-21_offline-tests-verbose.log` | `[PENDING]` | PASS |
| F16 | 2026-11-21 | Synthetic JSON log messages with small rotation threshold. | `test_logging.py::test_small_threshold_rotates_to_readable_gzip_json_without_secrets` | Readable gzip JSONL, UTC context, redacted secrets. | PASS: gzip JSONL readable; UTC context; secrets redacted. | `ejecuciones/2026-11-21_offline-tests-verbose.log` | `[PENDING]` | PASS |

## Status note

The current captured run is `ejecuciones/2026-11-21_all-tests.log` with 78
passed; the verbose split is 72 offline plus 6 integration passes.
`ejecuciones/2026-11-21_final-verification.log` is an older snapshot and predates
the live Telegram send. The manual CLI demo is in
`ejecuciones/2026-11-21_manual-demo.log`, and queue/resource inspection logs are
in `ejecuciones/2026-11-21_check-dlq.log` and
`ejecuciones/2026-11-21_inspect-resources.log`.

A real Telegram message was sent and confirmed on 2026-11-21T06:01:38Z; the
redacted capture is `telegram/2026-11-21T060138Z_a9b1da_F02_telegram-evidence.json`.
F02 and F14 tests still use a mocked Telegram transport. Video, individual role
evidence, course-defense artifacts, and responsible assignments remain pending.
Fill the remaining fields only from captured, sanitized artifacts listed in
[README.md](README.md).
