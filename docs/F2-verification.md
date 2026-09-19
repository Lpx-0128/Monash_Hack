# F2 verification — simulator application and native plugin tests

Date: 19 September 2026. Branch: `feat/prd-2-interaction-frontend`. F1 checkpoint `a2be220` preserved. Canonical Shared Contract v2.1.1 and PRDs unchanged. No main merge or F3 work.

## Verification levels

| Level | Result |
|---|---|
| Application logic + real simulator HTTP API | Verified by automated tests; Telegram transport double explicitly used |
| Hermes native plugin registration + Telegram SDK | Verified against installed commit `44945d224c2ccd6e0a55f16223c7ab0dd39331bf`, package version 0.21.3; Telegram network mocked |
| Restart and recovery | Application state reopened; native PTB gateway application recreated; queued update replay and duplicate suppression verified; simulator restart covered by retained F1 tests |
| Live Hermes gateway + Telegram chat | **Verified against simulator, 19–20 September**: authorized private chat, source delivery, sequential grounded decisions, override cancel/change, choices, external blocks, uncertain-response recovery, stale actions and pending-confirmation restart. Offline replies and confirmation recovery also verified after the scoped polling adjustment below. |
| Real backend | **Outstanding**: no backend URL/scoped credentials supplied; extraction/grounding accuracy not evaluated |
| Hosted deployment / container execution | Prior external gates remain outstanding |

Live simulator verification is complete for the journeys listed below; this is not real-backend integration completion. The [setup guide](F2-setup.md) supplies hidden-token setup and local ID approval without asking for secrets in chat.

## Live verification, 19–20 September 2026

Used the isolated Codex in-app Telegram browser, the authorized private test bot, pinned Hermes gateway, application service, and shared simulator at `http://localhost:5176`. No participant data or unrelated chats were used. All decisions below were made through actual Telegram message replies/buttons.

- `demo_both-sides`: replied 21707 to the SI review, confirmed, observed dashboard PROCESSING, received the subsequent BL review, then replied/confirmed 21707. Both values became DOCUMENT_CONFIRMED; operational OK and frozen machine NEEDS_REVIEW. Reusing the old confirmation was rejected.
- `demo_field-input`: 23000 reached ordinary preview then grounding rejection. Cancelled its override, proposed 22000, and verified the old override button was rejected. Restarted both dedicated Hermes gateway and application with the new exact override pending; the original button successfully applied 22000 once. Dashboard and Telegram report MANUAL_OVERRIDE, ungrounded, MISMATCH and CORRECTION_REQUIRED.
- `demo_candidate-choice`: selected the evidenced 21707 candidate; completed with operational OK. `demo_document-choice`: assigned the explicitly requested BL role; completed with operational OK.
- `demo_blocked-open`: acknowledged external action; review closed while workflow remained BLOCKED_EXTERNAL. `demo_unsupported-candidate`: selected None of these; remained BLOCKED_EXTERNAL with external follow-up.
- `demo_resume-failure`: armed the simulator's accept-then-lose-response fault and used the cannot-tell action. The application refetched, reported acceptance without retrying, then reported the simulator's FAILED resumption and operator notice. Persisted history contains exactly one accepted decision.
- Replayed `demo_grounded-input`, then clicked an old-run action. Telegram rejected it; the new run retained its OPEN review and no accepted decision. New synthetic source documents arrived with explicit simulation labels.
- `/pause` acknowledged and persisted an empty proactive subscription list. The backlog remained selectable throughout; no automatic backlog/file flood returned. Existing buttons remain usable, and `/reviews` resumes delivery.

The live loop exposed a defect missed by the prior API-result tests: spreading a delivery object into a binding leaked the original message ID into an outcome, making it look already sent. Bindings now explicitly copy identity fields only. A narrow migration recovers affected unsent legacy outcomes; real delivery and no-repeat-after-restart assertions cover the fix. The recovery emitted one current outcome per previously affected review, including two historical reviews for the sequential case. The dashboard's demo wording also now accurately identifies shared Telegram reset scope.

Final checks: `npm run check` passed **60 tests**, TypeScript and production build. The affected F2 browser regression passed **1/1** (real simulator API with labelled transport double), in addition to the live browser journeys above. A read-only assertion script validated all **23 persisted live cases**, exact override value/channel, immutable machine outcomes, single acceptance after response loss, stale-run isolation, and paused subscriptions. Dashboard console warning/error collection was empty. Dashboard screenshot inspected. Build reports third-party Zod PURE-comment warnings; no app runtime errors were suppressed. Hermes logs' unclean-exit warning is expected from the deliberate restart test; missing Nous auxiliary credentials do not affect this deterministic, non-LLM flow.

## Offline queue preservation — 20 September 2026

The dedicated shipping plugin now wraps only its adapter instance's pinned `_start_polling_once` entry point, forcing `drop_pending_updates=False` for cold starts, reconnects and conflict recovery. No installed Hermes files, general profiles, tokens, allowlists or independent pollers were changed. The launcher still enforces the tested commit. The wrapper checks the expected method signature and is idempotent across application rebuilds. This integration supports long polling only; setup rejects webhook configuration rather than silently bypassing the verified policy.

Live checks used the actual authorized Telegram chat and simulator:

1. Stopped the dedicated gateway, then sent 21707 as a reply to the active `demo_grounded-input` review and another reply to its old-run review.
2. Cold-started the adjusted gateway. The active reply produced one canonical preview; the stale reply was rejected. Persisted backend state remained AWAITING_HUMAN / OPEN with no current-run accepted decision.
3. Stopped the gateway again and clicked the preview's Confirm value while offline. After restart, the callback was received and accepted. Dashboard showed COMPLETED, human DOCUMENT_CONFIRMED, with the frozen NEEDS_REVIEW assessment intact.
4. Asserted exactly one current-run DECISION_RECEIVED event, TELEGRAM provenance, all three recovered SQLite updates marked done, and proactive subscriptions still paused.

Native plugin tests passed for cold/reconnect/conflict drop requests being changed to preserve, argument/return forwarding, wrapper idempotence, unsupported interface/webhook guards, actual PTB dispatch, duplicate update suppression and received-queue recovery. `python tests/f2_setup_test.py` also passed. Live startup logs confirmed the preservation policy ran and Telegram connected after both restarts. No live competing poller was deliberately started; conflict-policy coverage is automated.

This fixes deliberate queue disposal on startup, not all possible message loss. Telegram retains unreceived updates for no longer than 24 hours ([official Bot API](https://core.telegram.org/bots/api#getting-updates)). A crash after the Telegram polling layer acknowledges an update but before the plugin's SQLite receipt remains a transport crash window. Existing backend first-writer-wins checks prevent repeated application. If another poller uses the same token, stop that process; recovery will preserve pending updates instead of discarding them to force takeover. Real-backend integration remains outstanding.

## Live backlog finding and correction

The first authorized live startup sent 14 case notices and 21 source documents from the seeded backlog. Delivery was deduplicated but still far too noisy. The notifier was stopped; application routing and backend decisions were preserved. Large backlogs now stay in a selectable digest until a human chooses a case. `/pause` durably disables proactive delivery; `/reviews` explicitly reopens the queue. Tests verify no automatic review/file flood after a minute or restart, selected document retry, stale digest buttons, operator-only failure visibility, and pause persistence. The corrected live interaction was subsequently exercised as recorded above; proactive notifications are now paused. The original rate-only behavior is superseded by this correction.

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

- The dedicated profile overrides the pinned Hermes cold-start/conflict discard behavior and live offline reply/callback recovery passed. The unmodified general Hermes profile is unaffected. Telegram's retention limit and the acknowledge-before-SQLite crash window still apply; no exactly-once transport guarantee is claimed.
- Notifications can duplicate after a crash between external send and local mapping persistence. Decisions cannot be reapplied because current-run backend acceptance remains first-writer-wins. A crash before an inbound action finishes routing may require a fresh explicit human action; it never transfers a proposal to another review.
- Individual delivery/marker attempts stop after five failures, source documents after three, with bounded backoff and a dashboard fallback. No production multi-process database or power-loss durability guarantee is claimed. Application JSON and simulator JSON are single-process atomic-replace files; plugin inbound storage uses SQLite WAL.
- The restricted profile intentionally intercepts generic commands; `/reset` does not run Hermes's general agent or erase application records. Natural-language interpretation/model submissions are absent, as required for F2.
- Local setup/configure has a hidden prompt and explicit recipient selection. Actual gateway startup, authorized chat delivery, live restart and queued replies/callbacks during gateway downtime are verified above. Phone usability, long-duration outages and live competing-poller recovery remain unverified.
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
