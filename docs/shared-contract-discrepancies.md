# Shared-contract adoption notes

## SC-01 — Superseded by v2.1.1

The supplied [Shared System Contract v2.1.1](../shared-system-contract-v2.1.1.md) supersedes the former receipt-time blocking workaround. The revised contract and both PRDs are adopted together in this workspace. This records implementation adoption, not additional team sign-off or completion of external release gates.

`shared/participant-mapping.ts` now maps an absent source receipt timestamp to the required `received_at: null` and returns a validated initial PROCESSING Case. It retains the source body and attachment references for later processing; it does not classify, parse files or expose participant records through the public simulator. Caller-supplied run identity and system creation time stay separate. A trustworthy supplied timestamp is validated and normalized to UTC; malformed values raise a validation error. Quoted correspondence, file time and the system clock never fill receipt time.

The wire discriminator is `schema_version: "2.1.1"`; omitted receipt keys and malformed non-null values are rejected. No provisional schema is retained. Strict v2.1 clients must update. The old v2.1 document is retained as a historical reference only; authoritative links now point to v2.1.1. Historical snapshots are not rewritten.

Fixtures include known fictional and unknown receipt times in processing and settled states. Replay preserves receipt metadata and initial `created_at`, while advancing the new run timestamp. The UI renders “Received time unavailable,” “Case created,” and “Last updated” distinctly. No additional ingestion timestamp was introduced.

Receipt absence alone creates no failure, review or exclusion rule. Actual backend ingestion/export and cloud integration remain unverified; this mapper and simulator do not establish those end-to-end gates. No-attachment intent interpretation remains unresolved under the existing contract baseline. Hermes remains the selected F2 integration.
