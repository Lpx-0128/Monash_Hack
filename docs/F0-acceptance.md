# F0 acceptance checklist

Authority: Shared System Contract v2.1.1 §§3–8, 11–13; PRD 2 §§4, 10–14. Decisions and human-resolution interactions remain F1.

## Required verification

- [x] Overview, case list and deep-linked detail work at desktop and mobile widths, with keyboard access and visible focus.
- [x] Overview uses latest-run DEMO statistics: machine/effective status are separate; null assessments do not count as OK; auto-completed excludes every run with a created review; blocks and failures stay visible.
- [x] List filters use the API's workflow_status, category, final_status and has_open_review. Null category reads Classifying.
- [x] Detail shows email/run, frozen assessment, operational outcome, all seven fields for settled BL comparisons, original/raw and normalized values, evidence locations, provenance, documents and run-scoped history.
- [x] Unknown values never appear as zero or MATCH. Overrides remain ungrounded with exact confirmation lineage. Acknowledged blocks never appear completed.
- [x] Display all review modes, options (including NONE_OF_THESE), target and source context. Explain F1-only actions without fake submission or success.
- [x] Complete fixtures: initial processing; match; mismatch without review; non-BL; field input; candidate choice; document-role choice; open/acknowledged external blocks; human-resolved; sequential reviews; failure before assessment; failure after accepted decision; superseded review; empty/populated stats.
- [x] Synthetic documents, content hashes, Unicode code-point evidence ranges, field labels and outcomes agree. No AI extraction is claimed to have run.
- [x] Shared runtime validator checks all required wire shapes, closed vocabularies and applicable semantic invariants. Negative tests reject contract violations.
- [x] Stateful HTTP simulator is separate from UI. Same validated API adapter interface supports future real API access. Contract endpoints and error envelopes are preserved.
- [x] Processing transitions are predictable, visible through polling, and guarded by active run identity. Replay resets operational state and supersedes old reviews; duplicate create preserves the existing run.
- [x] Reset restores a known synthetic dataset. Empty, loading, stale/error, unavailable and access-denied states are inspectable. Failed polls retain labeled stale data; no overlapping/out-of-order updates regress the UI.
- [x] Server enforces synthetic DEMO scope for cases, reviews, stats, documents and replay. No private browser credentials. GET never marks notifications delivered.
- [x] Automated contract/API checks, build/type checks and actual browser exercises pass; screenshots checked at 375, 768, 1024 and 1440 pixels; runtime/network failures investigated.
- [x] Exact launch instructions and deployment configuration supplied. Production preview checked. Hosted deployment verified or explicitly recorded as an outstanding external dependency.

## Participant-reference continuation

- [x] Review only official participant materials; never use template GENERAL placeholders as ground truth. Public data stays synthetic.
- [x] Use participant-shaped correspondence, multiline addresses, label aliases, container expressions and explicit weight conventions with consistent evidence.
- [x] AC-17: Missing participant receipt time maps to a valid v2.1.1 processing Case with null and no metadata-triggered review or failure. Malformed supplied times are rejected.
- [x] AC-18/19: Known/unknown receipts render in processing and settled states; replay preserves unknown receipt and initial creation time while advancing run time. Required receipt keys remain validated; no provisional schema.
- [x] No-attachment intent stays explicitly unresolved, externally blocked and non-comparable on all seven fields, with no invented category or false parsing history.

## Outstanding deployment gate

- [ ] Verify a hosted deployment on an authorized target. No provider/project/access was supplied. Local production preview is verified; full deployed F0 completion remains outstanding.
- [ ] Build/run the supplied Docker image. Docker CLI is installed, but the Linux daemon is unavailable.

## Boundaries

The simulator demonstrates predefined state transitions and stored examples, not real classification, extraction, AI, durable backend decision acceptance or Telegram delivery. F1 will implement decision submission and exact override confirmation; later phases provide Telegram and live backend integration. Contract AC-01–AC-19 are wider system acceptance gates, not all achievable in F0.
