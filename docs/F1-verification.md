# F1 verification — simulated backend

Branch: `feat/prd-2-interaction-frontend`. Date: 19 September 2026.

## Preserved baseline and authority

F0 was checkpointed in `d233253` before edits. `origin/main` canonical-document changes were reconciled in `046c061`; compared requirements differed only in links/formatting. Local document copies were also preserved under ignored `.local/pre-f1-documents/`. The canonical contract and both PRDs under docs/ remain unchanged by F1. Main was not modified and F2 was not started.

## Implemented

All three review modes submit through the shared API adapter. Typed values have deterministic canonical preview and ordinary confirmation. Grounding rejection leaves the review open; manual override requires the exact review/run/field/side/value tuple. Cancel, edits, new review/run and reload clear confirmation. Candidate values use the same grounding gate. Document-role choices explicitly target BL and rederive all fields from immutable synthetic source text.

The simulator accepts each decision once, closes the review, stores accepted work and history, then returns 202 PROCESSING. Four-second delayed work applies the operational result without rewriting machine assessment. Sequential field and SI-before-BL examples create the next review. Acknowledgments and escapes finish at BLOCKED_EXTERNAL. Known mismatches remain visible and completed mismatch retains CORRECTION_REQUIRED. Resumption failure retains accepted work and prior assessment.

Single-process demo sessions and pending work are atomically saved to `.local/simulator-state.json` before acceptance response. A process-restart test verifies pending work applies once after recovery. No database, multi-instance locking, power-loss durability or production reliability is claimed. The fault fixture models exhausted resumption retries; it is not a real parser failure.

## Checks performed

- `npm run check`: **47 tests passed**, TypeScript passed, production build passed. Contract/API tests cover every fixture, exact source hashes/locations, request shapes, types, targeting, option membership, unsupported grounding, each override binding dimension, closed/stale actions, first-writer wins, access denial, rate limiting, sequential reviews, escapes, mismatch roll-up, lost response, failure retention and restart recovery. F0 timestamp, statistics, reset/replay and source checks remain included.
- `npm run test:browser`: **22/22 browser tests passed** in the final full run (11 F0 regressions and 11 F1 journeys/layout checks). Four responsive widths (375, 768, 1024, 1440) are covered; 15 axe page/state audits report zero violations (not a full accessibility certification). Journeys exercise visible outcomes and HTTP responses; ordinary submission returns 202 and never auto-resubmits. Deliberate 409/422/403 and lost-network scenarios are expected errors, not suppressed failures.
- Manual in-app browser: entered grounded 21707, inspected canonical proposal, confirmed and observed processing then operational OK. Entered unsupported 22000, inspected the grounding rejection and exact override prompt, restarted/reloaded (draft retained, confirmation cleared), confirmed again and observed operational MISMATCH with correction-required follow-up. Machine assessment remained NEEDS_REVIEW. Normal grounded browsing had no console/page errors; the override journey produced the expected 422 grounding response.
- Inspected desktop and 375px override screenshots. Layout preserves exact target/value and separate confirmation/cancel controls without horizontal overflow. Existing design system retained. Added labelled input guidance, focusable announced error summary and linked field errors using ui-ux-pro-max guidance.

## Findings fixed

- A success notice initially said processing after completion. It now describes the current applied result, or retained acceptance on failure.
- Clear old grounding/refetch errors once the review closes or authoritative refetch succeeds.
- Poll responses begun before a mutation cannot overwrite its accepted Case.
- Reset issues fresh run IDs so an old confirmation cannot address a new reset fixture.
- Decision history records the server-verified demo actor; client-supplied actor spoofing is rejected.
- The first browser suite passed 21/22; its remaining assertion expected lowercase “mismatch” while the UI correctly displayed “Mismatch”. Corrected the text assertion, preserving the requirement that the mismatch remains visible.
- Existing F0 count assertions were updated to 23 cases, 12 open decisions and 17 frozen NEEDS_REVIEW assessments because five explicit F1 scenarios were added. Closed historical review controls remain disabled; open controls are now expected to work.

## Limits and outstanding gates

**Simulator verification only.** No real backend, live actor integration, production grounding or extraction, private dataset processing/export or external evaluation was exercised. Live decision controls clearly report unavailable until trusted live identity is integrated; the decision adapter method exists. The PRD 2 real-backend F1 criterion remains outstanding.

Hosted deployment and Docker execution remain the F0 external gates: no configured hosting target and no running Docker daemon. The container now creates a writable simulator state directory, but container execution is not verified. Preserve that directory with a volume for container restarts.

The controlled synthetic parser supports the authored TXT layouts and explicit numeric conventions; it is not a general document parser. Canonical user entry rejects ambiguous separators and unsupported precision rather than guessing. Demo sessions expire after two idle hours; reset discards their demonstration work intentionally. No real credentials or organizer content is shipped. Hermes, Telegram and production recovery services remain later work.

Vite's two upstream Zod PURE-comment warnings and Playwright's environment color warning remain documented build/tool warnings. No application warning suppression was introduced.

## Reproduce

See [README walkthrough](../README.md). Run `npm ci`, `npm run check`, `npm start`, then in a second terminal `npm run test:browser`. The browser report is `playwright-report/index.html`; screenshot artifacts are under `test-results/screenshots/` (both ignored/generated).
