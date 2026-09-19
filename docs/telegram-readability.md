# Telegram readability update

User direction: short action-first messages, conversational tone, details separately, across the full bot flow.

Implemented in `interaction/copy.ts` and the existing engine:

- Reviews state the task, exact side/field or role, input format and next action. Known mismatches and synthetic labels remain visible.
- Queue buttons use case subjects with Review / Needs correction / Needs help labels.
- View details displays raw/normalized values, evidence, provenance, machine-versus-operational state, failure context and review/run identity. It is read-only, authenticated and rejects replaced runs/reviews.
- Previews show the exact proposal, interpretation source and confirmation/cancellation instructions. The persisted confirmation binding is unchanged.
- Overrides explain unsupported source values; results retain the human-provided/ungrounded warning. Acknowledgment never claims verification is complete.
- Acceptance, outcomes, cancellation, provider failure, stale actions, unauthorized actions, connection uncertainty and document-delivery failures use recovery-oriented wording. Internal exceptions are no longer copied into chat.
- Open dashboard provides the case URL and explicit laptop-only/copy-paste guidance for localhost. It does not turn localhost into a publicly accessible service. A hosted dashboard is still outstanding.

Verification: `npm run check` passed 67 tests and the production build; `npm run test:browser -- tests/browser/f2.spec.ts` passed both deterministic/interpreted journeys. Copy assertions were updated to the new wording without removing contract/state assertions. Added a test proving detail/link controls leave the review open, preserve a pending confirmation and reject a stale run.

Live Telegram checks: new subject-based queue; action-first BL container-count review; separate evidence showing OPEN/AWAITING_HUMAN; localhost guidance; an unmapped reply gets a clear recovery instruction; correctly routed value produces the new preview; Cancel leaves no submitted decision. Inspected the preview screenshot for spacing and button readability. No case replay/reset was needed. Historical messages keep their old wording; request a fresh queue with `/reviews`.

This changes presentation and read-only navigation, not simulator grounding, extraction or real-backend integration. Existing F3 verification boundaries still apply.
