# Verification and integration status

Current implementation: F0–F3 against a synthetic backend, with live Telegram and Copilot checks. The [shared contract](shared-system-contract.md) v2.1.1 is authoritative; see [PRD 2](prd-2-interaction.md) for full system acceptance and [PRD 1](prd-1-backend.md) for backend responsibilities. This record consolidates milestone notes; it does not certify real-backend integration.

## Status and outstanding gates

| Area | Verified boundary | Outstanding |
| --- | --- | --- |
| F0 dashboard, fixtures and validation | Local three-screen preview, consistent sources, nullable receipts, filters, polling, reset/replay | Authorized hosted deployment; Docker build/run (Linux daemon unavailable at verification) |
| F1 dashboard decisions | All review modes, exact overrides, sequencing, conflicts, uncertain responses and restart against simulator | Real backend and trusted live identity |
| F2 Hermes / Telegram | Native pinned SDK tests and actual authorized Telegram journeys against simulator | Real-backend handshake; production transport reliability |
| F3 interpretation | Actual Copilot proposals, strict validation, explicit confirmation and measured corpus | Real-backend pipeline visibility and acceptance |

No real extraction, general participant-document parsing, full dataset evaluation, private answer keys, production grounding accuracy or F4 completion is claimed. The shared adapter boundary exists; the real backend's authentication/actor assertion must be coordinated and tested rather than assuming the simulator's `X-Telegram-Actor` mechanism is supported.

## Acceptance requirements retained

These requirements remain enforced by the implementation/tests; the authoritative contract AC-01–AC-19 also includes wider integration gates.

- **Display:** latest-run DEMO statistics distinguish machine and operational outcomes; null assessment is not OK. Filters reach the API. Settled BL comparisons retain all seven fields, raw/normalized values, evidence, provenance and run-scoped history. Unknown values never become zero or match. Known mismatches stay visible during review; completed mismatch requires correction.
- **Fixtures:** processing/null classification, match, mismatch, non-comparison, candidate/document-role/value reviews, external blocks before/after acknowledgment, human resolution, sequential reviews, failures before assessment/after acceptance, superseded reviews and empty/populated statistics. Exact synthetic source bytes, hashes, code-point evidence ranges, field labels and values are audited.
- **Review:** CHOICE retains evidence, explicit target role and NONE_OF_THESE. VALUE_INPUT has deterministic parsing, side/field/unit guidance and canonical preview. Grounding rejection leaves the review open; override confirmation binds the exact review/run/field/side/value. Edits, cancel, reload and target changes invalidate confirmation. Human overrides remain ungrounded with lineage.
- **Transitions:** 202 acceptance is distinct from completion; pending work persists before acknowledgment. Polling shows updating results, subsequent reviews or retained failure. Canonical field and SI-before-BL ordering, review budgets and one-open-review invariants hold. ACKNOWLEDGE/cannot-tell/escape finish blocked externally, never verified. Human decisions never rewrite the frozen assessment.
- **Errors/concurrency:** strict shapes, IDs, actor, scope, run, action, option and confirmation are validated. Invalid/stale/conflicting actions cannot enqueue work. First acceptance wins; old jobs cannot update new runs. Uncertain responses trigger refetch, never automatic decision resend. Drafts remain bound to their review/run.
- **Telegram:** one Hermes inbound consumer, dedicated restricted profile, trusted sender/chat allowlist and no generic tool fallthrough. Persisted explicit reply/callback mappings and exact proposals survive restart. A single notifier enforces spacing, bounded retries and selectable large backlogs; digest delivery does not mark reviews notified. Operator failures and correction notices are distinct. Read-only details/link controls cannot submit decisions or reuse stale targets.
- **Interpretation:** deterministic paths work without a provider. Minimal explicitly mapped context goes through Hermes's explicit Copilot route, without tools or silent fallback. Strict structured output cannot change identity, target or approval. Inference rechecks the current run/review. Ambiguous, wrong-side, multiple-value, approximate and malicious replies clarify or fall back; every interpreted proposal requires confirmation.
- **UI:** keyboard labels/focus, responsive layout, reduced motion, visible errors and stale-data handling. The case workspace prioritizes unresolved/human-applied values; routine matches remain expandable. Progress reflects recorded events rather than invented activity. Telegram messages lead with the action, with details separately available.

## Recorded automated evidence

The following are recorded runs, not claims that the cleanup reran every integration check:

- Latest conversational-bot checkpoint: `npm run check` passed **67 tests**, TypeScript and Vite build. Added read-only detail/link, pending-confirmation and stale-run assertions. Existing scope, grounding, sequencing, duplicate, uncertainty and recovery assertions remain.
- Affected browser suite: `npm run test:browser -- tests/browser/f2.spec.ts` passed **2/2**, using actual simulator HTTP/dashboard with explicit Telegram/model doubles.
- Earlier complete F2 browser run: **23/23**, including F0/F1 regressions, 375/768/1024/1440 px checks and 15 axe audits. These audits are not a full accessibility certification. Dashboard refinement added its own responsive/filter/progress checks under `tests/browser/`; its separate design note did not record an additional full-suite count.
- Native `tests/hermes_plugin_test.py`: actual pinned Hermes PluginManager and PTB dispatch; mocked Telegram HTTP. Covers sender/reply/callback identity, SQLite dedup/pairing, button/document delivery, restricted fallback, pending updates and restart recovery. Also checks bridge ownership transfer when an abandoned application still reports running.
- `tests/f2_setup_test.py`: hidden-prompt configuration, explicit recipient approval, Node env-file parsing and no overwrite, with synthetic credentials. `tests/hermes_interpretation_test.py`: explicit Copilot/model routing, bounded tool-free requests and invalid-context rejection with a provider double.
- Source/contract/API tests cover nullable receipts, malformed/omitted receipt rejection, synthetic layout equivalence, evidence grounding context, exact overrides, DEMO/EVAL isolation, auth denial, rate limits, stale jobs, acceptance persistence and fault recovery.

Vite reports upstream Zod PURE-comment warnings; Playwright may report NO_COLOR/FORCE_COLOR configuration warnings. These were not suppressed. A historical F1 ephemeral-port fetch failure passed on rerun. Earlier trace-file races were resolved by running browser suites sequentially, not deleting assertions.

## Actual Copilot evaluation

[Retained report](interpretation-evaluation.json): **18/18 expected outcomes**, 10 actual Copilot `gpt-4.1` calls and 8 deterministic guard clarifications. Seven proposals and eleven total clarifications (three model-generated), zero unsafe proposals and zero decision submissions. Median model latency 2600.5 ms, maximum 5797 ms. This small authored corpus does not establish general accuracy.

The initial run passed 17/18: “twenty-ish tonnes” produced an incorrectly precise proposal, never submitted. A deterministic approximation guard fixed the case; the same expectations then passed. The original report remains available in Git history at `d60687d:docs/F3-evaluation-initial.json`. Reproduce the corpus through the command in [setup](setup.md); it uses provider requests but never submits decisions.

## Live evidence, 19–20 September 2026

Pinned Hermes `44945d224c2ccd6e0a55f16223c7ab0dd39331bf` (0.21.3), actual authorized private Telegram chat, shared simulator and dashboard:

- Two SI-before-BL reviews completed with human DOCUMENT_CONFIRMED values, operational OK and frozen NEEDS_REVIEW. Old confirmations were rejected.
- Unsupported 23000 triggered rejection; cancelled/changed to 22000, rejected the old override, restarted with the new override pending and accepted it once. Result retained MANUAL_OVERRIDE, ungrounded, MISMATCH and CORRECTION_REQUIRED.
- Evidenced candidate and explicit BL document assignment completed; acknowledgment and None of these remained BLOCKED_EXTERNAL.
- Accept-then-lose-response refetched without resubmission; simulated resumption failure retained exactly one accepted decision and produced an operator notice. Reprocessed-run buttons were rejected without mutating the new open review.
- `/pause` persisted across restart. Large backlogs stayed selectable instead of automatically flooding reviews/documents. `/reviews` resumed the queue.
- Offline active reply produced a preview after restart; an old-run reply was rejected. An offline confirmation recovered with exactly one TELEGRAM acceptance and unchanged machine assessment.
- Actual Copilot interpreted spelled-out 21707 kg into a preview; review remained open until confirmation, then 202 → operational OK. “Use the second option” proposed 22000, then confirmed to MISMATCH/correction required. The model did not establish grounding.
- Conversational refresh was checked live: subject-based queue, action-first review, separate evidence, local dashboard guidance, unmapped-reply recovery, preview and cancel without a submitted decision. Screenshot inspected for spacing/button readability. Existing historical messages retain old wording.

The live loop found and fixed a leaked message ID that made outcomes appear already delivered; explicit binding projection and a narrow legacy migration prevent recurrence. Telegram timeouts also exposed bridge ownership during Hermes application replacement; the replacement now releases the old bridge and denies old-generation updates. These fixes do not guarantee external connectivity. Normal captured dashboard warning/error logs were empty; deliberate failure scenarios retain their expected HTTP errors.

## Reliability and storage limits

- Local simulator and routing stores are single-process atomic-replace JSON, with SQLite WAL for plugin-received updates. This is not production multi-instance coordination or a power-loss durability guarantee. Keep ignored state and WAL files across restarts.
- The dedicated plugin preserves pending updates on cold start/reconnect/conflict recovery; it does not modify general Hermes. Only long polling is verified. Telegram retains unreceived updates for at most 24 hours ([Bot API](https://core.telegram.org/bots/api#getting-updates)). A crash between polling acknowledgment and SQLite receipt can still lose an update.
- A crash after outbound send but before mapping persistence may duplicate a notification. Backend first-writer-wins prevents repeated decisions. A crash before inbound routing finishes may require a fresh explicit action; proposals never migrate to another review.
- Individual delivery/marker attempts stop after five failures; source documents after three, with bounded backoff. More than three backlogged cases remain selectable instead of automatically draining. No exactly-once transport guarantee is claimed.
- Optional Nous auxiliary-credential startup warnings do not mean Copilot is used implicitly: shipping inference explicitly selects Copilot. Credentials remain in ignored local files. Subscription availability/limits apply.
- Phone usability, long-duration outages and live competing-poller recovery remain unverified. Container execution, hosted deployment and real-backend gates remain open.

## Participant reference and receipt-time adoption

The [participant problem statement](https://drive.google.com/file/d/1BV6-ljccjmqZm4MVmwg3O89mUuEJkyze/view) and [static participant bundle](https://drive.google.com/file/d/1K5WH580YwXHfmSpyfw-4ju0SnqD1gZOP/view) were reviewed for structure only. No organizer-only material, private answers or Docker distribution was inspected. The ignored `.local/reference/` archive is not publicly served or included in the container build.

The recorded inventory has 520 emails with five keys (`email_id`, `from`, `subject`, `body`, `attachments`) and no receipt timestamp; 250 attachments comprise 192 TXT, 28 PDF, 22 XLSX and 8 DOCX. Only representative TXT layouts informed the synthetic fixtures: multiline party addresses, alternate field labels, equipment expressions and explicit weight conventions. Rich-format parsing is not verified. Names, correspondence and outcomes are independently authored.

`sample_submission.json` contains GENERAL/OK format placeholders, not ground truth. No production code derives fixture outcomes from it. No-attachment draft intent remains explicitly unresolved under the existing BL_COMPARISON / missing_attachment / BLOCKED_EXTERNAL baseline with seven non-comparable fields, not an invented category or skipped comparison. Real intent mapping needs participant clarification and coordinated review.

Contract v2.1.1 supersedes the old receipt-time blocker. `shared/participant-mapping.ts` maps absent receipt to required `received_at: null`, validates supplied timestamps, preserves body/attachment references and produces a valid initial processing Case. It does not classify or parse participant documents. Receipt absence alone creates no review/failure. Replay preserves receipt/creation metadata while advancing run time; ingestion, file and quoted-correspondence times never substitute for receipt time. No provisional schema is retained.

## Reproduce and maintain

Follow [setup](setup.md). Application checks: `npm run check`; browser checks: `npm run test:browser` with the preview running. Run only one browser suite per artifact directory. Native checks:

```powershell
python tests/f2_setup_test.py
python tests/hermes_interpretation_test.py
$env:PYTHONPATH="$PWD/.local/f2-python;$env:LOCALAPPDATA/hermes/hermes-agent"
& "$env:LOCALAPPDATA/hermes/hermes-agent/venv/Scripts/python.exe" tests/hermes_plugin_test.py
```

Generated `dist/`, `test-results/` and `playwright-report/` can be rebuilt; they are ignored. `.local/` contains credentials, demo/routing state and reference material and must not be deleted as generic cleanup. Prior milestone notes remain in Git history (for example, `git show d60687d:docs/F2-verification.md`). Maintain these two current guides rather than adding a separate document for each implementation turn.
