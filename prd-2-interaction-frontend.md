# PRD 2 — Interaction / Frontend Layer

**Version:** 2.1.1-aligned · 19 September 2026  
**Authority:** [Shared System Contract v2.1.1](./shared-system-contract-v2.1.1.md) defines all data, review, decision, state, API, and access semantics.  
**Companion:** [PRD 1 — Backend Automation & Intelligence Layer](./prd-1-backend-automation-intelligence.md)  
**Owner:** C — Interaction + Submission; B supports APIs/access; A supports evidence.

**Selected Telegram framework:** Nous Research Hermes Agent. This is an interaction-layer implementation choice under Shared Contract v2.1.1; it does not change the shared API or backend ownership. Pin the tested Hermes release/commit during F2 setup.

## 1. Objective, USP, and UX philosophy

Deliver a responsive dashboard and proactive Telegram experience so shipping staff do not have to watch a workflow continuously. The system contacts the right person when a decision, correction, or external action is needed.

**“Don’t monitor AI. Let it chase you.”**

Use the simplest safe interaction:

- Automatic completion requires no human action.
- A concrete choice uses buttons.
- A limited missing value uses targeted input with the source document.
- A complex issue opens a responsive case detail page.
- An external block explains what document/action is needed and offers acknowledgment.

Some problems require another party to send a corrected document. Telegram cannot manufacture missing evidence, and acknowledging a problem does not resolve document verification. The interface must make this clear without undermining the value of proactive notification.

The dashboard is a control centre, review surface, and history viewer. It must independently resolve every supported review because judges may not have started the Telegram bot or joined its allowlist.

## 2. Ownership and scope

The interaction layer owns presentation, communication, local input/confirmation state, delivery records, routing, and translating human intent into DecisionRequest. The backend owns classification, evidence truth, grounding, comparison, workflow transitions, review creation, accepted decisions, and final outcomes.

Never directly edit backend storage, mark a candidate grounded, create a local shipping verdict, or rewrite machine_assessment. A successful POST means durable acceptance, not completed processing.

### MUST

- Three responsive screens: overview, case list, case detail.
- Display original machine assessment separately from current operational outcome.
- Render all seven field comparisons and per-value provenance/evidence.
- Resolve CHOICE, VALUE_INPUT, and ACKNOWLEDGE through the dashboard.
- Proactive Telegram reviews with buttons, explicit routed input, original documents, and dashboard deep links.
- Exact manual-override confirmation in dashboard and Telegram.
- Code-first parsing for canonical numeric input and explicit options.
- Persistent message routing, delivery records, update progress, and confirmations.
- One notifier instance, bounded flood control, digest behavior, and deduplication.
- Correction notices for confirmed mismatches and operator-only technical-failure notices.
- Correct PROCESSING/accepted/pending/error/stale behavior and backend refetch.
- Trusted actor identity and server-enforced demo-only access.
- Validated contract mocks, early real-backend integration, labelled demo fixtures, and repeatable rehearsal.

### SHOULD

Natural-language Telegram AI interpretation; improved explanations; useful live pipeline display with Code/AI/Human labels; richer queue filtering; measured interaction reliability. Natural-language AI is consistently SHOULD, not a hidden dependency of the MVP.

### OPTIONAL / stretch

Evidence crops/images, voice input/output, WhatsApp, browser replacement uploads, streaming updates, richer animations. Voice/WhatsApp must eventually use the same structured backend decision boundary.

### Out of scope / high-risk distractions

3D “Jarvis” decoration, multi-channel orchestration frameworks, autonomous business emails, general chat assistant behavior, public access to organizer EVAL data, and a claim that every exception can be solved by phone.

## 3. Core user journeys

### A. Background success

A real approved fixture is processed. The overview updates via polling. The user receives no decision request for a clean automatic match. The case shows machine OK, operational COMPLETED, and zero reviews for that run.

### B. Confirmed mismatch

The backend completes a dependable comparison and sets CORRECTION_REQUIRED. Telegram sends a concise discrepancy notice, such as “Container count differs: SI 3, BL 4. Correction required,” with a case link.

This is a notification, not a CHOICE review. Do not invent approval buttons that change the shipping result. The UI explains that verification completed but external correction remains.

### C. Human resolves a limited uncertainty

A review asks for a specific field and side, for example BL gross weight in kg. Telegram provides source context, the original document, and a detail-page link. The user replies to that review message or explicitly selects it.

The client parses and previews the proposed value. The backend checks type and grounding. A grounded value can be accepted as document-confirmed; an unsupported value requires exact manual-override confirmation. After 202, show “Decision accepted; processing continues.” Poll until the backend reports completion, another review, external block, or failure.

The dashboard continues showing the immutable automated NEEDS_REVIEW alongside the human-resolved operational result. Do not label that automated assessment as wrong or replace it.

### D. Document-role choice

The backend supplies a DOCUMENT/CHOICE review with target_role and candidate documents. Display “Which document is the SI?” or “Which document is the BL?” with filenames and safe document access.

Submit only the selected option ID. NONE_OF_THESE is always visible. Backend validates assignment and reruns dependent extraction. The frontend does not assume all existing fields remain valid during this work.

### E. External block

A missing document, wholly unreadable source, excessive unresolved fields, or exhausted review budget yields BLOCKED_EXTERNAL. Explain what must happen next: obtain the specified source through the operator workflow.

Acknowledgment closes the review and stops pending-review reminders; the case remains blocked. Do not show a success/completed badge. A corrected source and a new run are required for recovery.

### F. Two sequential reviews or a race

After the first review, the case may still be NEEDS_REVIEW and show a second OPEN review. Show the new field/side clearly. The previous reply/confirmation stays bound to the old review.

If Telegram and dashboard act simultaneously, only one acceptance succeeds. On 409, refetch and display the actual latest state. Do not replay the old value into the new review.

### G. Technical failure

Show a safe failure explanation, run/step context, and an operator recovery affordance only where authorized. Notify the team/operator. If a decision was already accepted, say it was retained; do not ask the business user to re-enter it.

## 4. Dashboard information architecture

### Screen 1 — Overview

Show latest-run DEMO metrics: total cases; machine OK/MISMATCH/NEEDS_REVIEW; workflow distribution; pending decisions; acknowledged external blocks; auto-completed runs; AI-assisted runs; visible failures.

Use Contract §12 definitions. “Auto-completed” means the current run completed with zero reviews created in that run. Do not mix all historical replays into current counts.

The live pipeline, if implemented, derives from actual backend history and displays Code, AI, and Human contributions. It is an explanation of real activity, not a decorative progress animation. Never claim a stage finished without backend evidence.

### Screen 2 — Case list and review queue

Show sender, subject, category (including “Classifying” for null), workflow, machine result, operational result, mismatch count, last update, and pending review indicator.

Filters use the shared API: workflow_status, category, final_status, has_open_review. Public users cannot select EVAL. Review queue and external-block views may share this screen; there is no requirement for extra navigation pages.

A “Process this email” control uses approved fixtures only. “Replay / Reprocess” starts a new run and clearly resets the active operational view. Disable while its request is pending; after timeout refetch instead of automatically creating another run.

### Screen 3 — Case detail

Include:

- Email header, active run identifier, safe fixture label, and workflow.
- Frozen “Automated assessment” and separate “Current operational outcome.”
- Seven-field SI/BL table with raw values, normalized values where helpful, comparison, and evidence.
- Per-value source label: extracted, human document-confirmed, or manual override.
- Current review action panel or external follow-up explanation.
- Authorized original-document viewer/download.
- History timeline, accepted/processing status, and safe failure details.
- Responsive layout usable from the Telegram deep link.

Unknown/null values render as unknown, never zero or MATCH. A manual override is visibly ungrounded; a human document-confirmed value can show its genuine source evidence. Evidence may include several cells, rows, pages, or paragraphs.

email.received_at may be null in every workflow state under v2.1.1. Display “Received time unavailable,” or omit that optional display row; never render an invalid date or substitute another timestamp. Label Case.created_at as “Case created” and updated_at as “Last updated.” Use those system timestamps for existing activity ordering; do not add receipt-time sorting that guesses a value for unknown dates. If receipt-time sorting is later introduced, define a consistent unknown-last policy explicitly. Date formatting must handle null before invoking a date parser.

During PROCESSING after a decision, label prior fields/outcome as “Last result; updating.” During FAILED, show the failure prominently even if an earlier assessment remains available. completed_at is displayed only for operational completion.

## 5. Review widgets and decision confirmation

| Mode | UI | Request |
|---|---|---|
| CHOICE | Candidate buttons with context/evidence and mandatory NONE_OF_THESE | SELECT_OPTION + option_id |
| VALUE_INPUT | Explicit field/side label, unit/type guidance, input, preview, confirm, “I can’t tell” | PROVIDE_VALUE + field/side/value, or ACKNOWLEDGE |
| ACKNOWLEDGE | Explain external action; acknowledge button | ACKNOWLEDGE |

Use backend allowed_actions. Do not infer extra actions from labels. All requests include review_id, run_id, channel, and trusted actor context as required by the contract.

For typed values:

1. Route to an explicit current review.
2. Parse with code and validate obvious input shape.
3. Show canonical interpretation: field, side, value, and units.
4. Obtain ordinary submission confirmation.
5. Submit for backend validation.
6. If evidence is unsupported, show an explicit override prompt.
7. Bind override confirmation to actor, review_id, run_id, field, side, and proposed_value.
8. Submit the exact confirmed tuple.
9. Refetch after acceptance; wait for the backend outcome.

Example override copy: “This value could not be verified against the BL gross-weight evidence. Use 21,707 kg as a manual override for this review?” Provide Confirm override and Cancel. Do not use a generic reusable “Are you sure?” prompt.

Changing the proposed value, review, side, or run clears confirmation. Reject old confirmation callbacks after supersession. Candidate selection does not bypass grounding: an unsupported field candidate triggers this same override path.

Ordinary document choices can use their explicit button as confirmation; uncertain AI interpretations must always be previewed before submission.

## 6. Telegram MVP and secure identity

### 6.1 Hermes integration architecture

Use **Hermes Agent as the Telegram gateway and agent runtime**, with a project-specific shipping-review integration. The dashboard remains the custom three-screen application in this PRD; adopting Hermes does not replace it with Hermes's own administration dashboard.

```text
Telegram user
  ↔ Hermes Telegram gateway
  ↔ shipping-review integration: routing, parsing, confirmation, API client
  ↔ Shared Contract REST API (simulator initially; real backend at integration)

Dashboard ↔ its API adapter ↔ the same Shared Contract REST API
```

Hermes supplies Telegram connectivity and extension mechanisms. Our integration must implement and verify shipping-specific review routing, durable delivery mappings, confirmation binding, and contract requests. Hermes conversation history or memory must never substitute for authoritative Case/Review records.

Use supported plugin/tool/command extension points where they fit. Keep the backend API client independent of Hermes so the simulator and future real backend expose the same interface. Any custom callback or adapter extension must be documented and tested against the pinned version; do not assume generic plugin support proves every required Telegram callback path is available.

The project integration must:

- Fetch authorized cases/reviews and documents through the shared API.
- Bind Telegram sender/chat/message identity to persisted review_id and run_id records before processing input.
- Handle explicit buttons and canonical numeric input deterministically, without requiring model interpretation for the MUST path.
- Persist exact confirmation proposals; build DecisionRequest only after an authenticated human action matches the active proposal.
- Submit decisions through the backend's validation and durable-acceptance endpoint; never mutate case storage directly.
- Support the single notifier's outbound review, correction, and operator messages, including returned message IDs and original-document delivery.

Model-facing tools may propose interpretations or retrieve scoped context. They must not manufacture an actor identity, confirmation, or approval. If a submission tool is exposed, its handler must independently require persisted, matching human-confirmation evidence; model-generated `confirmed=true` is insufficient.

Hermes generic clarification and command-approval dialogs are not shipping-review approval records. In particular, a generic next-message answer or bare “yes” must not bypass the explicit reply/selection and exact override-binding rules in §§5–7. Implement domain-specific controls where those rules cannot be satisfied by built-in prompts.

Run one Hermes inbound update consumer per bot token. Do not launch a second independent getUpdates loop alongside Hermes. The existing application notifier polls the backend for pending work and uses the tested Hermes transport integration for delivery; do not depend on an LLM periodically deciding to look for reviews. Keep restart recovery and delivery deduplication in durable application records.

Use a dedicated application profile with only the tools and commands this workflow needs. Disable unrelated shell, file-editing, browser, scheduling, or delegation capabilities for business users. Keep credentials server-side, and enforce backend DEMO scope independently of Hermes's Telegram allowlist.

### 6.2 Setup and user access

The user starts the bot and must be allowlisted/authenticated before receiving case data or submitting decisions. Persist Telegram chat and actor mappings. Unknown users receive setup guidance without case/document disclosure.

A review message includes case subject/short ID, field/side or target role, why attention is needed, relevant evidence, known discrepancy context, allowed action buttons, and a responsive dashboard link. Send the original source document where needed using server-side retrieval and sendDocument.

If document delivery fails, keep the review available and offer the authorized dashboard link; do not claim the file was sent. Retry notification delivery with bounded backoff. Never put private bearer tokens in links or bot messages.

The dashboard remains fully usable without Telegram onboarding. A public demo may use a scoped guest identity tied only to safe fixtures; do not permit a browser-supplied actor_id to impersonate another user.

## 7. Reply routing and free text

Persist (chat_id, message_id) → case_id/review_id/run_id. Buttons may use short opaque tokens backed by persisted mappings; do not rely on oversized Telegram callback payloads.

Valid input routing requires:

- Reply-to the specific mapped review message; or
- Explicit case/review selection through the bot UI.

A bare value such as “21707” must not be applied merely because only one review is currently OPEN. Ask the user to select/reply to the intended review. This also applies immediately after closing a previous review.

Before submitting any action, validate mapping ownership and actor; fetch current backend state when necessary. Stale or CLOSED reviews produce a clear “This review has already been handled or replaced” message and a current case link.

A bare “yes” is meaningful only as a reply/callback to an exact pending confirmation. It never authorizes another review's proposal. If the user changes the value, cancel the previous confirmation and create a new bound proposal.

## 8. Code-before-AI parsing and optional natural language

Deterministic parsing handles option IDs/buttons, integers, explicit kg values, supported units, and simple acknowledgment. Use the same documented canonical interpretation as the backend; the backend is always authoritative.

Ambiguous “1,234” must not be guessed if locale/context does not settle its meaning. Preview clear unit conversion, and reject malformed/negative values before submission while still relying on server validation.

Natural-language AI is SHOULD. If implemented, it returns only a structured proposed action, target, and value for the selected review. It cannot submit directly or override backend allowed_actions.

Examples such as “I think the BL says twenty-one thousand seven hundred and seven kilos” may produce a proposed 21707 kg, but require explicit preview/confirmation. “Use the second one” is valid only when the review has an explicit ordered candidate list and the intended option is unambiguous.

If interpretation is uncertain, ask a focused clarification or show buttons/input. Do not invent a value, case, side, or review. Keep voice and unrestricted conversation outside MVP.

## 9. Proactive discovery, delivery, and flood control

Use one notifier instance. Poll authorized current-run reviews and cases every 3–5 seconds, with backoff on failures. Telegram inbound updates use long polling with durable update progress.

Hermes owns that inbound Telegram polling lifecycle. Verify how the pinned version persists/replays updates and add application-level processed-update records as required. Hermes session resets must not erase shipping-review mappings, pending confirmations, or delivery state.

Persist notification delivery, message mappings, processed updates, and pending confirmations. Do not keep these only in memory. Review delivery is keyed per run/review/recipient; mismatch and technical-failure delivery per run/type/recipient.

| Event | Audience | Behavior |
|---|---|---|
| OPEN actionable review | Allowed business/demo user | Individual decision message with source/context |
| OPEN external-block acknowledgment | Allowed business/demo user | Explain external action and acknowledge |
| Settled effective MISMATCH | Allowed business/demo user | Correction-required notice, no invented decision review |
| FAILED technical processing | Team/operator | Failure notice and diagnostic case link |

A review containing known mismatches mentions them in context. Send the standalone mismatch notice when operational comparison settles, once logically per run. Technical failure does not become a business troubleshooting question.

Recommended initial flood-control configuration: at most one outbound individual case notification per recipient every three seconds, with at most three immediate messages per polling burst. Queue excess work and issue a summary digest no more than once per recipient per minute when the queue meaningfully changes. These are tunable delivery settings, not new contract state.

A digest does not mark individual reviews notified. It offers case selection, and individual messages are marked only after actual delivery. Recheck OPEN/active-run status before sending queued work. Avoid endlessly resending unchanged digests.

Delivery order: send → persist message mapping/delivery → POST notified. Persisting a successful send lets restart retry only the marker when appropriate. A crash before send acknowledgment persistence may cause a duplicate; accept this documented limitation. Backend decision atomicity prevents duplicate application.

If a backend response is lost, query case state before retrying a decision. Delivery recovery must not cause automatic retries of reprocess.

## 10. Frontend state and API consumption

The server Case is authoritative. Local UI state is limited to loading/error, selected review, input draft, proposed canonical value, confirmation, request pending, and polling progress. Do not create a second shipping workflow state machine in the client.

Use one API adapter with mock and live implementations. Both return the same Case/CaseSummary/Review/Stats types. Handle nullable category/classified_by during early processing.

| API use | UI behavior |
|---|---|
| GET cases/stats/detail | Poll every 3–5 seconds; display last successful data with stale indication on failure |
| POST cases | 202 new processing or 200 existing run; render actual returned state |
| POST reprocess | 202 new run; clear old local drafts/confirmations; refetch after uncertain timeout |
| GET reviews | Only authorized current-run reviews; preserve backend ordering/targets |
| POST decision | 202 means accepted and resuming; disable old review actions and poll |
| POST notified | Interaction service only; never triggered by a dashboard GET |
| GET document content | Authorized proxy/viewer; no raw private storage URL |

Use request/run identity when processing asynchronous responses. Discard an older response if a newer run has already been rendered. On reprocess, reset local review bindings so old inputs cannot migrate to a new run.

## 11. Error states and recovery

| Situation | User-facing response / action |
|---|---|
| 409 closed review or stale run | Explain it was handled/replaced; refetch; do not retry against new review |
| 422 invalid value/option/action | Keep input visible, show targeted correction, no optimistic success |
| Grounding/override required | Show exact bound manual-override prompt |
| Invalid confirmation | Clear stale proposal and require confirmation of the current tuple |
| 401/403 | Stop protected reads; show access/setup state without leaked details |
| 404 | Case/review/document unavailable in this scope |
| 429/network/5xx | Back off; show stale data and retry state; retain draft safely |
| Decision timeout | Refetch to determine whether accepted; avoid duplicate human work |
| Reprocess timeout | Refetch, never automatically start another run |
| Resumption failure | Show retained accepted decision and operator recovery path |
| Bot document/send failure | Keep review available; offer dashboard and bounded delivery retry |
| Empty review queue | Clearly state no pending decisions; do not hide acknowledged external blocks |

Server-supplied error text must be safe for display. Do not expose provider credentials, private object paths, or EVAL content in public errors.

## 12. Demo safety, fixtures, and mock strategy

Public and Telegram surfaces use explicitly demo-safe fixtures. A run marked DEMO does not grant permission to expose organizer documents. Server checks cover every endpoint and referenced document; frontend hiding of EVAL navigation is not sufficient.

Begin with the full contract fixture set. Validate mocks with the shared runtime validator, including seven fields for settled BL cases, required NONE_OF_THESE, review targeting, null handling, evidence lists, and provenance.

Read the official problem statement and participant README and inspect representative input layouts as F0 reference material. The inspected participant bundle contains 520 records with no received_at; raw records have email_id, from, subject, body, and attachments. The dashboard still consumes the shared Case API rather than raw inbox records.

Build clearly labelled synthetic fixtures reflecting observed multiline addresses, equivalent field labels, container expressions, weight formatting, and supported document formats. Keep their documents and evidence internally consistent. Include both explicitly fictional known receipt times and received_at=null in processing and settled cases. Participant-derived records must retain null where the source supplies no time. Do not use sample_submission.json placeholders as expected classification results.

F0 uses a stateful, deterministic simulated backend behind the API adapter, with resettable scenarios and observable processing updates. Emit schema_version="2.1.1" throughout and validate against the same shared schema; do not maintain a provisional timestamp schema. Missing source receipt time no longer requires a blocking mapper discrepancy after this amendment is adopted.

F0 covers the shell, viewing, navigation/filtering, valid fixtures, loading/error states, and simulated processing. Full decision submission and confirmation journeys remain F1. Simulator acceptance and real-backend acceptance are separate milestones: neither simulation nor representative fixture design proves participant-data extraction accuracy. Private real-data processing and integration checks remain necessary later; no real dataset needs to be exposed publicly to complete F0.

Required presentation fixtures:

1. Automatic clean match.
2. Confirmed mismatch and correction notice without review.
3. Human-resolvable value/candidate uncertainty with actual backend processing.
4. External block and honest acknowledgment.
5. At least one clearly labelled synthetic hero fixture if the participant dataset lacks a dependable interactive example.

Synthetic inputs may create the scenario, but the demonstrated classification/extraction/review/resumption must execute through the real backend. Do not portray precomputed mock output as live processing. Rehearsals use new DEMO runs while scored snapshots remain untouched.

## 13. Interaction validation and metrics

Create a small repeatable test set before optional natural-language work. Cover at least these cases:

| Input / event | Expected behavior |
|---|---|
| Explicit positive integer in selected count review | Preview canonical count; submit after confirmation |
| Clear kg/metric-tonne value | Correct unit conversion preview |
| Ambiguous decimal/group separator | Clarify; no submission |
| Negative/zero or malformed numeric value | Reject as invalid |
| Bare number without reply/selection | Request routing; no decision |
| Reply to old review | Reject stale route |
| “Yes” without bound confirmation | Clarify; no decision |
| Changed value after confirmation | Clear old confirmation |
| Unsupported candidate choice | Require override confirmation |
| NONE_OF_THESE / “I can’t tell” | Submit escape; backend blocks externally |
| Two reviews in sequence | New review target; old reply never migrates |
| Simultaneous dashboard and Telegram action | One accepted, one 409 |
| Restart after send / after decision acceptance | Recover delivery/routing; no duplicate decision |
| Unauthorized actor or guessed EVAL document | Denied without disclosure |
| Uncertain optional AI interpretation | Preview/clarify; never automatic submission |
| received_at=null in a processing or completed case | Valid payload; unknown receipt time shown honestly; no invalid date or blocked screen |
| Explicitly fictional known receipt time in a synthetic fixture | Correctly formatted receipt time, separate from case creation/update labels |
| Reprocess a case with unknown receipt time | Receipt remains unknown; case creation time remains stable; current run time advances |

If natural-language AI is implemented, add paraphrase, correction, negation, multiple-number, wrong-side, and malicious instruction examples. Record interpretation accuracy, clarification rate, and unsafe submissions. Wrong-target or unconfirmed override submission is a release-blocking defect, not an acceptable average.

Use backend-defined metrics for the dashboard. Report interaction sample sizes and observed completion times honestly. Do not claim a mobile-resolution rate from a tiny demo. Keep EVAL evaluation metrics separate from public DEMO operational statistics.

## 14. Phase-by-phase implementation plan

F0 proceeds alongside B0. F1/F2 basic review handling integrates immediately after the B1 vertical slice, before B2 expands accuracy work.

| Phase | Work | Deliverables and exit criteria |
|---|---|---|
| **F0 — Deployed shell and valid mocks (MUST)** | Participant structure review; API adapter; stateful simulator; synthetic source documents; three-screen responsive structure; v2.1.1 validator; safe hosting/proxy setup | Deployed dashboard renders all contract mock states, including null classification and known/unknown receipt time; resettable scenarios; no guessed timestamps or private token in browser |
| **F1 — Dashboard review flow (MUST)** | All widgets; raw/evidence/provenance views; machine vs operational status; exact override confirmation; error/refetch behavior | Every review mode works on mocks and then a real backend Case; dashboard alone completes a review |
| **F2 — Hermes setup and early handshake (MUST)** | Pin Hermes version; configure dedicated profile, bot and allowlist; implement shipping-review integration; prove callbacks, explicit reply routing, file delivery, persistent mappings, and bound confirmations | Simulator handshake first; then real backend review → Hermes Telegram message → accepted decision → backend resumption → dashboard update; durable acceptance visible |
| **F2 completion — Proactive reliability (MUST)** | One Hermes inbound consumer and one backend notifier; delivery/update records; flood limits/digest; mismatch/operator notices; stale-run, session-reset, and process-restart behavior | Sequential/race/stale/restart tests pass; Hermes reset cannot lose domain routing; digest does not mark individual delivery; public EVAL access denied |
| **F3 — Hermes interpretation improvements (SHOULD)** | Optional natural-language interpretation through Hermes; structured proposals; ambiguity handling; test set; useful real pipeline view | Measured interpretation results; no automatic ambiguous/wrong-target actions; MUST paths remain deterministic and usable |
| **F4 — Rehearsal and submission (MUST)** | Full real integration, replay, responsive checks, safe fixture labels, video/script, README/slides/link checks | Repeatable live flow and backup recording; validated scoped metrics; all submission links work; no mock-only core demonstration |

Manual-override confirmation belongs in F1 and F2, not deferred to F3. If F3 is skipped, the MVP remains complete through buttons, explicit values, and confirmation.

F0 needs no running Hermes instance, Telegram token, or model credentials. Build the custom dashboard and contract-compatible simulator first, using ui-ux-pro-max for design. Record Hermes as the selected future Telegram integration; do not couple dashboard components to Hermes internals.

At the start of F2, perform a bounded integration spike against the pinned Hermes version: receive authenticated updates, preserve reply/callback metadata, render domain buttons, send documents while capturing message IDs, submit one confirmed simulator decision, and restart without losing routing. Record supported extension points and any adapter work required. A successful simulator handshake does not satisfy the real-backend exit criterion. If an essential capability cannot be implemented through the selected extension path, report the specific blocker instead of silently replacing Hermes or weakening the contract.

After C's MUST implementation works, C helps test failures/integration and coordinates submission packaging. A supplies processing details; B supplies architecture/cloud/evaluation evidence. Do not spend spare time on visual polish while core validation remains incomplete.

## 15. Acceptance and definition of done

All relevant Shared Contract AC-01–AC-19 pass, with particular emphasis on simultaneous decisions, stale replies, exact override binding, restart recovery, external acknowledgment, and access denial.

The interaction MVP is done when:

- A real cloud case renders across the three dashboard screens.
- The dashboard independently handles every review mode.
- Known and unknown receipt timestamps display correctly in processing and settled states; operational timestamps are accurately labelled and never substituted for receipt time.
- Telegram proactively delivers a real review with usable source access.
- A routed user response and any necessary bound override confirmation reach the backend safely.
- 202 acceptance is visibly different from final completion.
- The updated operational result appears while the frozen machine result remains unchanged.
- A second review cannot consume an old reply or confirmation.
- A confirmed mismatch produces correction notification without a review.
- Technical failures notify operators and preserve accepted user input.
- All public/bot accesses remain within approved DEMO data.
- Delivery and routing survive restart with documented at-least-once notification behavior.
- Hermes session reset and gateway restart preserve application review bindings; generic clarification answers and model-generated approval flags cannot submit unconfirmed decisions.
- Exactly one inbound consumer uses the bot token, and required structured actions work without an LLM deciding whether to execute them.
- Replay runs the real pipeline, and synthetic fixtures are labelled.
- Documentation, video, prototype, and repository links are verified before submission.

## 16. Submission evidence and future extensions

C coordinates the public prototype, repository, technical documentation, architecture explanation, demo video, and final link checks. Use distinct evidence for architecture, working core, technology integration, validation, problem understanding, innovation, and practical value rather than repeating one screenshot for every rubric item.

The pitch explains proactive attention, honest external blocks, and deterministic/AI/human responsibilities. It uses measured counts and explicit limitations. Optional future work includes a real mailbox adapter, OCR/vision, WhatsApp, voice, and controlled source replacement; these must retain the same backend-owned decision contract.

## 17. Changes from the prior PRD

Natural-language AI is consistently SHOULD. Manual confirmation moves into the earliest core phases. Routing is explicit and persisted; bare values are never assigned to the only current review. Digests do not mark individual reviews delivered. Mismatch and technical-failure notices are distinct from decision reviews. The dashboard displays intermediate resolutions and retained decisions honestly, and public data restriction is enforced by the server. The first real handshake moves ahead of broad accuracy tuning, while all three dashboard screens and submission ownership are retained.

**Framework selection update:** Hermes Agent is now the required Telegram gateway/agent runtime. F2 adds the shipping-review integration and a version-specific feasibility check; F3 may use Hermes for natural-language proposals. F0 remains independently implementable with the simulated backend. The shared contract and PRD 1 remain framework-independent.

**v2.1.1 data-alignment update:** Adopt nullable receipt time, preserve system timestamp meanings, and test both timestamp variants. Ground F0 synthetic fixtures in observed participant structures while retaining the simulator boundary. This supersedes the temporary timestamp-blocking workaround and any proposed provisional simulator schema. Hermes selection and the existing F1/F2 integration requirements remain in force.

## 18. Hermes reference documentation

Official documentation consulted for this selection:

- [Telegram integration](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/telegram): Telegram setup and interaction capabilities, including generic clarification prompts. These are framework features, not evidence that our domain-specific review invariants are already implemented.
- [Build a Hermes Plugin](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins): supported custom tools, commands, and hooks for application integration.
- [Toolsets reference](https://hermes-agent.nousresearch.com/docs/reference/toolsets-reference): configurable tool availability; restrict the application profile to its intended workflow.

The architecture and additional checks above are project requirements inferred from Shared Contract v2.1.1, not claims of out-of-the-box Hermes guarantees. No Hermes installation or integration test has been performed as part of this PRD update.

