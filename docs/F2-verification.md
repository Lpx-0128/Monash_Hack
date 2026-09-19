# F2 verification — simulator application and native plugin tests

Date: 19 September 2026. Branch: `feat/prd-2-interaction-frontend`. F1 checkpoint `a2be220` preserved. Canonical Shared Contract v2.1.1 and PRDs unchanged. No main merge or F3 work.

## Verification levels

| Level | Result |
|---|---|
| Application logic + real simulator HTTP API | Verified by automated tests; Telegram transport double explicitly used |
| Hermes native plugin registration + Telegram SDK | Verified against installed commit `44945d224c2ccd6e0a55f16223c7ab0dd39331bf`, package version 0.21.3; Telegram network mocked |
| Restart and recovery | Application state reopened; native PTB gateway application recreated; queued update replay and duplicate suppression verified; simulator restart covered by retained F1 tests |
| Live Hermes gateway + Telegram chat | **Partial**: gateway connected and initial outbound notices/documents reached the authorized chat. Full confirmed-decision handshake and live restart remain outstanding. See live finding below. |
| Real backend | **Outstanding**: no backend URL/scoped credentials supplied; extraction/grounding accuracy not evaluated |
| Hosted deployment / container execution | Prior external gates remain outstanding |

Do not describe this as live F2 completion. The user is new to Telegram bots; [setup guide](F2-setup.md) supplies hidden-token setup and local ID approval without asking for secrets in chat.

## Live backlog finding and correction

The first authorized live startup sent 14 case notices and 21 source documents from the seeded backlog. Delivery was deduplicated but still far too noisy. The notifier was stopped; application routing and backend decisions were preserved. Large backlogs now stay in a selectable digest until a human chooses a case. `/pause` durably disables proactive delivery; `/reviews` explicitly reopens the queue. Tests verify no automatic review/file flood after a minute or restart, selected document retry, stale digest buttons, operator-only failure visibility, and pause persistence. The service is resumed paused; the corrected live interaction still needs user exercise. The original rate-only behavior is superseded by this correction.

## Architecture and changes

- `hermes/shipping-review`: standalone Hermes plugin using the supported `register_platform_handler("telegram", factory)` extension. Native PTB handlers preserve authenticated sender/chat/message/reply/callback identity. Scoped `ship:` callbacks and a restricted dedicated-profile catch-all prevent general model/tool fallthrough. The plugin adds no inbound poller. Hermes already owns token-scoped gateway locking and polling.
- Plugin SQLite stores received update payloads/progress independently of Hermes memory. A loopback authenticated bridge sends via the gateway's actual `Application.bot`, returns message IDs and forwards received updates to the application. Unknown `/start` records local pairing IDs only; no case content or outbound message before designation.
- `interaction`: shared-schema REST client, serialized deterministic routing, shared F1 value parser, exact persisted ordinary/override proposals, authenticated confirmation evidence, source delivery, single notifier and PID ownership lock. Application confirmation state cannot be reset by Hermes conversation commands.
- Simulator: optional server-verified service credential + actor allowlist, TELEGRAM channel validation, contract notification endpoint, persistent shared DEMO namespace. Default F1 guest sessions remain isolated. This is a transport auth configuration, not a shared-contract wire change. Real backend authentication mapping still needs coordination.
- Dashboard: preserves design and review behavior; the F2 bootstrap changes only the simulation notice to explain the shared Telegram demo. Receipt-time semantics and machine/operational split are unchanged.

## Checks performed

- `npm run test`: 59 tests passed in the final complete application run; TypeScript and Vite build passed after correcting test-only optional-property annotations. Includes 47 F0/F1 regressions and 12 F2 tests (several contain multiple journeys).
- F2 API/application checks: explicit reply and canonical preview; grounded input; unsupported typed and candidate overrides; cancellation and changed proposal invalidation; document role and required escapes; two SI-before-BL reviews; stale/reprocessed messages; authenticated actor/chat binding; duplicate update/button and dashboard race; lost acceptance response; retained resumption failure; marker-only recovery after failed acknowledgment; document failure/retry; flood spacing and digest isolation; correction versus operator notices; EVAL, guessed ID, cross-case document and credential denial.
- `tests/hermes_plugin_test.py`: actual pinned `PluginManager` loads the plugin; actual PTB `Application.process_update` handles SDK Update objects. Asserts sender/chat/reply/callback metadata, no general-handler fallthrough, SQLite dedup, private pairing records, native button payloads, native document delivery and returned message IDs. Recreates the gateway application with the same SQLite store while the local application endpoint is unavailable, then verifies pending-update recovery and duplicate suppression. **Telegram HTTP is mocked; no live handshake claimed.**
- Browser F2 journey: real simulator HTTP API, routed/confirmed application action using a transport double, observed Processing then Completed, human document-confirmed value, immutable NEEDS_REVIEW machine result and operational OK. No page errors. Full-page screenshot inspected; established desktop layout retained.
- Final sequential `npm run test:browser`: **23/23 passed (2.4 minutes)**, including all 22 F0/F1 regressions and the new F2 dashboard journey. Existing responsive checks at 375/768/1024/1440px and 15 axe audits passed. No assertion weakening or warning suppression.
- `python tests/f2_setup_test.py`: hidden-prompt setup with synthetic credentials, explicit local recipient authorization, actual Node env-file parsing, and refusal to overwrite existing configuration passed. No real bot token was used.

## Findings addressed

Initial test failures exposed incorrect fixture names and a test helper selecting the first old review message; corrected the harness to target the actual new message without weakening stale-message assertions. Native SDK compatibility required its abstract `read_timeout` property on the test transport. Windows cleanup required explicitly closing a test SQLite connection (its transaction context manager does not close it).

One browser regression run reported missing trace/network files because a second Playwright invocation cleaned the same artifact directory concurrently. The journeys themselves were not reported as assertion failures. Subsequent full suite execution is sequential. No app errors or assertions were suppressed.

An existing footer incorrectly said no notifications run even for the new shared demo; F2 now uses an honest gateway-dependent notice. The notifier enforces both per-recipient spacing and a three-attempt burst cap; digest attempts are recorded before transport to avoid repeated flood attempts after an uncertain send.

## Sanitized outcome evidence

The test actor/chat `101/101` are invented transport identities, not an authorized real recipient. A grounded review follows `OPEN → 202 PROCESSING → COMPLETED`, with `resolution.channel=TELEGRAM`, human DOCUMENT_CONFIRMED BL weight 21707, and frozen machine NEEDS_REVIEW. Unsupported 23000 remains OPEN after rejection; a persisted callback bound to the exact proposal yields MANUAL_OVERRIDE with grounded=false and CORRECTION_REQUIRED. Competing dashboard/Telegram requests produce exactly one DECISION_RECEIVED history event. A failed notification marker retains its message ID and retries the marker without sending a second review.

## Limits

- Pinned Hermes cold-start polling passes `drop_pending_updates=True`; offline Telegram updates may be discarded **before plugin receipt**. The plugin cannot persist updates it never sees. Already received updates and application mappings are restart-tested. This upstream transport gap and actual gateway network reconnect remain live reliability checks, not a claim of exactly-once transport.
- Notifications can duplicate after a crash between external send and local mapping persistence. Decisions cannot be reapplied because current-run backend acceptance remains first-writer-wins. A crash before an inbound action finishes routing may require a fresh explicit human action; it never transfers a proposal to another review.
- Individual delivery/marker attempts stop after five failures, source documents after three, with bounded backoff and a dashboard fallback. No production multi-process database or power-loss durability guarantee is claimed. Application JSON and simulator JSON are single-process atomic-replace files; plugin inbound storage uses SQLite WAL.
- The restricted profile intentionally intercepts generic commands; `/reset` does not run Hermes's general agent or erase application records. Natural-language interpretation/model submissions are absent, as required for F2.
- Local setup/configure has a hidden prompt and explicit recipient selection. Actual BotFather credentials, full gateway startup/provider prerequisites, chat delivery, phone usability and live restart must be checked once the user finishes setup. Pinning and native-handler tests do not prove those live capabilities.
- The real-backend adapter must be exercised with its trusted actor assertion/authentication mechanism. No participant extraction, dataset evaluation, real shipping documents or private answer keys are involved.

## Reproduce

```powershell
npm run check
npm run test:browser
python tests/f2_setup_test.py
$env:PYTHONPATH="$PWD/.local/f2-python;$env:LOCALAPPDATA/hermes/hermes-agent"
& "$env:LOCALAPPDATA/hermes/hermes-agent/venv/Scripts/python.exe" tests/hermes_plugin_test.py
```

Install the local pinned optional dependencies first, as described in [F2 setup](F2-setup.md). Do not run two Playwright invocations concurrently against the same output directory.
