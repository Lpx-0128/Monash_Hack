# PRD 1 — Backend Automation & Intelligence Layer

**Version:** 2.1.1-aligned · 19 September 2026

**Authority:** [Shared System Contract v2.1.1](./shared-system-contract.md) governs every interface and shared semantic rule.

**Companion:** [PRD 2 — Interaction / Frontend Layer](./prd-2-interaction.md)

**Owners:** A — Document Intelligence; B — Platform + Validation.

## 1. Objective and user context

Build the real cloud-executed backend that classifies shipping emails and compares SI against draft BL across seven required fields. Automate dependable cases, preserve confirmed discrepancies, and ask humans only for decisions they can usefully make.

Shipping staff face mixed inbox traffic, inconsistent document labels/layouts, missing information, and repetitive verification. SI describes intended shipment details; BL is checked against it. A reliable discrepancy is an outcome requiring correction, not automatically a review question. Missing or uninterpretable information is uncertainty, not a confirmed mismatch.

The backend must support the product promise “Don’t monitor AI. Let it chase you” by exposing actionable reviews and visible follow-up states. It must preserve what automation originally decided even when humans later resolve operational work.

Direct inspection of the participant bundle found 520 email records, 126 with attachments, and 250 attachment files: 192 TXT, 28 PDF, 8 DOCX, and 22 XLSX. All email records lack a receipt timestamp. B0 must reproduce the inventory for the actual input version rather than hard-code those counts.

## 2. Success criteria and scope

### MUST

- Classify every required email into the contract vocabulary.
- Parse the participant dataset's required TXT/PDF/DOCX/XLSX content paths.
- Extract, ground, normalize, and compare all seven canonical fields for BL comparisons.
- Implement G1–G3 in the first vertical slice.
- Demonstrate at least one meaningful real AI classification or extraction fallback in that slice.
- Preserve raw values, source context, multi-location evidence, and per-value provenance.
- Produce correct deterministic roll-up and organizer-shaped automated assessments.
- Create bounded, targeted reviews; accept durable decisions; recompute dependent values.
- Support explicit manual overrides operationally without falsifying grounding or machine output.
- Implement contract APIs, asynchronous durable work, run-guarded writes, and bounded retries.
- Keep EVAL private and public/bot data explicitly demo-safe at the server boundary.
- Export complete, immutable, fail-closed EVAL snapshots with release manifests.
- Run real processing, persistence, and AI integration in cloud infrastructure.
- Deliver baseline and final validation reports, integration tests, visible failures, and recovery.
- Complete a real review handshake before broad accuracy tuning.

### SHOULD

Improve extraction coverage, aliases, evidence clarity, targeted independent mismatch verification, caching efficiency, and latency/cost instrumentation after the working MUST path. Report AI contribution and held-out behavior. Add an informative live pipeline view using real history.

### OPTIONAL / stretch

OCR and vision, evidence image crops, carefully validated semantic equivalence, replacement uploads in the public UI, real mailbox ingestion, richer workers/queues. Image-only documents may become NEEDS_REVIEW/unreadable in the preliminary core; OCR remains a stretch under the agreed scope.

### Non-goals and high-risk distractions

No autonomous edits to shipping documents, automatic outbound correction emails, WhatsApp/voice backend, general shipping ontology, event bus, Kubernetes, enterprise authorization system, multi-region resilience, or multi-agent orchestration framework. A small worker and durable store are sufficient.

## 3. Architecture and implementation boundary

~~~text
Participant dataset / approved demo fixture
  → Inbox adapter
  → Classification (deterministic signals → AI fallback when needed)
  → Internal actionability diagnostic
  → Attachment resolution and document-role assignment
  → Parser router
  → Deterministic extraction → targeted AI fallback
  → G1–G3 grounding → normalization → comparison → mismatch verification
  → Frozen automated assessment
  → COMPLETED or targeted review / external block

Structured human decision
  → Authenticate + validate + durable acceptance
  → Recompute changed values and dependencies
  → Current operational comparison + resolution
  → Completion, next bounded review, or external block
~~~

A owns document interpretation and comparison. B owns transactional orchestration, APIs, cloud, access control, and validation/export. C consumes the contract only. Backend functions must not depend on Telegram markup, dashboard components, or browser state.

Prefer a cloud service that can run a persistent worker/notifier lifecycle, a transactional state store, object/file storage, a model service, and structured logs. If hosting cannot sustain worker polling, choose a supported scheduling mechanism before building the workflow. Do not rely on request-local background tasks surviving after a 202 response.

## 4. Deterministic code and AI responsibilities

| Deterministic code owns | AI may interpret |
|---|---|
| IDs, hashes, time, storage, source versions | Email intent when rules are inconclusive |
| Type/schema validation and evidence checks | Messy document layouts and semantic labels |
| Number parsing, unit conversion, aggregation | SI/BL role hints when direct signals fail |
| Equality, roll-up, state transitions | Candidate extraction with quotes/locations |
| Review routing and budgets | Optional human-readable explanation |
| Durable jobs, retries, authorization, export | Optional text equivalence after validation |

AI returns structured data, never executable workflow decisions. Validate schema, canonical field names, candidate values, and evidence independently. Model confidence alone cannot make a field comparable.

At least one real model path must handle a representative input in B1. A hard-coded result or an unused API call does not satisfy meaningful AI integration. Other AI features can remain SHOULD; do not add AI to arithmetic or concurrency.

Treat document/email content as data. Embedded instructions cannot change system prompts, authorization, tool access, or evaluation rules.

## 5. Ingestion, classification, and source handling

Create an immutable input snapshot and hash the email plus referenced attachments. A run records input_version and config_version. Config identity includes code, parser, model, prompt, alias, normalization, and comparison policy versions.

At intake, category/classified_by may be null and document roles UNKNOWN. Resolve local participant references or approved fixture IDs without allowing arbitrary file traversal. Do not fetch arbitrary URLs from user-supplied documents.

The participant input contains email_id, from, subject, body, and attachment paths; it is not already a Case API response. Retain the body for classification and adapt source fields into the shared Case shape. Emit schema_version="2.1.1" and email.received_at=null when no receipt timestamp is supplied. This is valid input metadata absence: do not block mapping, create a shipping review, or fail export because of it. Never substitute system time, file modification time, or a date from quoted correspondence.

Case.created_at records initial case creation and remains stable across reprocessing. Case.updated_at and run.started_at describe their respective system events. They do not supply an email receipt time. Validate a genuinely supplied timestamp before normalization; distinguish malformed source values from missing values. No additional ingestion timestamp is required.

Classify from email intent and body as well as subject. Deterministic signals handle clear cases; validated AI classification resolves ambiguity. Non-BL categories finalize as OK with fields=[] and no review.

NOT_READY remains an internal diagnostic. It must not silently skip BL assessment, produce a sixth category, or invent an organizer status. Follow the contract's baseline until participant-facing evidence establishes a complete alternative mapping.

For a required role:

- Missing referenced/available attachment → missing_attachment.
- Files exist but cannot establish expected type → wrong_doc_type.
- Plausible alternative files → document CHOICE with explicit target_role.
- Whole-document unreadability → external block.
- Do not assign the same document to SI and BL.

Keep immutable document content and parsed artifacts by content hash. Role assignment may change working interpretation within a run after a decision, but cannot rewrite frozen assessment evidence.

## 6. Parsing, extraction, and minimum grounding

### Parser router

| Format | Required extraction and locator support |
|---|---|
| TXT | Decoded text, preserved lines, text ranges |
| PDF | Text by page; page number and quoted text |
| DOCX | Paragraphs and tables; paragraph index or table/row/column |
| XLSX | Sheets, cells, labels, rows, and stored/cached values |

Detect format from content as well as extension. Preserve table/row structure; flattening all content into one string can confuse labels and totals. An unsupported/corrupt/image-only input is a document-data limitation when established from the content; a parser bug, timeout, or unavailable service is a technical failure.

For formulas, do not treat missing cached spreadsheet results as a valid blank or silently execute untrusted macros. Use a supported deterministic reading path or escalate the specific limitation.

### Extraction sequence

1. Extract deterministic candidates using field aliases, table headers, and structural context.
2. Apply approved totals/reference rules to derive one canonical candidate where possible.
3. If unresolved, use targeted AI extraction with field, source quote, and locator.
4. Validate source existence, field context, and derivation.
5. Preserve all rejected/conflicting candidates in private diagnostic records; expose relevant candidates with evidence for a review.
6. If no valid canonical value remains, emit NOT_COMPARABLE with a precise internal cause.

Minimum grounding is MUST in B1:

- G1 checks exact quote/location against the preserved parser output.
- G2 checks canonical-field aliases or unambiguous structure, not mere digit occurrence.
- G3 re-derives the normalized value using deterministic policy.

For aggregated values, evidence covers every contributing component or the trusted total. For referenced values, evidence includes the reference and its target. Human-confirmed values and candidate selections follow exactly these checks.

## 7. Field policy baseline

The contract defines comparable and grounded. This table provides versioned implementation policies. Organizer-dependent choices use conservative defaults and must not be silently tuned to private answers. Any shared behavior change requires the contract's change-control process.

| Field | Canonical type | Normalization | Aggregation / references | Equality |
|---|---|---|---|---|
| shipper | Nonempty text block | Unicode normalization, case-fold, trim/collapse whitespace; remove only approved insignificant punctuation | None; retain party name and address present in the labelled block | Exact normalized full block; approved general aliases only |
| consignee | Nonempty text block | Same as shipper | None | Same |
| notify_party | Nonempty text block | Same; recognize explicit “same as consignee” wording | Resolve against consignee on the same document side; retain both evidence sets | Compare resolved canonical blocks |
| port_of_loading | Nonempty port text | Case/space normalization plus versioned, verified aliases | None | Exact canonical port; no arbitrary fuzzy merge |
| port_of_discharge | Nonempty port text | Same | None | Same |
| container_count | Positive safe integer | Parse count-labelled expressions, e.g. 3 × 40HC → 3 | Trusted total once, otherwise sum disjoint component counts | Exact integer |
| gross_weight_kg | Positive finite decimal kg | Parse unambiguous locale notation; explicit mass-unit conversion | Trusted gross total once, otherwise sum disjoint gross components in kg | Exact decimal equality; no unverified tolerance |

Retain original raw text alongside the normalized value. Do decimal arithmetic using an exact decimal representation internally; avoid floating-point tolerance as an accidental business rule. Serialize normalized numeric values as JSON numbers only after range and finite-value checks.

### Explicit edge rules

- **Separators:** accept 1,234.50 and 1.234,50 when both separators provide a consistent grouping/decimal pattern. A lone 1,234 or 1.234 can be ambiguous across locales; use an explicit document/column convention established independently, otherwise escalate. Never globally strip commas.
- **Units:** kg/kgs/kilograms mean kg; explicit metric tonnes convert by 1,000. Convert other units only from a versioned verified unit table. Bare “tons” is ambiguous unless convention is established.
- **Missing unit:** a clear column/field heading can supply it. Otherwise gross weight is not comparable; do not assume kg merely because the canonical output field uses kg.
- **Rounding:** do not round for equality by default. UI display rounding never alters stored comparison. Any organizer-approved tolerance becomes a versioned policy with boundary tests.
- **Ranges:** zero, negative, NaN/infinity, nonintegral counts, or values outside supported safe numeric range are invalid. Suspicious but possible magnitudes trigger investigation; do not introduce unsupported business limits.
- **Party identity:** compare the normalized full labelled block by default, including address. Do not discard address differences without evidence that organizer policy permits name-only comparison.
- **Blanks:** blank on either or both sides is NOT_COMPARABLE.
- **Totals:** if a trusted unique total exists, use it once. Otherwise aggregate disjoint components. Never sum totals plus components. Identical repeated totals may be deduplicated only when clearly the same total; inconsistent totals or uncertainty about duplicated rows must escalate.
- **Plausibility:** net weight is not gross weight. Where both are available, gross below net signals possible interpretation/unit error and prompts validation rather than an automatic “fix.”
- **Port aliases:** include generally justified variants such as a verified spelling alias; record provenance. Do not learn aliases from hidden labels or merge ports based solely on similar text.

## 8. Comparison, verification, and roll-up

Compare only when both sides meet automated or operational comparability as applicable. Return MATCH, MISMATCH, or NOT_COMPARABLE; retain a cause for the latter.

Use three verification paths:

1. Grounded, type-valid strong deterministic difference: accept the mismatch.
2. Text near-difference: apply safe normalization and approved aliases.
3. Weak evidence, inconsistent parsing, or competing candidates: targeted independent extraction/validation, then review if unresolved.

Do not ask the same model the same question universally as a reliability ritual. Do not turn a clear mismatch into uncertainty merely because it is undesirable.

AI semantic equivalence is off in scored EVAL by default. If later proposed, restrict it to party/port near-matches, never numbers; use a deterministic prefilter, schema-valid EQUIVALENT/DIFFERENT/UNCERTAIN result, false-equivalence tests, and verified organizer mapping before enabling it.

Roll up using Contract §4.3. A known container mismatch may remain visible while a missing gross weight makes machine status NEEDS_REVIEW and exported defects empty. This is intentional.

## 9. Human reviews and operational resolution

Use Contract §§5–9 without alternative review enums or frontend-specific payloads.

- Readable documents and at most two distinct unresolved fields in the run permit field-level input/choice.
- Field order is canonical; SI precedes BL.
- Every choice includes NONE_OF_THESE; document choices identify target_role.
- More extensive gaps, no usable candidate, or exhausted budgets become external blocks.
- Technical failures create operator alerts, not business decision reviews.

For PROVIDE_VALUE and value SELECT_OPTION, validate field type and G1–G3. Grounded human values become DOCUMENT_CONFIRMED. If unsupported, return the grounding error and keep the review OPEN until the exact manual override is explicitly confirmed. The backend computes provenance and validates the bound confirmation.

Manual overrides are valid only for the operational comparison. Preserve them as ungrounded HUMAN values with their confirmation. A later dependent value must retain that lineage. One top-level “human edited” flag is insufficient when several fields have different origins.

After durable acceptance, recompute changed values plus dependencies:

- Consignee updates propagate to same-as-consignee notify party.
- Document choice invalidates every extraction associated with the changed assignment.
- Aggregated fields reconsider all contributing rows.
- Recomparison may expose a second review; effective status remains NEEDS_REVIEW until fully resolved.
- Acknowledgment records operational review resolution while staying BLOCKED_EXTERNAL.
- Successful operational comparison can finish OK or MISMATCH; machine assessment remains byte-for-byte unchanged.

Do not claim the business discrepancy is corrected merely because a MISMATCH verification run is COMPLETED. follow_up=CORRECTION_REQUIRED communicates remaining real-world work.

## 10. Durable state, run identity, and errors

Persistent concepts: Case namespace, immutable Run inputs/config/assessment, working fields/documents, Review, AcceptedDecision, PendingWork, History, and SubmissionSnapshot manifest. They may share a small number of database tables; relational normalization is not itself a product requirement.

A transaction must accept a decision, close its review, and record pending resumption together. Apply that record idempotently. Every write checks active run_id at commit time. Reprocess supersedes reviews and replaces the active run atomically.

One retry is allowed for a retryable failed work unit. A second failure becomes FAILED; permanent technical faults may fail immediately. Retain safe error text, step, attempts, correlation/run IDs, prior assessment, and any accepted decision. Send an operator notification through PRD 2 discovery.

After a crash, recover pending/interrupted work. If automatic retries are exhausted, provide a private operator recovery path for the same run's accepted decision; do not ask the user to enter it again. Starting a fresh run is a separate explicit operation and does not import prior human decisions into the automated baseline.

The MVP recovery from missing/unreadable source is private operator replacement/addition of immutable inputs and a new run. Replaying identical missing inputs is not recovery.

## 11. APIs, cloud security, and interaction integration

Implement exactly Contract §8. New create/reprocess/accepted decision work returns 202 only after durable recording. A duplicate create returns the existing active DEMO Case with 200. Duplicate decisions return 409. Repeated explicit reprocess creates another run, so clients must refetch after an uncertain response.

The dashboard and bot receive scoped access. Enforce demo safety across lists, direct document IDs, reviews, stats, and replay. A proxy-held token is not a security boundary by itself. Protect private EVAL processing and any EVAL document content independently of public route labels.

Expose original document bytes only after authorization. The bot uploads those bytes to Telegram; the browser uses a same-origin authorized viewer/download. No public storage bucket or bearer token in URLs.

Persist readable history for classification, parsing, AI fallback, verification, review creation, acceptance/application/rejection, retries, failures, supersession, and completion. Do not log credentials, hidden model reasoning, or unnecessary raw personal data.

## 12. Evaluation and submission

B owns the harness from B0. Use permitted participant data and self-evaluation only. Do not inspect organizer-only Docker contents or private ground truth. Reserve a representative held-out sample before tuning rules/prompts, and report when it is first evaluated.

The official problem statement makes the self-evaluation endpoint optional and says it is not the final assessment. We retain the harness, full-coverage export, and reproducible snapshots as project validation commitments. If no permitted endpoint is available, report that limitation and perform local schema, source-grounded, and held-out checks; do not invent evaluator scores. sample_submission.json supplies output shape and IDs, not labelled answers.

Text-based processing is the official baseline, with richer formats described as advanced work. This PRD deliberately commits to the formats present in the supplied bundle. Frontend simulation can proceed independently, but synthetic-only results cannot establish accuracy on those participant documents.

Golden tests cover match; single/multiple mismatch; each review reason; ambiguous numeric notation; mixed units; duplicate totals; party/address difference; same-as-consignee; blank both sides; non-BL category; manual override; and technical failure.

Validate:

- Classification macro-F1.
- Defect-F1 and end-to-end exact defect results.
- NEEDS_REVIEW precision/recall when provided by the permitted evaluator.
- Missing/duplicate output IDs and assessment completeness.
- Technical failures, escalations by reason, AI calls/assisted cases, latency, and cost.
- Held-out errors and known unsupported cases.

These metric names and earlier reported scoring weights are inherited findings, not new measurements. Preserve actual evaluator names/results in the report and distinguish benchmark scoring from the preliminary judging rubric. Do not invent baseline numbers or a pass percentage.

Snapshot generation reads successfully finalized automated EVAL assessments, even if workflow is awaiting a human. It fails closed when any required ID lacks a valid assessment. Prior success reuse requires exact input/config alignment and an explicit manifest. No technical exception is converted into unreadable; no human resolution or DEMO result is exported.

Write a new immutable snapshot at each evaluated milestone. Keep required IDs, input/config/run mappings, snapshot hash, evaluator response, and reuse/failure notes together for reproducibility.

## 13. Throughput and cost plan

Use bounded concurrency and bounded model calls, configured from observed quotas. Start with one worker for correctness; increase processing concurrency only after run-guard tests pass.

Cache parsed content by document hash plus parser version. Cache machine extraction by input, model, prompt, and policy identity; never reuse a human override as automated output. Repeated requests must not share mutable run state.

Batch deterministic work, call AI only for unresolved classification/extraction, and apply timeouts plus the single retry policy. Track actual calls, active processing latency, rate-limit events, and cost when available. Establish batch-runtime and budget expectations from B0 measurements rather than guessed targets.

## 14. Phase-by-phase implementation plan

B0 and F0 run in parallel. The first real human handshake is a gate immediately after the B1 vertical slice; full dataset accuracy can continue afterward.

| Phase | A delivers | B delivers | Exit evidence |
|---|---|---|---|
| **B0 — Feasibility, contract, cloud, harness (MUST)** | Authorized format inventory; participant mapper with null receipt time; representative parser spike; held-out split; policy questions | Deployed cloud skeleton; persistent run model; v2.1.1 types/validator; baseline export/evaluation harness; scoped credentials | Cloud health/readiness; one participant record ingested without a guessed timestamp; known/unknown receipt fixtures for C; documented baseline and external verification gates |
| **B1 — Minimal scored core (MUST)** | Classification; required format paths; seven-field extraction; minimum G1–G3; normalization/comparison; one real AI fallback | Durable jobs; Case APIs; assessment finalization; minimal review/decision transaction; fail-closed adapter | Real cloud Case renders; grounded match/mismatch; one honest review fixture is produced; real AI evidence |
| **B1 integration gate — First real review handshake (MUST)** | One targeted human-resolvable uncertainty and dependency recomputation | Review retrieval; durable acceptance/resumption; unchanged machine assessment | Real backend → dashboard/Telegram review → human decision → backend resumes → dashboard reflects operational result |
| **B2 — Coverage and accuracy (MUST)** | Broader format/layout coverage; context checks; aggregation; aliases; targeted mismatch verification; field-policy fixtures | Full-batch validation; held-out report; snapshot validation; runtime/cost measurements | Required ID set processed; complete candidate snapshot or explicit failing-ID report; errors investigated; no fabricated fallback |
| **B3 — Full review and reliability (MUST)** | Sequential reviews, document assignment, override lineage, dependency invalidation | Race/crash/stale-run handling; finite budgets; recovery; all endpoint access tests; notification discovery | AC-01–AC-15 pass; no lost accepted decisions; no public EVAL leakage; restart-safe resumption |
| **B4 — Demo and submission hardening (MUST)** | Stable labelled fixtures; final extraction limitations and reproducible config | Release snapshot/manifest; regression and validation report; cloud rehearsal; architecture/log evidence | Repeated real demo; published safe prototype; reproducible release artifacts; C has technical content for packaging |

B2 SHOULD refinements begin only after its MUST validation path works. OCR/vision and semantic AI remain optional afterward. No imposed clock-time freeze or invented early deadline is part of this plan; order follows readiness and the organizer's actual submission requirements.

## 15. Acceptance and definition of done

All applicable Contract AC-01–AC-19 scenarios must pass. In addition:

- All seven fields follow the field-policy table; unrelated digits never ground a value.
- Three required document formats beyond TXT are exercised on representative participant-facing inputs.
- Blank and absent values are not silently matches.
- Missing email receipt metadata maps to null without blocking processing or export; malformed supplied timestamps and omitted required API keys are rejected by the appropriate validator.
- Reprocessing preserves initial Case.created_at and does not replace unknown receipt time with the new run's timestamp.
- A full EVAL export contains exactly the authorized required IDs, or generation clearly fails with a diagnostic report.
- Automatic and operational status are distinguishable in the API and immutable snapshot.
- Crash/race tests prove transactional acceptance and commit-time run guards.
- A meaningful AI path and actual cloud processing are demonstrated.
- A mismatch-only case triggers correction follow-up without an invented review.
- Final validation report includes observed metrics, held-out results, unresolved organizer-dependent questions, and limitations.
- No core presentation path relies only on mock results.

## 16. Integration handoff and changes from the prior PRD

A/B give C complete validated fixtures, scoped API credentials, endpoint behavior, runnable demo-safe cases, safe document access, and error scenarios. C provides real UI/bot decision requests and routing tests. Both sides use the same runtime validator.

This revision removes actionability-based scored skipping, completed-workflow-only export, fake technical-failure output, weak human grounding, and “rerun only one step” language. It moves grounding and meaningful AI into B1, brings review integration forward, defines field policies, and makes override/retry/reprocess behavior implementable. The implementation remains small: REST, polling, transactional state, and one durable worker.

The v2.1.1 refinement incorporates the inspected participant input shape, nullable receipt-time mapping, system timestamp semantics, and related validation. It supersedes the temporary recommendation to block participant conversion on missing received_at. Other unresolved organizer interpretations remain open; this amendment does not settle no-attachment intent or numeric/text comparison policy through assumption.
