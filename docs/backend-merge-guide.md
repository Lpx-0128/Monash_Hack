# Backend integration and merge guide

Draft, 20 September 2026. Intended for a teammate unfamiliar with the frontend branch. This is a pre-deployment guide: deployment-specific values below remain pending. Do not treat the proposed public-demo features as already implemented.

The main objective is to connect the hosted dashboard and Telegram/Hermes Interaction Layer to PRD 1's real backend and maintain that application across releases. Initial simulator hosting enables work before the backend is ready. The public judge demo is a separate supported mode, not the target architecture for all users. See `azure-deployment-proposal.md` for hosting stages and release gates.

## What exists

The branch `feat/prd-2-interaction-frontend` contains a React dashboard, a Node synthetic backend, a Node Telegram interaction service, and a Python Hermes gateway/plugin. Voice V1 work is also present and partly uncommitted; preserve it but disable it for the first cloud release.

Read the authoritative `docs/shared-system-contract.md`, then `docs/prd-1-backend.md`, `docs/prd-2-interaction.md` and `docs/prd-3-voice-attention.md`. The frontend working copy targets contract v2.1.2. Confirm what the backend actually implements; matching filenames do not prove matching schemas.

| Location | Responsibility |
|---|---|
| `src/api.ts` | Browser API requests and response validation |
| `shared/types.ts`, `shared/validation.ts`, `shared/decisions.ts` | Contract types, runtime validation and decision rules |
| `server/index.ts`, `server/app.ts`, `server/store.ts` | Current synthetic backend, static serving and persisted demo state |
| `interaction/api.ts` | Backend adapter used by Telegram/voice |
| `interaction/index.ts` | Interaction startup, routing, polling and optional voice startup |
| `hermes/shipping-review/` | Hermes plugin and constrained language interpretation |
| `scripts/f2_setup.py` | Local Hermes setup and existing manual pairing |
| `interaction/voice*.ts` | Voice functionality; excluded from initial deployment acceptance |
| `tests/`, `tests/browser/` | Contract, API, interaction and browser checks |

The backend owns cases, runs, reviews, assessments and workflow execution. Hermes interprets a reply into a proposed action. Interaction code validates scope and confirmation, then submits the existing structured `DecisionRequest`. It must never invent backend acceptance or mutate business state directly.

## Application modes and environment separation

First host the application for authorized team use with the simulator. Connect the real backend through staging once its contract and identity checks pass, then release the integrated application. Maintain the public synthetic demo independently; its open enrollment and isolation requirements must not define real-user authorization.

| Integrated application | Permanent judge demo |
|---|---|
| Teammate's actual API and processing | Synthetic cases and simulated processing |
| Explicit authorized real users | Automatic private-chat demo enrollment |
| Backend-owned authorization and data scope | Isolated workspace per judge |
| Azure-hosted interpretation | Azure-hosted interpretation |
| Independently tested before release | Remains available if backend integration fails |

Separate deployments are acceptable. A Git merge combines code; it does not require combining cloud resources. Avoid sharing bot tokens, state files or public demo credentials between these environments. A single Telegram bot may have only one active long-polling consumer.

## Safe Git flow

1. Each developer checks their branch and working tree. Commit intended work to their own branch, or deliberately stash it with untracked files included. Review files before committing; never add `.local`, environment secrets, private runtime profiles or generated state.
2. Fetch current remote branches and inspect the graph. Do not switch branches with unresolved work or use `reset --hard` to catch up.
3. Create a separate integration branch/worktree from current `origin/main`, leaving the working frontend branch untouched. Merge a committed frontend checkpoint and the required backend feature commits into that integration branch.
4. Review conflicts by responsibility: preserve frontend interaction behavior, backend persistence/workers, and one agreed contract. Never resolve all conflicts with “ours” or “theirs”. Reconcile dependency manifests, regenerate a consistent lockfile, and inspect combined scripts.
5. If only synchronizing docs, use the actual merged docs-only commit after checking its contents. Do not cherry-pick a merge commit blindly. The earlier proposal PR is [PR 4](https://github.com/Lpx-0128/Monash_Hack/pull/4); verify its current status and final commit before using it. Later uncommitted PRD edits may not be included there.
6. Run the integration checks below against a staging backend, then create a reviewable PR into main. Promote the tested integrated release explicitly; preserve the previous application release for rollback and keep the public-demo environment independently available.

Merging retains non-conflicting branch changes; conflicts require deliberate reconciliation. Fetching alone does not overwrite working files. Do not deploy a directory containing uncontrolled uncommitted changes: capture the intended release in a commit first.

## Changes needed for real backend integration

### 1. Contract and schemas

Compare actual responses against the shared validators, including nullable receipt timestamps, provenance, run identity, current review identity, allowed actions, error shapes and channel enums. v2.1.2 adds voice-related compatibility; if voice is disabled, still agree how strict version validation behaves. Do not loosen validators merely to silence integration errors.

The participant dataset does not provide receipt timestamps; preserve the agreed nullable/missing-data handling. Do not invent participant timestamps. Keep synthetic fixtures clearly identified.

### 2. Browser path

`VITE_API_MODE` and `VITE_API_BASE` are build-time frontend configuration. Changing them does not turn `server/index.ts` into an authenticated backend proxy: it currently starts the simulator.

Implement or configure a same-origin server adapter for the real backend. Forward only allowed API routes, preserve status/error shapes, validate user sessions, and attach trusted backend credentials server-side. If using direct cross-origin browser access instead, the team must explicitly implement compatible authentication, CORS and CSRF handling. Never place service tokens in `VITE_*` settings.

### 3. Telegram adapter

`ReviewApi` appends `/api/v1` to its configured base. Avoid an accidental `/api/v1/api/v1` URL. Today it sends a bearer token and `X-Telegram-Actor` (or `X-Voice-Actor`). Those actor headers are not automatically trusted by the teammate backend: agree the authenticated service identity and user-scoping mechanism first. Never forward a user-supplied actor assertion as trusted identity.

Current interaction queries are DEMO-scoped and enforce `assertDemo`. A real backend can still process contract-defined DEMO runs; choosing the real API does not itself require a new run kind. Preserve DEMO restrictions for public judges. If the product later needs operational/non-demo data, agree that scope with the backend and contract owners and implement separate authorization; changing a URL is not authorization.

### 4. Decisions and processing

Verify the real backend supports the exact review-decision endpoint and returns contract-compatible HTTP202 plus the expected response body. Durable acceptance is different from completed processing. After confirmation, report acceptance and refresh backend state; do not optimistically mark the case complete.

Keep stale run/review protection, duplicate handling, one-open-review behavior, action validation and machine-assessment immutability. If a request times out, reconcile status before retrying an uncertain submission. Use only the contract's defined idempotency behavior; do not invent an unsupported request field.

### 5. Evidence and notifications

The adapter obtains document bytes through `/api/v1/documents/{document_id}/content`, checks the document belongs to the case and is demo-safe, and currently limits demo transfer to 8 MB. Confirm the real backend supports the authorized content path or agree an adapter for the authoritative contract's evidence mechanism. Preserve filename, content type, ownership checks and safe error handling.

Keep notification delivery marking separate from review resolution. Validate `/reviews/{id}/notified` and its `run_id` semantics before wiring polling to the real backend. Do not let two pollers generate duplicate notifications.

### 6. Cloud connectivity and storage

Allow authenticated HTTPS from the interaction deployment to the backend. Keep internal Hermes endpoints private. Set bounded timeouts and log correlation identifiers without tokens or document contents. The real backend owns durable business data; frontend persistent storage holds only its demo data, sessions and interaction state. Do not copy simulator JSON into backend production tables as a migration shortcut.

## Configuration handover

Azure read-only check: subscription is Active and the user is Owner. The allowed-location policy lists `indiasouthcentral`, `uaenorth`, `eastasia`, `centralindia`, and `japaneast`. Compute quota could not be confirmed because the portal reports the selected provider is not registered. No Foundry AI resources were displayed. Model quota, actual deployment capacity and remaining student credit still need confirmation before release. No subscription settings were changed by this review.

The names marked “design item” below are requirements to implement, not claims of existing environment variables.

| Item | Current/proposed handling |
|---|---|
| Browser mode/base | Existing `VITE_API_MODE`, `VITE_API_BASE`; rebuild after changes |
| Public URL | HTTPS origin used for dashboard links and origin validation |
| Backend base | Existing interaction configuration; base excludes `/api/v1` |
| Backend identity | Server-side secret/identity; trusted actor mapping agreed with backend owner |
| Judge workspace | Design item: durable Telegram-user-to-demo-workspace mapping |
| Dashboard link exchange | Design item: single-use, expiring token exchanged for a secure session |
| Azure AI | Design item: provider, endpoint, deployment name, supported API and private credential/identity |
| Hermes runtime | Pin commit and Linux Python environment; do not copy Windows virtualenv |
| Persistent data | Linux paths for simulator, interaction state and Hermes SQLite/profile |
| Telegram | Environment-specific bot token and exactly one cloud polling consumer |
| Voice | Existing `VOICE_ENABLED` must be false/unset for initial deployment |

## Required post-merge tests

Apply the common application checks to every release and backend-specific checks to integrated releases. The two-judge and public link-enrollment checks additionally gate the public-demo mode; they do not prevent private team hosting. Run the real-backend journey through processing completion separately from simulator tests.

| Test | Expected result |
|---|---|
| `npm test` and `npm run build` | Tests pass and production build succeeds |
| Relevant `npm run test:browser` cases | Dashboard list/detail/evidence/decision flows remain usable |
| Hermes interpretation tests + one Azure smoke request | Azure inference actually runs; invalid/ambiguous output cannot submit |
| Schema checks against staging responses | Case, summary, review and errors match the agreed contract |
| Telegram + dashboard same authorized user | Both show the same backend-owned case/run state |
| Two judge accounts | Cases, evidence and decisions remain isolated |
| Expired/replayed dashboard link | Access rejected; no cross-user session |
| Confirmation and HTTP202 | Only confirmed intent submits; acceptance is not mislabeled completion |
| Stale review/run and concurrent decisions | Rejected/reconciled per contract, no duplicate workflow execution |
| Backend/model unavailable or request timeout | Clear recoverable message; no fabricated success |
| Evidence and EVAL access attempts | Out-of-scope/unsafe content denied server-side |
| Notification polling | One delivery path with correct marking and no duplicate consumer |
| Service/VM restart | State persists; processes restart; one bot consumer resumes |
| Phone with laptop terminals stopped | Public Telegram and dashboard remain usable |

Run tests with synthetic/staging data. Do not run tests that reset the public judges' workspaces. Record test dates, release commit, backend version and failures; do not claim “passed” until executed.

## Release record — complete after deployment

- Frontend release commit: PENDING
- Backend release commit/contract version: PENDING
- Integrated application URL, bot username and authorized-user access method: PENDING
- Public demo URL and bot username: PENDING
- Integrated staging URL and bot username: PENDING
- Azure resource group, region and VM/service names: PENDING
- Azure model deployment name/version: PENDING
- Service startup/restart instructions and private config locations: PENDING
- Persistent directories and backup/restore procedure: PENDING
- Previous release and tested rollback command/procedure: PENDING
- Smoke-test results and known limitations: PENDING
- Frontend/interaction owner and backend owner: PENDING

Keep secrets out of this guide. Give authorized operators the private configuration location and access procedure separately.

## Rollback

Retain the previous application release and an application-consistent state backup. Stop polling before replacing the gateway. Restore compatible code/configuration, then start one gateway and verify health. If a new storage format was introduced, use its tested rollback/migration procedure; do not blindly overwrite newer judge decisions with an old snapshot. A backend integration failure should leave the separate permanent synthetic demo available.
