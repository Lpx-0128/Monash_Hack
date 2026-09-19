# Harbor Review · PRD 2 / F0

Responsive shipping-review dashboard with a **stateful synthetic Node API**. Implements Overview, Case list and Case detail against Shared System Contract v2.1.1. All documents and cases are generated; no organizer data, AI calls or notification delivery are used.

## Run

Requires Node **22.12+** and npm. From this repository:

```sh
npm ci
npm run build
npm start
```

Open **http://localhost:5173**. This is the production build served alongside the API. For development with hot reload use `npm run dev` instead. Stop the other server before switching. `PORT` and `HOST` can be set in the launching environment; `.env.example` documents settings (the server does not automatically load a `.env` file).

## Try the demonstration

1. Overview shows 18 seeded cases: 7 pending decisions, 3 auto-completed runs and 2 technical failures. Machine and operational counts are deliberately different.
2. **Explore cases**. Combine workflow/category/outcome/review filters, or search by subject/sender/ID.
3. Open **Gross weight · manual override applied**. The frozen machine assessment is NEEDS_REVIEW; the operational outcome is OK. Its BL override stays visibly ungrounded and includes exact confirmation lineage.
4. Expand **View evidence**, then **Open source**. Documents are UTF-8 plain text, labeled SYNTHETIC; locators use zero-based Unicode code-point offsets with exclusive end. SHA-256 and byte counts are shown under source integrity.
5. Inspect input, candidate and document-choice reviews; NONE_OF_THESE is visible. Actions are disabled and explained as F1-only. An acknowledged external block remains blocked.
6. **Replay / Reprocess** starts a new run and returns PROCESSING. After 8 seconds, polling displays the predefined outcome. Old reviews are superseded. Historical human overrides are not copied into new automated runs.
7. **Demo controls → Advance processing** settles seeded processing examples immediately. These seeds are held initially so every F0 state can be inspected. This also advances active replay jobs.
8. Demo controls offer **Load empty dataset**, **Reset demo**, and normal/slow/outage/access-denied connections. Reset restores the exact seeded set. A spontaneous failed poll retains labeled stale data; access denial hides protected data and stops polling until explicit retry/recovery.
9. In an empty dataset, **Process sample email** creates the approved match fixture. Duplicate creates open the existing current run (HTTP 200), while a new one returns 202.

Each browser has its own server-issued HttpOnly, SameSite=Strict DEMO guest cookie. Sessions and state are **in memory**, expire after two idle hours, and reset on server restart. This is intentionally a disposable simulator, not durable production workflow storage. No bearer token or user-supplied actor identity is embedded in the frontend. Only the fixed synthetic fixture allowlist is accessible; EVAL scope and guessed objects are denied server-side.

## Participant reference boundary

The official statement and participant bundle were reviewed for structure and layout only. All displayed correspondence, addresses, documents and outcomes remain independently authored synthetic examples. Expand **Synthetic email context** to inspect the five-key source shape and fictional receipt-time notice. Inspect **Draft requested · no attachments · intent unresolved** for an explicit blocked comparison with seven unknown fields. The submission template supplies no ground truth.

`shared/participant-mapping.ts` produces a validated initial v2.1.1 Case with `received_at: null` when source receipt time is absent. Supplied malformed times fail validation. Case creation/update/run times stay separate, and replay preserves source absence. Known synthetic times are explicitly fictional; unknown ones display “Received time unavailable.” See the [authoritative contract](shared-system-contract-v2.1.1.md), [reference review](docs/participant-reference-review.md) and [adoption notes](docs/shared-contract-discrepancies.md). The previous v2.1 file is historical only.

## Architecture and integration boundary

- `shared/types.ts`: exact TypeScript wire definitions extracted from the authoritative contract.
- `shared/validation.ts`: strict Zod wire schemas and semantic invariants, used on the server and API adapter. Source-content grounding is a backend concern; the synthetic document audit checks exact bytes, locations, field context and values.
- `server/fixtures.ts`: 18 complete cases and consistent source documents, plus source-integrity audit.
- `server/store.ts`: session state, latest-run metrics, guarded simulated transitions and superseded review records. A server timer advances jobs; GET does not record delivery or trigger transitions.
- `server/app.ts`: contract HTTP endpoints under `/api/v1`, guest scope, same-origin writes and safe error envelopes.
- `src/api.ts`: one `CaseApi` interface with simulated and future live HTTP implementations. Both validate responses. UI components never import fixtures or the simulator.
- `src/usePoll.ts`: non-overlapping 3-second polling, bounded failure backoff, cancellation, stale-data handling and stopping protected reads after 401/403/404.
- `src/App.tsx`, `src/styles.css`: three screens and ui-ux-pro-max-informed design system. No external fonts or content dependencies.

F0-only simulator controls live separately under `/api/demo/*`; they do not extend the shared Case wire shape or business vocabulary. `/health` and `/ready` expose status only. `/api/v1/reviews/:id/decision` returns 422 ACTION_NOT_ALLOWED for an active F0 review, 409 for a closed/stale one; no accepted decision is fabricated. `/notified` rejects the guest identity with 403.

For a real backend, set build-time `VITE_API_MODE=live` and optionally `VITE_API_BASE=/api/v1`. Host the frontend behind an authenticated same-origin gateway that routes `/api/v1` to the real service. Do not start the demo server as a real-backend proxy: it always serves synthetic data. Never put credentials in `VITE_*`. Live integration has not been verified in this milestone.

## Verification

```sh
npm run check                 # contract + HTTP tests, TypeScript, production build
npx playwright install chromium
npm start                    # keep running in another terminal
npm run test:browser          # browser journeys, 4 viewports, axe accessibility
```

Browser evidence is written to `test-results/` (ignored by Git). `playwright-report/` contains the HTML report. See `docs/F0-verification.md` for the checks actually performed and `docs/F0-acceptance.md` for the acceptance checklist.

## Deployment configuration

No hosting provider, deployment project or credentials were supplied. **Hosted deployment is outstanding; F0's deployed exit gate is not claimed complete.** The local production preview is the verified deliverable.

A Dockerfile builds the client and runs a non-root Node service. On a container host:

```sh
docker build -t harbor-review-f0 .
docker run --rm -p 5173:5173 harbor-review-f0
```

Use a single always-running instance (the simulation is in memory), port 5173, health route `/health`, readiness route `/ready`, and HTTPS at the hosting edge. Set `COOKIE_SECURE=true` for HTTPS. Do not deploy only `dist/` to a static host: the demo requires its Node API. Docker execution itself requires a local Docker daemon and is reported separately from the verified Node build.

## Milestone boundaries

Completed locally: F0 shell, case browsing, review/context display, source access, mock/live adapter boundary, contract-valid fixtures, stateful simulation and reset/error controls.

Reserved for **F1**: actual decision submission, canonical input preview, exact override-confirmation UX, real human-resolution flows and backend integration tests. Hermes setup and Telegram delivery/routing belong to F2. Restart-safe business workflows belong to later phases and the real backend. Stored human-resolution/acceptance examples are synthetic history, not actions performed by this app.
