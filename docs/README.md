# Implementation documents

These stable paths contain the current authoritative documents:

- [Shared System Contract](./shared-system-contract.md) — v2.1.1; authoritative for both PRDs.
- [PRD 1 — Backend](./prd-1-backend.md) — v2.1.1-aligned.
- [PRD 2 — Interaction](./prd-2-interaction.md) — v2.1.1-aligned; Hermes selected for Telegram.
- [Person A — implementation](./person-a-implementation.md) — document intelligence: what it does, what it refuses to guess, measured behaviour and limitations.
- [Person A — integration handoff](./person-a-integration.md) — the callable boundary for B, the demo fixtures for C, changes made in shared code, and the blockers still open.

Versions live inside the documents. Edit these files in future documentation PRs rather than introducing a new filename for every revision. Redundant root-level document pointers have been removed. Git history preserves previous content.

## Adoption

The v2.1.1 amendment permits `email.received_at: null` because participant records omit receipt timestamps. Update shared types, runtime validation, participant mapping, simulator payloads, dashboard date handling, and fixtures together. Keep case creation/update and run times distinct from receipt time. This documentation change does not certify that any implementation or team review has completed.

The PRDs also record the inspected participant structure, dataset-informed synthetic F0 fixtures, the distinction between simulated and real-data validation, and Hermes's F2 integration boundary.

Branch new work from current `main`. Existing feature branches can incorporate current `main`; commit or otherwise safely preserve local work first. If a feature branch already contains full copies at the old root filenames, retain its legitimate content changes in these canonical documents, update references to the stable paths, and remove the superseded root copies when integrating. Do not discard implementation changes to resolve documentation moves.

Shared semantic changes follow the contract's A/B/C review rule. Local implementation edits may remain within the relevant PRD when they do not change shared obligations.
