# F2 acceptance — fixed implementation checklist

Authority: Shared Contract v2.1.1 §§5–11 and AC-01–19; PRD 2 §§5–11,14–15.

- [x] Pin and exercise Hermes native plugin registration; one inbound consumer, deterministic handlers, dedicated restricted profile.
- [x] Trusted sender/chat allowlist, DEMO-only scoped REST credentials, denied guessed EVAL and document IDs.
- [x] Explicit persisted reply mappings; bare values never route implicitly; exact actor/review/run proposals survive restart.
- [x] CHOICE evidence, document target role, NONE_OF_THESE; backend option validation.
- [x] VALUE_INPUT shared deterministic parsing, canonical preview and human confirmation; cannot-tell escape.
- [x] Grounding rejection keeps review OPEN; exact persisted override confirmation, cancellation/edit invalidation.
- [x] Durable 202 distinguished from completion; follow subsequent review/block/failure and frozen assessment.
- [x] Duplicate updates/callbacks, dashboard races, stale runs, uncertain responses cannot repeat or migrate decisions.
- [x] One persistent notifier, 3–5 second polling/backoff, per-recipient spacing, bounded bursts, meaningful-change digest; no digest notification marks.
- [x] Send → persist mapping → notified marker recovery; bounded document retries with honest fallback.
- [x] Correction notices without reviews, operator-only technical failure, active-run recheck before queued send.
- [x] Independent persistent routing, inbound progress, confirmations, queue/retries and delivery records; restart and session-reset tests.
- [x] Actual authorized Telegram handshake, source delivery, decision, dashboard result and gateway restart with a pending exact override (19–20 September live simulator verification).
- [x] F0/F1 regressions and unchanged authoritative documents.
- [ ] Real backend handshake (separate external gate).

Checked items denote simulator/native SDK verification; the explicitly marked live handshake also used real Telegram delivery. See F2-verification.md for individual journeys and the unresolved pinned-gateway cold-start limitation. Real-backend integration remains a separate gate.

Live credentials and explicitly authorized recipients are prerequisites for live checks, not for independent application tests. Test doubles must be labelled as such.
