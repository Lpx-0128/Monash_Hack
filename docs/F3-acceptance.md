# F3 — Hermes interpretation acceptance

Authority: PRD 2 §§6–8, 13–15; Shared Contract v2.1.1 remains unchanged.

- [x] Deterministic buttons/canonical values remain independent of provider availability.
- [x] GitHub Copilot is the explicit provider through the pinned Hermes runtime; no silent provider fallback, credentials in UI, or general agent tools.
- [x] Only authorized DEMO context for an explicitly mapped current review is sent for interpretation.
- [x] Strict structured proposals: exact target, allowed action, canonical value or existing option; model identity/approval fields rejected.
- [x] Every interpreted action has a persisted, exact preview and explicit human confirmation; backend grounding/override checks still apply.
- [x] Ambiguity, negation, multiple numbers, wrong side, malicious instructions, unsupported output and provider errors produce clarification or deterministic fallback, never automatic submission.
- [x] Recheck run/review after inference; stale responses cannot migrate. Changed input invalidates prior confirmation.
- [x] Resettable synthetic examples, measured interpretation test corpus and honest sample-size/accuracy/clarification/unsafe-action results.
- [x] Actual Copilot inference and live Telegram → preview → confirmation → simulator → dashboard checks; retain all F2 routing/restart/flood protections.
- [x] Useful pipeline visibility distinguishes deterministic parsing, model interpretation, human confirmation, backend acceptance and simulated completion.
- [x] Document launch/setup, usage limits, verified provider/model, tests and limitations. Real-backend pipeline visibility/acceptance stays outstanding until PRD 1 is available.

