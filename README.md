# Harbor Review · PRD 2 / F1 + F2 integration

Responsive shipping-review dashboard with a **stateful synthetic Node API**. Implements Overview, Case list and Case detail against Shared System Contract v2.1.1. All documents and cases are generated; no organizer data or AI extraction is used. F2 adds an opt-in Hermes Telegram integration; live delivery requires local bot setup and explicit test-chat authorization.

**First Telegram bot:** follow [F2 setup](docs/F2-setup.md). Default F1 preview remains on 5173; the shared F2 simulator/dashboard uses 5176. See [F2 verification and limits](docs/F2-verification.md) before describing it as a live integration.

## Run

Requires Node **22.12+** and npm. From this repository:

```sh
npm ci
npm run build
npm start
```

Open **http://localhost:5173**. This is the production build served alongside the API. For development with hot reload use `npm run dev` instead. Stop the other server before switching. `PORT` and `HOST` can be set in the launching environment; `.env.example` documents settings (the server does not automatically load a `.env` file).

## Try the F1 review journeys

Open **All cases**; reset through **Demo controls → Reset demo** to restore all 23 synthetic scenarios. Reset creates fresh run IDs so an old confirmation cannot target a new demonstration.

| Journey                | Case and steps                                                                                                              | Observable result                                                                                                        |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| Grounded input         | **Source available · enter BL gross weight**; enter `21707`, Preview value, Confirm submission                              | 202 acceptance, about four seconds of processing, then human document-confirmed value and operational OK                 |
| Manual override        | **Gross weight needs confirmation**; enter `22000`, preview and submit; inspect the rejection, then Confirm manual override | Review stays open on rejection; confirmed value stays ungrounded; operational mismatch and correction-required follow-up |
| Change/cancel          | Cancel an override proposal or edit the input                                                                               | Confirmation disappears; new value requires a new preview and confirmation                                               |
| Candidate choice       | **Two gross-weight candidates**; inspect evidence, select an option and confirm                                             | Grounded candidate applied; `21707` matches, `22000` produces mismatch                                                   |
| Unsupported candidate  | **Unsupported candidate · explicit override**; choose `23000` and confirm                                                   | Same grounding rejection and exact override flow as typed input                                                          |
| Document assignment    | **Identify the draft bill of lading**; inspect source, choose BL document and confirm                                       | Target role BL assigned; all BL values recomputed from that immutable synthetic source                                   |
| Two reviews            | **Two sides · SI before BL**; enter `21707` for SI, then again for the new BL review                                        | First result remains NEEDS_REVIEW; no proposal carries into the second review; then operational OK                       |
| Two fields             | **Two uncertainties · first review**; confirm count `3`, then weight `21707` (requires override)                            | Canonical field order and frozen machine assessment preserved                                                            |
| External action        | **Missing draft BL · external action**, or “I can’t tell” / “None of these” on other reviews                                | Brief accepted/processing state, then CLOSED review and BLOCKED_EXTERNAL, never completion                               |
| Known mismatch         | **Known container mismatch · weight review**; resolve weight with `21707` override                                          | Count mismatch remains visible throughout and ends with correction-required follow-up                                    |
| Lost response          | Demo controls: **Next decision simulation → Accept, then lose response once**; submit a grounded review                     | UI refetches authoritative state; no automatic resend or false failure                                                   |
| Resumption failure     | **Decision journey · simulated resumption failure**; submit `21707` override                                                | FAILED with accepted decision retained; operator recovery required, no re-entry                                          |
| Competing/stale action | Open the same review in two tabs; resolve or reprocess in one, then attempt an old action in the other                      | First acceptance wins; old actions return 409 and refresh; drafts never transfer to another review/run                   |

Ordinary numeric entry is deliberately canonical: positive whole counts; positive kg values with a dot decimal and no grouping separators. Unsupported/ambiguous notation is explained before submission. Known/unknown receipt times remain distinct from case creation and update times.

Polling runs every three seconds. Decisions normally resume after four seconds; replays after eight. **Advance processing** is an explicit shortcut. Source documents/evidence, filters, empty/reset states and connection fault controls remain available. Demo controls apply only to this browser's guest session.

The production preview atomically saves demo sessions, accepted decisions and pending jobs in ignored `.local/simulator-state.json` before returning 202. Restart recovery is tested. Set `SIMULATOR_STATE_FILE` for another writable location; retain that directory across container restarts if desired. This is a single-process synthetic store, not a production database or multi-instance coordination service. Reset intentionally clears that session's history/work. Guest sessions expire after two idle hours; use reset for a repeatable walkthrough. No browser credentials, model calls or real documents are involved.

## Architecture and F1 boundary

`shared/decisions.ts` validates the closed request union and parses canonical proposals. `server/decisions.ts` performs bounded synthetic source grounding, exact confirmation checks, dependency-free fixture recomputation and review sequencing. `server/store.ts` owns acceptance, pending work and active-run guards. `server/app.ts` verifies the session's explicit DEMO guest identity and persists state. `src/ReviewActions.tsx` owns drafts/preview/confirmation/recovery, and calls the same `CaseApi.decide` interface used by the future live adapter.

Drafts are stored in sessionStorage keyed by case/run/review; confirmations are never persisted. Cancel/edit invalidates confirmation. The UI disables further submissions during uncertain responses until refetch succeeds and never retries a decision automatically. Unsupported values are never silently converted to overrides. Frozen machine assessment and operational resolution remain separate.

## Participant reference boundary

The official statement and participant bundle were reviewed for structure and layout only. All displayed correspondence, addresses, documents and outcomes remain independently authored synthetic examples. Expand **Synthetic email context** to inspect the five-key source shape and fictional receipt-time notice. Inspect **Draft requested · no attachments · intent unresolved** for an explicit blocked comparison with seven unknown fields. The submission template supplies no ground truth.

`shared/participant-mapping.ts` produces a validated initial v2.1.1 Case with `received_at: null` when source receipt time is absent. Supplied malformed times fail validation. Case creation/update/run times stay separate, and replay preserves source absence. Known synthetic times are explicitly fictional; unknown ones display “Received time unavailable.” See the [authoritative contract](docs/shared-system-contract.md), [reference review](docs/participant-reference-review.md) and [adoption notes](docs/shared-contract-discrepancies.md). Earlier document versions are preserved in Git history.

## Architecture and integration boundary

- `shared/types.ts`: exact TypeScript wire definitions extracted from the authoritative contract.
- `shared/validation.ts`: strict Zod wire schemas and semantic invariants, used on the server and API adapter. Source-content grounding is a backend concern; the synthetic document audit checks exact bytes, locations, field context and values.
- `server/fixtures.ts`: 23 complete cases and consistent source documents, plus source-integrity audit.
- `server/store.ts`: session state, latest-run metrics, guarded simulated transitions and superseded review records. A server timer advances jobs; GET does not record delivery or trigger transitions.
- `server/app.ts`: contract HTTP endpoints under `/api/v1`, guest scope, same-origin writes and safe error envelopes.
- `src/api.ts`: one `CaseApi` interface with simulated and future live HTTP implementations. Both validate responses. UI components never import fixtures or the simulator.
- `src/usePoll.ts`: non-overlapping 3-second polling, bounded failure backoff, cancellation, stale-data handling and stopping protected reads after 401/403/404.
- `src/App.tsx`, `src/styles.css`: three screens and ui-ux-pro-max-informed design system. No external fonts or content dependencies.

Simulator controls live separately under `/api/demo/*`; they do not extend the shared Case wire shape or business vocabulary. `/health` and `/ready` expose status only. `/api/v1/reviews/:id/decision` implements validated 202 acceptance, 409 stale/closed conflicts and 422 input/target/grounding/confirmation errors. Invalid attempts are rate-limited. `/notified` still requires an interaction-service identity and returns 403 to dashboard guests.

For a real backend, set build-time `VITE_API_MODE=live` and optionally `VITE_API_BASE=/api/v1`. Host the frontend behind an authenticated same-origin gateway that routes `/api/v1` to the real service. Do not start the demo server as a real-backend proxy: it always serves synthetic data. Never put credentials in `VITE_*`. Live integration has not been verified in this milestone.

## Verification

```sh
npm run check                 # contract + HTTP tests, TypeScript, production build
npx playwright install chromium
npm start                    # keep running in another terminal
npm run test:browser          # browser journeys, 4 viewports, axe accessibility
```

Browser evidence is written to `test-results/` (ignored by Git). `playwright-report/` contains the HTML report. See `docs/F1-verification.md` for current checks and `docs/F1-acceptance.md` for the acceptance checklist. The F0 notes preserve the earlier checkpoint.

## Deployment configuration

No hosting provider, deployment project or credentials were supplied. **Hosted deployment is outstanding; F0's deployed exit gate is not claimed complete.** The local production preview is the verified deliverable.

A Dockerfile builds the client and runs a non-root Node service. On a container host:

```sh
docker build -t harbor-review-f0 .
docker run --rm -p 5173:5173 harbor-review-f0
```

Use a single always-running instance with a persistent writable state directory (the simulator does not coordinate multiple processes), port 5173, health route `/health`, readiness route `/ready`, and HTTPS at the hosting edge. Set `COOKIE_SECURE=true` for HTTPS. Do not deploy only `dist/` to a static host: the demo requires its Node API. Docker execution itself requires a local Docker daemon and is reported separately from the verified Node build.

## Milestone boundaries

**F1 is verified against the simulator.** See [F1 acceptance](docs/F1-acceptance.md) and [verification](docs/F1-verification.md). The previous [F0 verification](docs/F0-verification.md) records the checkpoint before interactive decisions.

**Real-backend F1 acceptance remains outstanding.** No real service or trusted live actor integration is configured. Live decision UI is explicitly unavailable until that identity integration is provided; the shared adapter method is implemented. Synthetic grounding, restart and race tests do not prove production extraction, durability or authorization. Hosted deployment and Docker execution retain their outstanding F0 gates.

Hermes/Telegram belongs to F2. Real document extraction, private dataset evaluation and production recovery infrastructure are outside this milestone. The authoritative documents are under [docs/](docs/README.md); old root copies are preserved in Git history and a local pre-F1 backup.
