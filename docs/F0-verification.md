# F0 verification record

Date: 19 September 2026. Branch: `feat/prd-2-interaction-frontend`.

## Verified locally

- `npm run check`: **36 contract/HTTP/reference tests passed**, TypeScript passed, Vite production build succeeded.
- `npm run test:browser`: **11 Chromium browser tests passed** on the production preview. The suite covers all 18 fixture pages, navigation, API filters, evidence expansion and document opening, disabled F1 actions, timed replay/polling, reset, empty state, simulated loading/outage/access denial, stale-data retention, keyboard navigation and reduced motion.
- Four viewport checks: **375, 768, 1024 and 1440 pixels**, each on overview, case list and candidate-review detail. Assertions reject page-wide horizontal overflow. Twelve page/viewport axe WCAG 2 A/AA and 2.1 AA audits reported **zero violations**. These automated audits do not constitute a full accessibility certification.
- Browser network assertions confirm combined category, operational outcome and review filters reach `/api/v1/cases`; API tests cover response shapes/statuses and DEMO access restrictions. Normal browsing/replay reported no console/page errors. Deliberate fault tests produce expected 503/403 responses and visible recovery states.
- Manual in-app browser inspection: overview, case list, workflow filtering, candidate detail; screenshots inspected for desktop/tablet/mobile layout and readable status separation. Captured browser warning/error log was empty.
- Source fixtures: each document's bytes, SHA-256, exact code-point evidence ranges, field context and normalized values are audited. Negative assertions reject seal-number grounding even when source/hash/digits are consistent, and reject overrides bound to the wrong run, field, side or value.
- Backend behavior: duplicate create returns actual existing state; replay supersedes an old review and starts a fresh run; stale scheduled work cannot commit; replay does not inherit human overrides; GET does not mark reviews notified; sessions are isolated; guessed/EVAL resources are denied.

- Participant reference checks validate the five-key source shape, v2.1.1 null-receipt intake, required nullable receipt schema, malformed-time rejection, fictional timestamp provenance, multiline addresses, alternate labels, container/weight equivalence and unresolved no-attachment intent before and after replay. Browser checks inspect expanded email/source context at 375px.

## Issues found and fixed during the loop

1. Test harness passed a string to Node's regular-expression assertion; corrected it, preserving the content-type check.
2. Select controls wrapped their option text inside implicit labels. Added explicit accessible names for the filter and connection controls; the same browser interactions then passed.
3. Source evidence test matched identical SI and BL quotations. Scoped the assertion to the explicitly opened SI evidence, retaining the full source-content assertion.
4. Connection controls initially defaulted to Normal after reload even if the session retained a fault. Bootstrap now supplies the current server-side fault setting; the browser test includes reload followed by recovery.

5. The updated browser suite initially reached a stale 17-case preview. Restarted the identified Node service; all 10 checks then passed against the 18-case simulator.
6. Manual inspection found a document-parsed history entry on the no-attachment case. Removed that false event, clarified its review question to cover intent and both required documents, and added a regression assertion. All 35 prior-version checks and the build passed again; both affected browser journeys passed after restarting the final preview.

## Limits and outstanding checks

- **Hosted deployment remains outstanding.** No hosting provider/project or deployment access was configured. A local production preview and Docker deployment configuration are supplied; this does not satisfy the hosted F0 exit gate.
- Docker CLI exists, but its Linux engine pipe is absent: the daemon is not running. Container build/run was therefore **not verified**. No Docker settings were changed.
- Tested with local Node 25.2.0, npm 11.6.2 and Playwright Chromium. Node 22.12+ is the declared runtime minimum; the Docker image targets Node 22.
- Vite emits two upstream Zod PURE-comment annotation warnings. It strips those comments and builds successfully. No warning filters or error suppression were added. Playwright reports an environment NO_COLOR/FORCE_COLOR warning; this is unrelated to application runtime behavior.
- The simulator uses disposable, in-memory guest sessions. Restart resets data; it makes no claim of durable decision acceptance, restart-safe processing or real AI execution.
- The live adapter's wire boundary is implemented, but **no real backend handshake** has been performed. Decision entry/submission/override confirmation remain F1. Telegram and production backend work remain later-phase work.

## Evidence locations

`test-results/screenshots/` contains the current responsive evidence; `playwright-report/index.html` records the full 11-journey v2.1.1 run. Both are generated/ignored artifacts; rerun the documented commands to reproduce them. Core tests live in `tests/contract.test.ts`, `tests/api.test.ts` and `tests/participant-reference.test.ts`; browser tests live in `tests/browser/f0.spec.ts`.

## v2.1.1 adoption verification

The revised contract and both PRDs were copied byte-for-byte from the supplied outputs. Types, validator, mapper, fixture responses, UI labels and replay preservation were updated together. The old blocker is removed; no real-data ingestion/export, deployment or Hermes handshake is claimed. The first added mapper test used an empty subject rejected by the existing validator; corrected the test input to a valid subject without weakening validation.

AC-17/18/19 checks pass for valid null intake, normalized supplied receipt, rejected malformed/omitted receipt values, known/unknown UI states and preserved receipt/creation time through replay. The simulator bootstrap contract marker and client validation also use 2.1.1.
