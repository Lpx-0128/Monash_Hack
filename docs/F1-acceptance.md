# F1 acceptance — simulator

Authority: [Contract v2.1.1](shared-system-contract.md) §§4–9, AC-01–AC-19; [PRD 2](prd-2-interaction.md) §§4–5, 13–15. Preserve the F0 checkpoint and design system.

- [x] CHOICE shows candidate evidence, explicit document target and NONE_OF_THESE; requests use allowed actions only.
- [x] VALUE_INPUT parses deterministically with field/side/unit guidance, canonical preview and explicit ordinary confirmation; invalid values do not submit.
- [x] Unsupported values/candidates return grounding errors without closing reviews. Exact review/run/field/side/value override confirmation is required and cleared by edit/cancel/target changes.
- [x] Accepted human values have per-value document-confirmed or ungrounded manual provenance and exact lineage; frozen machine assessment is unchanged.
- [x] Every acceptance returns 202 PROCESSING with closed review and retained pending work, then polls to completion, subsequent review or failure. Prior results say updating.
- [x] ACKNOWLEDGE, I cannot tell and NONE_OF_THESE produce closed-review BLOCKED_EXTERNAL, never completion.
- [x] Sequential review respects canonical field order and SI-before-BL, one open review, distinct-field and per-side budgets; known mismatches remain visible.
- [x] Completed mismatch has CORRECTION_REQUIRED. Document assignment rederives values from the assigned immutable synthetic document.
- [x] Server validates shape, path/body IDs, actor, run, open review, action, target, option and exact confirmation. Invalid/stale/conflicting actions cannot mutate case or enqueue work. Invalid requests are rate-limited.
- [x] First competing decision wins. Old jobs cannot update a reprocessed run. Acceptance followed by delayed work or resumption failure retains the decision without requiring re-entry.
- [x] Network uncertainty locks submission until an authoritative refetch; no automatic resend. Drafts stay within the same review/run, with confirmation invalidated on stale state or reload.
- [x] F0 navigation/filter/evidence/reset/replay and nullable receipt invariants regressions pass; accessible controls, keyboard, responsive screenshots and runtime/network checks performed.
- [x] Exact launch and journey instructions, verification evidence and limitations documented.

## External gates

- [ ] Real-backend F1 integration. No real backend is configured; simulator evidence does not satisfy this gate.
- [ ] Hosted deployment and Docker execution remain the previously recorded F0 external gates.

Hermes/Telegram, real extraction and dataset evaluation are outside F1.
