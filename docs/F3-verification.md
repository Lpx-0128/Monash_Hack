# F3 verification — 20 September 2026

F3 adds optional interpretation through pinned Hermes and GitHub Copilot `gpt-4.1`. Shared Contract v2.1.1 is unchanged. Only minimal, explicitly mapped synthetic review context reaches inference. Provider output is strictly validated; identity, target and approval remain application-controlled. No general agent tools are enabled.

## Automated evidence

- `npm run check`: 66 tests passed, TypeScript and production Vite build passed. Existing dependency PURE annotation warnings do not prevent the build.
- `npm run test:browser -- tests/browser/f2.spec.ts`: 2 browser journeys passed, covering deterministic and interpreted proposals with the actual simulator API/dashboard and a controlled model double. These are not live Copilot browser tests.
- `python tests/hermes_interpretation_test.py`: passed explicit provider/model, bounded request, no-tools and invalid-context checks with a provider double.
- `tests/hermes_plugin_test.py` under installed pinned Hermes: passed native registration/PTB routing, authorization, durable inbound dedup/restart, preserved pending-update policy and bridge ownership transfer while an abandoned application still reports running. Telegram HTTP is mocked in this test.
- `python tests/f2_setup_test.py`: passed.
- F3 tests include wrong target/action/extra identity fields, ambiguity, exact unit conversion, provider failure, changed proposals, stale inference after reprocessing, and confirmation before accepting an interpreted candidate.

## Actual provider corpus

[Final report](F3-evaluation.json): 18/18 expected outcomes, 10 actual Copilot calls and 8 deterministic guard clarifications. Seven valid proposals and eleven total clarifications (three from the model); zero unsafe proposals and zero decision submissions. Median model latency 2600.5 ms; maximum 5797 ms. This small authored corpus does not establish general interpretation accuracy.

[Initial report](F3-evaluation-initial.json) is retained: 17/18 passed. “twenty-ish tonnes” incorrectly produced an exact proposal. It was never submitted. A deterministic approximation guard fixed this and the same corpus was rerun without weakening its expected outcomes.

## Live check

Real authorized Telegram chat → installed Hermes → actual Copilot → simulator → dashboard was exercised. On `demo_grounded-input`, the spelled-out 21707 kg reply produced a labelled Copilot preview. The dashboard stayed AWAITING_HUMAN with an open review until confirmation. Confirmation produced 202 acceptance followed by COMPLETED / operational OK, DOCUMENT_CONFIRMED provenance, and unchanged frozen NEEDS_REVIEW machine assessment.

After recovery, replying “Use the second option” to `demo_candidate-choice` produced a Copilot proposal for 22000. The review remained open before confirmation. Confirmation produced 202, then COMPLETED / MISMATCH with CORRECTION_REQUIRED, DOCUMENT_CONFIRMED and unchanged machine NEEDS_REVIEW. Dashboard screenshot inspection showed the completed case and preserved synthetic/timestamp labels; browser warning/error log was empty. Ambiguity and stale inference are covered by the corpus and automated tests, not claimed as additional live Telegram journeys.

A final check run exposed an existing transient F1 ephemeral-port fetch failure and the old generic `Option:` assertion after improving preview target labels. The assertion now requires the exact BL field/value/unit; the complete rerun passed 66/66 plus build. No test was removed or skipped.

Telegram suffered a network timeout during the next journey. Hermes rebuilt its application. A regression exposed the need to transfer bridge ownership instead of leaving the previous application bound to the local port; the plugin now cancels/cleans up the old bridge before the replacement starts and refuses old-generation updates. The fixed native regression passes. Gateway restart restored the live `/reviews` digest. Network availability remains external; a local fix cannot guarantee Telegram connectivity.

## Boundaries

This is simulator verification with a real LLM provider and real Telegram transport. Grounding/extraction are simulated. The useful pipeline view currently exposes interpretation → confirmation → simulator acceptance → operational result; a **real backend pipeline view and PRD 1 integration remain outstanding**. F3 is not a claim that all PRD 2 real-integration acceptance criteria are complete.

Existing F2 flood controls, exact override confirmation and offline retention limits remain. Telegram's finite queue and the transport acknowledgment-before-local-persistence crash window are not eliminated. No production deployment, Hermes core modification, real extraction, full dataset evaluation or F4 work is included.

The installed Hermes startup may log missing optional Nous auxiliary credentials; this shipping interpreter explicitly selects Copilot and does not fall back to Nous. Secrets stay in ignored local files. See [setup and walkthrough](F3-setup.md).
