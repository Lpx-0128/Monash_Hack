# PRD 3 — Voice & Attention Orchestration Layer

**Version:** v2.1.2 target-aligned · 20 September 2026  
**Status:** Draft for coordinated implementation; transport spike completed, real-backend voice integration pending.  
**Authority:** [Shared System Contract v2.1.2](./shared-system-contract.md).  
**Companions:** [PRD 2 — Interaction / Frontend Layer](./prd-2-interaction.md) and [PRD 1 — Backend Automation & Intelligence Layer](./prd-1-backend.md).  
**Owner:** C — Voice adapter, attention policy and PRD 2 integration; B — API/access/version adoption; A — evidence/grounding integration review.

This is a separately gated extension to the working Telegram + Hermes and dashboard product. Backend truth and workflow execution remain unchanged. The v2.1.2 target contract must be adopted before real VOICE decisions; this document does not claim backend readiness or team approval.

## 1. Recommendation and evidence

Proceed with a limited voice demo implementation. The transport and a deterministic confirmation flow are feasible on the user's Malaysian handset. Keep real decision submission gated on the coordinated contract amendment and backend integration tests below.

| Tested | Evidence and limit |
|---|---|
| System calls user | Outbound call reached the handset and ran the custom speech prompt and response. |
| User calls system | User reported dialing the US Twilio trial number and hearing the speech echo; endpoint logs show the subsequent prompt and speech callback. Logs did not independently record direction. |
| Speech input and response | Actual transcripts were returned. The first numeric test produced `2177 kilograms` instead of the intended 21,707. Numeric reliability is not established. |
| Choice and explicit confirmation | A live call logged exactly one synthetic proposal: option A, 21707 kg, confirmed=true. |
| No backend mutation | That proposal recorded backend_submitted=false and contract_validated=false. It was not a DecisionRequest accepted by the real backend. |
| Negative-path checks | Local tests covered ambiguity, silence, refusal, premature confirmation, expiry, and duplicate confirmation. These were software tests, not additional live phone trials. |

The spike used Twilio speech gathering and deterministic code, not Hermes reasoning or an LLM. It used fictional values, not a demonstrated extraction result from participant Case 055. The temporary services were stopped afterward. The spike's temporary capability URLs and in-memory sessions are not production authentication or durable routing.

## 2. Product direction and boundaries

**“Don't monitor AI. Let AI chase you — and when you need AI, just call it.”**

The interaction layer helps shipping staff handle exceptions without continuously watching a dashboard. Voice is the preferred conversational mode when it can safely obtain the needed input. Telegram provides text, buttons, documents and visual evidence. The dashboard provides full context, investigation and independent review completion.

**Voice-first, screen-optional does not mean every decision can be made without evidence.** Speaking an option does not establish that it is correct. If selecting the correct candidate requires inspecting a source, ask for that inspection or defer. Do not turn an unreadable scanned number into a voice-only guessing exercise.

The backend owns classification, grounding, comparison, review creation, accepted decisions and workflow execution. Voice, Telegram and dashboard present authorized information and submit structured human intent. The voice service must not write backend storage, claim grounding, modify machine assessments or create its own shipping outcome.

## 3. Architecture and Hermes relationship

```text
Human
 ├─ Dashboard ────────────────────┐
 ├─ Telegram ↔ Hermes adapter ────┼─ Shared interaction service
 └─ Phone ↔ VoiceProvider adapter┘    ├─ authenticated actor and scope
                                      ├─ active review/run routing
                                      ├─ pending proposal and confirmation
                                      ├─ constrained API operations
                                      └─ authoritative backend APIs

Existing notifier → attention policy → Telegram delivery / outbound call
```

Hermes remains the selected Telegram runtime. Do not add a second Telegram update consumer. Reuse the current shipping-domain integration rather than replacing it. An optional Hermes interpretation adapter may propose intents from transcripts, but deterministic application code controls permitted operations, confirmations and submission.

Use a `VoiceProvider` adapter for starting an outbound call, answering an inbound call, speaking a prompt, gathering speech, ending a call and normalizing provider callbacks. Provider identifiers, signatures and transport settings stay behind this adapter. These are interaction-service interfaces, not new backend APIs.

**Voice style:** Calm, friendly and professional. Use short conversational sentences, a clear case/field/unit read-back, and neutral explanations of uncertainty. Never sacrifice confirmation precision for warmth. The isolated demo now selects `Polly.Joanna-Neural` with `en-US`; subjective quality and trial-account execution of this voice still require a listening test. Plain wording and punctuation are used initially; speaking-rate/SSML adjustments require verification on the chosen provider and trial path. This is presentation configuration, not a Shared Contract change.

Example confirmation: “Just to confirm. Option A, 21,707 kilograms. Shall I submit that?” Use “save a test proposal” instead of “submit” when running the isolated spike. Thank the user briefly and report only the outcome actually achieved.

Twilio is the tested demo transport candidate. Turn-by-turn speech gathering is sufficient for the initial demo. Do not require full-duplex streaming or assume Hermes supplies telephony. A deployed HTTPS interaction service is needed for reliable use without a running laptop; ngrok remains a development arrangement.

## 4. Scope and priorities

### Existing MUST — unchanged

Complete and preserve dashboard review handling, Telegram + Hermes, source access, bound overrides, durable routing, demo isolation, real-backend handshake and F4 submission work. Voice failure must not block these paths.

### Voice MVP — integration-gated extension

- One enrolled demo user and verified handset, using only authorized demo-safe fixtures.
- Real inbound and outbound calls through the provider adapter.
- Authenticated inbound pending-work query with a concise summary from existing APIs.
- One current backend CHOICE review resolved through speech, exact read-back and explicit confirmation.
- One real backend acceptance and observable resumption after the contract amendment is deployed.
- An evidence handoff through the existing Telegram integration; use an original document plus locator and dashboard link if no crop renderer exists.
- “Repeat,” “no,” “I cannot tell,” and “not now” behavior that cannot fabricate a decision.
- At most one outbound attempt per actor/review/run in the initial demo; no automatic redial. Optional further attempts require a deliberate operator/user action and a fresh state check.
- Short configured call limit, quiet hours and explicit outbound-call opt-in. Start with one active call per actor and a 90-second demo cap, adjustable after measured rehearsal.
- If any real integration gate fails, show the working Telegram/dashboard path and label the voice spike as experimental.

### SHOULD

Bounded free-form numeric values with unit clarification and exact read-back; multiple reviews in a call; richer pending-work navigation; asynchronous voice messages; policy-based escalation; natural-language interpretation through a constrained Hermes integration.

### OPTIONAL

Multilingual speech, full-duplex conversation, WhatsApp calling, transfers, sophisticated priority scoring and production telephony scaling.

## 5. Journeys H–K

### H — System calls user

Backend exposes an OPEN review → existing notifier checks authorized recipient, opt-in, quiet hours and attempt budget → attention policy selects a call → adapter calls the enrolled handset → authenticate before case disclosure → refetch the current review → explain case/field/side and necessary evidence → collect one option → read back exact proposal → explicit confirmation → validate and submit DecisionRequest → report acceptance accurately → poll/refetch outcome.

If the user does not answer, the call fails, or confirmation is absent, leave the review pending and deliver or retain the normal Telegram review. Voicemail must not contain private case details or trigger a decision.

### I — User calls system

User dials the assigned number → service authenticates and binds the actor → query authorized OPEN reviews and relevant cases → speak a brief workload summary → offer one eligible task → user explicitly selects it → run the same evidence, proposal and confirmation flow as H.

“What's pending today?” defaults to “currently pending as of now.” Do not imply that the emails arrived today. Explain a date filter when one is applied. For “since yesterday,” use actual history events and an explicit Asia/Kuala_Lumpur time window; label system activity as system activity.

### J — Voice plus evidence glance

Explain why source inspection is necessary → send the authorized source/locator through the user's mapped Telegram chat → confirm delivery → user views it when safe → user gives a choice/value verbally → read back and confirm → normal backend submission.

Do not claim an image was sent if only a document/link was delivered. DOCX/XLSX evidence uses its real paragraph/table/sheet-cell locator; never invent a PDF page. If the user is driving or cannot inspect evidence, defer instead of urging a glance.

### K — Defer

“Not now” or “I cannot look at this” cancels the pending voice proposal and leaves the backend review unchanged. An interaction-layer reminder preference is not a shipping decision. Do not map ordinary deferral to ACKNOWLEDGE, which closes a review and leads to BLOCKED_EXTERNAL under the contract.

## 6. Voice Task Inbox and channel selection

Derive these interaction classifications afresh from authorized current state. They are not backend workflow enums:

| Classification | Meaning |
|---|---|
| VOICE_RESOLVABLE | An allowed action whose necessary context/evidence the user can establish without a new visual inspection. Not inferred solely from CHOICE mode. |
| VISUAL_EVIDENCE_REQUIRED | Source inspection is needed before a defensible decision. |
| BLOCKED_EXTERNAL | Reflects backend BLOCKED_EXTERNAL; distinguish OPEN acknowledgment from already acknowledged cases. |
| INFORMATION_ONLY | Status or correction notice with no actionable review. |

Use existing `/api/v1/reviews`, `/cases`, `/cases/{case_id}` and `/stats`; retrieve document content through the authorized route. Case detail supplies history and mismatches. No new backend read endpoint is justified for this small demo. Local filtering may suffice at this scale; larger-scale history searches would need a separately justified API proposal.

Use silence for routine automation, Telegram text for ordinary reviews/notices, optional voice messages for asynchronous explanations, and calls for opted-in actionable work that benefits from immediate conversation. Urgency must come from an explicit configured demo priority or supported business data. The current contract has no urgency/deadline field; do not invent one from the dataset or model intuition.

The existing notifier remains the single coordinator. Keep channel-specific attempt/delivery records locally. For this extension, preserve the current meaning of `notified_at`: Telegram individual-message delivery is what marks it. A ringing phone, answered call, summary or inbound query must not mark a review notified. Voice eligibility must not depend only on `notified=false`, because Telegram may already have delivered the review. If the team later wants voice-only delivery to set `notified_at`, coordinate that semantic contract change separately.

## 7. Intent and DecisionRequest mapping

| Spoken intent | Backend operation |
|---|---|
| Pending work / case status / summary / mismatches | Existing authorized read APIs only. |
| Next / repeat / send evidence / defer | Interaction behavior only; no decision mutation. |
| Explicit option selection | SELECT_OPTION using the actual current backend option_id, after confirmation. Spoken A/B labels are session-local aliases. |
| Numeric/text value | PROVIDE_VALUE with current field/side, canonical value and required override confirmation. |
| Explicit acknowledgment of external action | ACKNOWLEDGE only where allowed; explain that verification remains blocked. |
| None of these / I cannot tell | Map only to the current mode's contract-defined escape, after explaining its effect and confirming intent. |

Always use the current review_id and run_id and a trusted actor_id. Confirmation binds actor, case, review, run, action and option/value; value inputs additionally bind field, side and units. Discard confirmation after any edit, different review, new run, expiration or call disconnection. Never transfer a bare “yes” to another task.

Every mutating Voice MVP action requires explicit confirmation. Numeric read-back states the full value and unit; offer individual digits when recognition is uncertain. A recognizer confidence score or LLM assertion cannot substitute for human confirmation. Ambiguous/corrected speech triggers clarification, not submission. Use a bounded clarification budget and fall back to Telegram.

If the backend requires manual override, explain that the value is not supported by the source and obtain a new exact `OverrideConfirmation` tuple. Earlier generic approval is not enough. No new pre-validation API is required: handle the contract's existing 422 response without closing the review, then obtain the required override confirmation.

202 means “Your decision was accepted; processing continues.” Say “completed” only after a fresh backend response confirms it. On 409, announce that the review was handled/replaced and refetch. On timeout, refetch and reconcile before any retry. Never redirect an old proposal to a new review.

## 8. Interaction state, identity and recovery

Persist call/provider ID, direction, trusted actor mapping, case/review/run binding, selected proposal, confirmation status/expiry, processed callback identities, attempt count, delivery status and submission outcome. These belong to the interaction service. Do not add call states to WorkflowStatus.

A useful local call lifecycle is created → authenticating → gathering → awaiting_confirmation → submitting → ended/failed. Backend state is fetched separately. Restart must preserve accepted/submitting records and prevent duplicate application; uncertain or expired confirmations are discarded and reacquired.

Caller ID alone does not authenticate a person. Before private readout or mutations, bind the session through a short-lived challenge approved in the already authenticated Telegram account, or an equivalent trusted pairing flow. For the one-device demo, a pre-established short-lived pairing may be used. Validate provider webhook signatures and replay behavior on the deployed path; if trial proxying makes that impossible, investigate an authenticated alternative before real backend integration. The unsigned synthetic spike is not evidence that this gate has passed.

Apply the same demo-safe case/document checks to voice and to evidence handoff. Do not read case details before authentication or into voicemail. Keep provider tokens server-side. Store only the minimal interpreted intent, confirmation and delivery metadata needed for audit; audio recording is off by default. Transcript/audio retention and third-party handling must be explicit before participant-derived content is used.

Disconnect before confirmation: no submission. Disconnect after durable acceptance: reconcile and notify through Telegram; do not ask for the same decision again. Evidence delivery failure: say it failed and defer visual-dependent work. Provider outage: normal Telegram/dashboard remains usable. No automatic retry of reprocess.

## 9. Contract and team dependencies

[Shared Contract v2.1.2](./shared-system-contract.md), especially §§7.3 and 10.1, is authoritative. This PRD does not redefine its enums, wire types, authorization, confirmation or notification semantics. VOICE requires coordinated deployment; no real submission to unmodified v2.1.1 validators is permitted.

B implements/validates VOICE acceptance, trusted service identity, schema migration and channel persistence/consumers. A verifies unchanged evidence/grounding behavior and joins coordinated approval. C implements the voice adapter and attention policy, reusing PRD 2's shared interaction service. PRD 1's classifier, parser and comparison architecture do not require redesign.

No new business endpoint or workflow state is requested. Contract AC-20–AC-24 gate real voice activation. Core Telegram/dashboard acceptance remains separate while voice is disabled. Team sign-off and runtime migration are pending, not implied by this document.

## 10. Dataset fit and limits

The participant bundle contains shipping emails and attachments, not phone routing or reviewer identities. Enroll the demo handset explicitly; never derive recipients from signatures or phone numbers found in documents.

The 520 inspected records omit receipt timestamps. Continue emitting received_at=null; do not infer “received today,” age-based urgency or delivery deadlines from that absence. System processing/history times can support accurately labelled activity summaries.

The same backend-generated reviews can support voice after integration. However, the tests so far used synthetic values and did not establish dataset extraction accuracy or identify a dependable voice-only review in Case 055. Select a permitted participant example after running the real pipeline, or use a clearly labelled synthetic fixture whose documents and expected evidence are consistent.

Scanned-number disambiguation, document-role choice and complex addresses may require visual evidence. The value of voice is obtaining attention and handling simple structured responses, not guaranteeing that all dataset exceptions are resolvable without a screen.

## 11. Implementation milestones and acceptance

| Milestone | Exit criterion |
|---|---|
| V0 — transport and confirmation spike | Completed for one handset: real inbound/outbound speech echo plus a confirmed synthetic structured proposal. Numeric recognition limitations recorded. |
| V1 — shared interaction adapter and safe demo service | Durable routing, authenticated sessions, constrained read-only task inbox, provider callback validation, bounded calls, Telegram evidence handoff; existing MUST flows still pass. |
| V2 — coordinated backend decision integration | Contract amendment approved and deployed; one real review goes through speech confirmation, backend 202, resumption and updated dashboard; stale/race/override/refusal tests pass. |
| V3 — voice rehearsal alongside F4 | Repeatable short inbound/outbound demo, cost measured, access valid for pitching and finals, deployed endpoint or explicitly documented laptop dependency, backup video and Telegram fallback. |

Existing F0–F4 remain intact. V1 adapter work and simulator tests can run before real backend readiness. V2 real acceptance cannot. F3 may improve voice/Telegram language interpretation after deterministic flows work; it is not a prerequisite for the proven option-selection flow.

Acceptance must demonstrate:

- An authenticated caller hears only authorized current work, including the difference between pending decisions and external blocks.
- Inbound and outbound calls use the same domain routing/confirmation service.
- A spoken option maps to the backend-supplied option ID and exact current review/run.
- A wrong or ambiguous value, silence, “no,” or deferral cannot submit.
- A changed value or new run invalidates confirmation; “yes” without a pending proposal does nothing.
- A manual override remains ungrounded and requires its exact contract tuple.
- Concurrent channels yield one acceptance; stale voice input cannot apply to the next review.
- A lost HTTP response or process restart cannot silently submit twice or falsely claim completion.
- Failed/missed calls preserve normal Telegram access and do not repeatedly call the user.
- Required evidence can be delivered and inspected safely, or the task is deferred.
- Voice never exposes private EVAL content or mutates machine_assessment.
- No model call is needed for the deterministic demo path; any optional model usage is separately measured.

## 12. Demo scenario and cost gates

1. Start an approved demo fixture through the real backend. Explain whether it is synthetic.
2. An actionable review triggers one opted-in outbound call. Authenticate, inspect evidence if required, select an option, confirm, and show backend acceptance followed by its actual result.
3. User calls the system, authenticates, asks what remains pending, and hears a concise live summary. Demonstrate an external block honestly; optionally handle another eligible review.
4. Show the dashboard's unchanged machine assessment and updated operational outcome. Retain Telegram as the evidence/fallback surface.

For the current spike, Twilio trial minutes funded the Twilio-side tests. The observed balance was 70 minutes before the final confirmation call; the post-call balance has not been verified here. Inbound dialing used a US number, so the Malaysian carrier's international charge is separate and unmeasured. The RM10 total additional-voice target has therefore **not** been proven.

Before recording/finals, check actual remaining quota and trial expiry, number availability and carrier charges, endpoint hosting, and any post-trial number rental/per-minute/speech costs. Do not commit to a paid upgrade or new recurring service without a concrete priced choice. Confirm that the final-round date falls within the available account/number access window, or budget a replacement beforehand.

### Voice style and usage accounting

- Editing voice configuration, wording and local XML checks consumes no Twilio call minutes. No call was placed for the Joanna Neural configuration update.
- A real listening test or demo call consumes trial call allowance. Changing the selected voice does not itself reduce the trial's stated total allowance, but it does not make calls quota-free. Longer prompts or slower delivery can increase call duration and therefore usage.
- Twilio's trial documentation supports the Say voice attribute and describes TTS as bounded by trial call duration/quota. It does not establish that every premium voice is available without additional restrictions on this particular account. Joanna Neural execution and account-specific usage treatment remain to be verified; do not promise zero incremental charge.
- The Malaysia pricing page checked on 20 September 2026 lists neural TTS at US$0.0032 per 100 characters, separate from calling and speech recognition. This is a published paid usage rate, not evidence that the trial account has been charged. No paid upgrade was performed for this change.
- This style change adds no Hermes/LLM reasoning calls and does not change speech-recognition settings. Neural TTS is provider speech synthesis, with its own applicable usage terms.
- Keep prompts concise, retain exact numeric confirmation, and use at most one short listening test initially. Record actual trial allowance before/after and any visible TTS usage charge. Stop and review the concrete cost if an upgrade or paid enrollment is required.

Current source references for implementation planning: [Twilio trial voice restrictions](https://www.twilio.com/docs/usage/trials/try-out-voice), [Twilio speech Gather](https://www.twilio.com/docs/voice/twiml/gather), [Malaysia voice pricing](https://www.twilio.com/en-us/voice/pricing/my), [ngrok setup](https://ngrok.com/download/windows). Recheck applicable prices and restrictions at implementation time; successful trial tests are not a guarantee of production terms.

The defensible pitch claim today is: **“We demonstrated real two-way phone interaction and explicit spoken confirmation on a physical handset.”** Claim voice-driven backend resolution only after V2 passes.
