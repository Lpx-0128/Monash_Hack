# Person A — integration handoff for B and C

What to call, what is persisted, what changed in shared code, and what is still
blocked. Read `docs/person-a-implementation.md` for how the analysis itself
behaves.

## 1. The boundary

Three pure functions. None opens a transaction, reads a global session, creates
a review ID, sends a notification or mutates a Case.

```python
from backend.intelligence.pipeline import (
    AnalysisContext, IntelligenceServices, analyze_case,
)
from backend.intelligence.recomputation import (
    apply_validated_decision, validate_human_proposal, working_state_from_analysis,
)

analysis = analyze_case(snapshot, context, services)           # automated pass
decision = validate_human_proposal(proposal, review, state, context)
result   = apply_validated_decision(decision, state, context)  # one accepted decision
```

| Input | Where it comes from |
|---|---|
| `snapshot` | `crud.load_input_snapshot(email_id, run_kind)` |
| `context` | `worker._build_context(case)` — case/run identity, config, injected time and ID providers |
| `services` | `worker._build_services()` — registries, model client, shared call budget |
| `state` | `working_state_from_analysis(analysis, snapshot, convention)` |

Time and ID providers are injected, so a run is repeatable. Wall-clock
timestamps are never extraction inputs.

### What comes back

`AutomatedAnalysis` carries the category and its reason, document refs with
content-backed roles, seven comparisons (or none for a non-BL case), the
assessment, a **review requirement**, unresolved targets, metrics, events and
private diagnostics. `backend/intelligence/wire.py` converts the public subset
into contract shapes:

```python
from backend.intelligence import wire

case.documents        = wire.document_refs_to_wire(analysis.documents)
case.fields           = wire.comparisons_to_wire(analysis.comparisons)
case.machine_assessment = wire.assessment_to_wire(analysis, assessed_at)
case.review           = wire.review_to_wire(analysis.review, review_id=..., ...)
```

Person A returns a review *requirement*; Person B mints the review ID and owns
the durable Review and its budget ledger. `wire.requirement_from_review()`
rebuilds the requirement from the persisted Review, so a decision arriving
after a process restart is validated against exactly what the person saw.

## 2. Changes made in shared code

Narrow, and listed so ownership stays clear.

| File | Change | Owner |
|---|---|---|
| `backend/worker.py` | `process_case` and `apply_decision` rewritten around real analysis; `_build_bl_fields`, the `time.sleep(1)` and the 15000 default are gone | A |
| `backend/worker.py` | `_commit_case` writes under a transaction-time run guard and reports whether the write was accepted | A, in B's area |
| `backend/crud.py` | `_load_inbox_email` replaced by registry-backed `load_input_snapshot`; real hashes, honest `demo_safe`, roles start UNKNOWN, `received_at` from the source or null | A |
| `backend/crud.py` | `update_case_with_decision` commits case, accepted decision and job together | A, in B's area |
| `backend/crud.py` | `reprocess_case_atomic` also deletes unapplied decisions from the superseded run | A, in B's area |
| `backend/models.py` | New `accepted_decisions` table: stable identity, immutable payload, run/review/job binding, `applied_at` marker | **B's area, minimally filled** |
| `backend/main.py` | Decision route validates through Person A against the shared working state, returns `PROCESSING` for every accepted action including acknowledgment, and no longer writes an optimistic `final_status=OK` | A + B |
| `backend/main.py` | Reprocess pins real input/config identities instead of `v1` placeholders | A |
| `backend/models.py` | New `run_snapshots` table: each run's input and config identity, source manifest and settled classification | **B's area, minimally filled** |
| `backend/worker.py` | `load_working_state` is the one loader validation and application share; `_commit_case` writes the case, the applied marker and the run snapshot in one transaction | A, in B's area |
| `backend/main.py` | Document endpoint serves registered bytes by verified identity, or 404s; no placeholder text, no filename lookup | A + B |
| `backend/main.py` | `POST /cases` and `/cases/batch` refuse an unregistered email id | A |
| `backend/requirements.txt` | Pinned to the tested set; added `pypdf`, `python-docx`, `openpyxl` | A |
| `.github/workflows/ci.yml` | Added `claude/**` so this branch is actually verified | A |

The shared contract, the PRDs and the frontend branch were **not** modified.

## 3. What is persisted where

- **`cases`** — unchanged shape. `run.input_version` and `run.config_version`
  now carry real reproducible identities instead of `"v1"`.
- **`jobs`** — unchanged.
- **`accepted_decisions`** — new. The worker applies *this* record; it never
  rediscovers a decision by scanning history, and there is no default value. A
  supplied job id must match its decision exactly — an unknown or already-applied
  job never consumes a different pending decision. `applied_at` is the
  idempotency marker and is written **in the same transaction as the case**, so a
  crash between them cannot leave a visible result that a retry applies twice.
- **`run_snapshots`** — new. The input version, config version, source manifest
  and settled classification of each run. Validation and resumption verify the
  current inputs still match before applying anything; if the sources or the
  policy have moved, the decision is refused with `STALE_RUN` and the case needs
  a new run. Replay is deterministic and never consults a provider.

The machine assessment is snapshotted before a decision is applied and compared
afterwards; a change raises rather than silently overwriting a frozen result.

## 4. For Person C

The endpoints C already expects are unchanged. What differs is that the data is
now real:

- `documents[].role` comes from content, so it can legitimately be `OTHER` or
  `UNKNOWN`, and `parse_status` can be `UNREADABLE`.
- `documents[].demo_safe` is **false for participant sources**. `GET
  /documents/{id}/content` returns 404 for those to a DEMO caller. Use the
  synthetic demo fixtures for anything user-visible.
- Review questions and context summaries are generated from the actual cause
  and are safe to display verbatim. They never claim OCR was attempted.
- `NEEDS_REVIEW` cases can still show confirmed differences in `fields` while
  `machine_assessment.defect_fields` is empty. That is the contract, not a bug.
- A BL case in `PROCESSING` has a null assessment. A Stats validator that
  assumes every classified BL case is already assessed will reject it —
  exercise this during integration rather than manufacturing an OK assessment.

### Demo fixtures ready to use

`resources/demo-fixtures/` — independently authored, publicly streamable:

| Email id | Shows |
|---|---|
| `email_demo_match` | all seven agree → OK, COMPLETED |
| `email_demo_mismatch` | one confirmed difference → MISMATCH, CORRECTION_REQUIRED |
| `email_demo_missing_weight` | FIELD / VALUE_INPUT question |
| `email_demo_document_choice` | DOCUMENT / CHOICE with NONE_OF_THESE |
| `email_demo_no_attachments` | missing attachment → external block |
| `email_demo_wrong_doc` | a packing list in the BL slot |
| `email_demo_scanned` | image-only PDF, honestly unreadable |
| `email_demo_corrupt` | unopenable PDF, distinct from a technical failure |
| `email_demo_invoice` | non-BL → OK with `fields: []` |
| `email_demo_pdf`, `email_demo_office` | PDF and XLSX/DOCX coverage |
| `email_demo_reference` | `SAME AS CONSIGNEE` dependency |
| `email_demo_needs_model` | an intent no rule can decide |

Regenerate with `python scripts/build_demo_fixtures.py`.

## 5. Contract version gate — unresolved

`main` emits and validates `schema_version: "2.1.1"`. The interaction branch's
`caseSchema` requires exactly `"2.1.2"` and its channel enum includes `VOICE`.

This implementation targets **v2.1.1**, the agreed baseline in this checkout.
The shared contract was not edited, no validator was weakened, and `VOICE` was
not spoofed as `TELEGRAM`. Adoption of v2.1.2 must be coordinated across server
emission, runtime validators, fixtures and accepted channel handling together —
it is an A/B/C decision, not a compatibility workaround.

**Before live frontend integration:** run the Python cases through C's actual
runtime validator on the agreed version. Some frontend implementation details
may also need correcting against the contract; conformance failures should be
attributed explicitly rather than patched away on either side.

## 6. Integration blockers still open

These are Person B's to close. Person A's work does not depend on them, but the
combined system is **not ready** while they stand.

| Priority | Gap | Needed |
|---|---|---|
| Blocker | `_get_caller_scope()` trusts `X-Run-Kind: EVAL` with no credential | Real authenticated scope. An untrusted header cannot authorize EVAL. |
| Blocker | Participant ingestion has no authenticated operator path | `POST /cases` currently accepts any *registered* id. Document access is already gated on `demo_safe`, which is the leak that mattered; ingestion still needs auth. `INTELLIGENCE_ALLOW_PUBLIC_PARTICIPANT_INGEST` exists for when it lands. |
| Blocker | One raw `case_id` primary key spans both namespaces | Separate internal identity per namespace. Document identities are already namespace-scoped. |
| Blocker | Actor identity is taken from the request body | Bind the actor to the authenticated caller; the same applies to C's Bearer-credentialed service. |
| Blocker | No immutable run archive | Reprocess still clears the current assessment and review. Archive run, assessment, review and decision identity so older reviews can be retrieved. |
| Blocker | Failure and retry writes are not run-guarded | `_mark_case_failed` and `_emit_retry_triggered` use unguarded `update_case`. A stale failing job can still mark a superseded case FAILED, and FAILED can retain an OPEN review, which should close with `TECHNICAL_FAILURE` and clear the completion time. |
| Conformance | Pydantic accepts omitted required nullable keys and an arbitrary `locator` | Strict wire schemas with correctly discriminated variants. |
| Conformance | Stats BL buckets use effective status | Use the contract-defined machine buckets; keep operational counts separate. |
| Conformance | `crud.get_reviews()` filters OPEN before the route applies its own filter | Support the contract's CLOSED and current-run filtering. |
| Release | Exporter's required-ID file is optional and ignored when absent | Exact coverage checks, validated eligible runs, atomic release outputs. |
| Reporting | "assessment completeness" counts non-null classification | Separate required-ID, classification and assessment coverage measures. |

`/cases/batch` remains absent from the authoritative endpoint table. It should
stay a private operator capability; C should not depend on it.

## 7. What has not been executed

Stated plainly so nobody reads more into this change than it earned:

- **No live model call.** No credentials exist here. The adapter is tested
  offline against an injected client and a mock transport.
- **No evaluator run, no accuracy score.** The counts in the implementation doc
  are this pipeline's output, not measured accuracy.
- **No Telegram or cloud smoke test**, and no live dashboard handshake.
- **No held-out evaluation.** The corpus was inspected structurally while
  building the rules, so these numbers are development-exposed, not held out.

The one real review handshake is demonstrated through local API integration
tests (`tests/integration/test_decision_flow.py`): a real backend outcome, a
real review, a real human decision, durable acceptance, worker resumption and an
updated case. **These tests are not authenticated** — no authentication exists
yet, and the actor identity they send is unverified. The live Telegram and cloud
requirement is **pending**, not passed.


## 8. Correction pass, and what it changes for you

Ten review findings (R1-R10) were fixed on `claude/person-a-corrections`. Two
affect how B and C integrate:

**A new table, `run_snapshots`.** It has a foreign key to `cases`, so anything
that deletes cases must delete from it first — the test isolation fixture in
`tests/conftest.py` shows the ordering. B should fold it into whatever run
archive it builds rather than treating it as a permanent Person A structure.

**A new refusal on the decision route.** `POST /reviews/{id}/decision` can now
return `409 STALE_RUN` because the run's *inputs or configuration* changed since
it was computed, not only because the run id is stale. The message says which.
C should treat it the same way as any stale-run conflict: refetch the case and,
if needed, reprocess.

Everything else is internal: block-bound grounding, the shared working-state
loader, the atomic applied marker, the consent gate and the connected extraction
path do not change any wire shape. Public document roles now reflect a human
document choice, which is a correction to the data C was already reading.
