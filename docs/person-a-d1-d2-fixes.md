# Person A: AI evidence binding and database upgrade

Branch: `codex/person-a-evidence-migration-fixes`.
Parent reviewed commit: `5b9ff5f9ac4ade872bd15907d53d42c36d8929a0`.

## Changes

### D1: contradictory AI claims

The pipeline supplies a token-to-block mapping containing each source block's
label, exact value, structural context and document order. The HTTP request
includes this mapping as `location_blocks`, alongside the document text. The
existing request-size limit bounds the request; exceeding it stops the call.

Both `raw` and evidence `source_text` must equal the selected block's complete
value exactly. This deliberately conservative private protocol performs no
whitespace rewriting or numeric equivalence inference on the AI's quotations.
The HTTP adapter rejects disagreement. The pipeline also checks injected client
responses, so bypassing the HTTP adapter cannot bypass the binding rule.
An inconsistent claim leaves that field unresolved even when another valid
claim for it appears in the same response, in either order.

Candidates still must pass the existing source, semantic-label and numeric
grounding checks. Multiple distinct candidates retain the C2 uncertainty
behavior. Prompt v2 instructs the model to retain uncertainty when the source
does not establish which reading applies. This prevents contradictory evidence
from being silently rewritten; it does not prove a model's semantic choice is
correct. Live-provider and held-out evaluation remain outstanding.

AI, pipeline and release versions are bumped; prompt hashing also changes the
configuration identity. The public shared contract is unchanged.
The default configuration identity for this release is
`person-a-v1+c6665be1b54e7c1e`; environment-specific settings can change it.

### D2: existing SQLite databases

`backend.database.init_db()` now calls `backend.migrations.initialize_schema`
before application startup proceeds. Migration `0001_run_snapshot_interpretation`
adds nullable JSON columns `machine_state` and `config_manifest` to existing
`run_snapshots`. Fresh installations get the current tables. A small
`schema_migrations` table records the applied version.

The upgrade is additive and idempotent, including a partially upgraded table.
SQLite `BEGIN IMMEDIATE` serializes concurrent startup migrations. Changes and
the version record commit together. Failures abort startup; workers do not
continue against a known incompatible schema.

Existing cases, jobs, snapshots and accepted decisions are preserved. Missing
historical interpretations remain SQL NULL: the migration never invents them.
Existing databases on other engines with missing columns fail early with an
actionable message; automatic schema alteration here supports SQLite only.

## Upgrade procedure for Person B

1. Stop the old API and worker processes before changing the deployed code.
2. Back up the SQLite database consistently. Use SQLite's backup facility, or
   copy it after a clean shutdown/checkpoint; copying only the main database
   file while a WAL writer is active is not a consistent backup.
3. Activate this branch and install the existing pinned backend requirements.
4. Point `DATABASE_URL` at the intended database. From the repository root run:

   ```sh
   python -c "from backend.database import init_db; init_db()"
   ```

   Application startup also performs this step automatically.
5. Inspect the upgrade result and start the new API/workers. New runs write the
   full machine interpretation and configuration manifest normally.
6. Preserve historical runs for audit. A run with missing machine state is
   refused by the existing resumption guard. A run under an older configuration
   is also refused rather than silently reinterpreted. Coordinate explicit
   reprocessing through the existing workflow with Person B. Do not delete or
   automatically replay old pending accepted decisions into a new run.

For another database engine, Person B must add the equivalent nullable JSON
columns through that deployment's migration process before startup. No schema
downgrade or data-destructive rollback is supplied. Keep the pre-upgrade backup.

## Validation

Final full suite: **355 passed, 2 dependency deprecation warnings, 112.32 s**
on Python 3.12 with the pinned backend requirements. The original reviewed
suite had 335 tests; this change adds 20 regression tests.

Regression coverage includes the real HTTP adapter with a mock transport,
wrong raw/quote values in both directions, empty quotes, valid agreement,
conflicting readings, injected contradictory responses in either order,
populated legacy databases, repeated and concurrent upgrades, partial upgrades,
fresh installations, controlled legacy resumption refusal and a real worker
processing a fresh case after upgrade.

The existing `ChoosingModel` test double now returns actual source quotations
instead of placeholder text and empty evidence. Its original assertions remain.

Run from the repository root:

```sh
python -m pytest -q
```

## Import the delivered self-contained bundle

The delivered `person-a-fixed.bundle` contains this branch's full reachable Git
history, including the original project and binary fixtures. It has no required
external base commit. It excludes uncommitted files, secrets/environment files
not tracked by Git, installed dependencies, and local databases.

To restore in a new directory:

```sh
git clone -b codex/person-a-evidence-migration-fixes /path/to/person-a-fixed.bundle Monash_Hack_fixed
cd Monash_Hack_fixed
```

To import into an existing clone, first ensure there is no uncommitted work:

```sh
git bundle verify /path/to/person-a-fixed.bundle
git fetch /path/to/person-a-fixed.bundle codex/person-a-evidence-migration-fixes:codex/person-a-evidence-migration-fixes
git switch codex/person-a-evidence-migration-fixes
```

Do not force-update an existing branch of the same name. Choose a fresh local
branch name if it already exists and has diverged. The imported branch contains
the fixes already; Claude does not need to implement this report again.

A clone made directly from a bundle initially has the bundle path as `origin`.
Only when ready to publish, set its remote to the intended GitHub repository
and push this feature branch using an account with write access. Do not push to
`main` or merge automatically. No remote was changed or pushed by this task.

## Remaining work outside these two fixes

These changes do not resolve the previously documented Person B/Lee integration
gates: durable provider accounting across restart/retry; authentication and
participant-data exposure; actor/namespace identity; run archive; guarded
failure/retry writes; and shared-contract v2.1.1/v2.1.2 coordination. Numeric
policy and port-table approval decisions are unchanged. There was no live model
call, evaluator submission, accuracy claim, cloud deployment or Telegram
handshake in this task.
