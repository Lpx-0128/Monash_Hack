# Person A — document intelligence implementation

Latest update: [D1/D2 fixes and upgrade instructions](person-a-d1-d2-fixes.md)
on `codex/person-a-evidence-migration-fixes`. That addendum supersedes the
historical AI-token and database-upgrade limitations below.

What was built, how it behaves, what it refuses to guess, and how to run it.

- **Branch:** `claude/person-a-corrections`, continuing
  `claude/loving-bohr-x6whx9` at `58f2a7e`, based on `main` at `72e6940`.
- **Contract:** shared contract v2.1.1, retained **unchanged**. No new wire
  field, enum value, review action or endpoint was introduced.
- **Baseline before any of this work:** 15 tests passed in 21.34 s.
- **At `58f2a7e` (first pass):** 234 tests, 96 files changed.
- **At `675f0d3` (first correction pass, R1-R10):** 301 tests.
- **After the second correction pass (C1-C4):** 335 tests pass in 113.01 s.

## 1. What the pipeline does

`backend/intelligence/` is one modular package. `analyze_case()` is the single
callable Person B integrates against. It opens no transaction, touches no
database session, creates no review ID and mutates no Case.

```
immutable input → classify intent → (BL comparison?)
                                      │ no  → OK, fields = []
                                      │ yes → parse → assign roles from content
                                              → extract candidates
                                              → ground (G1/G2/G3)
                                              → normalize → compare → roll up
```

| Module | Responsibility |
|---|---|
| `types.py` | Immutable DTOs, locators, the failure taxonomy, the JSON-number boundary |
| `config.py` | Validated settings, version identities, budgets, the config manifest |
| `ingestion.py` | Source registries, containment checks, SHA-256, `input_version`, document identity |
| `parsers/` | TXT, PDF, DOCX, XLSX and a content-signature router |
| `classification.py` | Ordered intent rules over the current message, plus a bounded model fallback |
| `roles.py` | Content-backed SI / BL / OTHER / UNKNOWN assignment |
| `extraction.py` | Versioned aliases, candidate interpretations, totals and references |
| `grounding.py` | G1, G2, G3 — shared by every path that produces a value |
| `normalization.py` | Party blocks, ports, counts, masses, numeric punctuation |
| `comparison.py` | Exact comparison and the assessment roll-up |
| `recomputation.py` | Human proposal validation, dependency recomputation, budgets |
| `pipeline.py` | Composition; returns review *requirements*, never Reviews |
| `ai.py` | One `ModelClient` protocol, one validated HTTP adapter, one test double |
| `wire.py` | The only module that imports `backend.schemas` |

## 2. What it refuses to guess

These are deliberate. Each one costs coverage and buys correctness.

**A lone thousands/decimal separator.** `131,058` can be 131058 or 131.058, and
both are physically plausible for a shipment mass. With no convention
established, the field is `NOT_COMPARABLE / AMBIGUOUS` and a person is asked.
The policy is configurable (`INTELLIGENCE_NUMERIC_LOCALE_POLICY`) and the
coverage effect is measured — see §6.

**A missing unit.** `Gross Weight: 341715` with no unit in the value or the
heading yields no value. The internal field name `gross_weight_kg` is not
evidence that the source number is kilograms. `MT` and `tonnes` convert; a bare
`ton` stays ambiguous.

**A port code, at all, by default.** The corpus contains `BALTIMORE, US (NGAPP)`
— a Nigerian code on a US port. `CORPUS_PORT_CODES` records what code each port
is *mostly written with* in the source registry (`scripts/derive_port_codes.py`:
at least three observations **and** a strict majority, i.e. more than half).

That is a **corpus convention learned from development data**, not an external
validation of geographic truth — the documents it is derived from are the same
noisy artefacts being checked, and no port registry was consulted. It is
therefore not called "verified", and `PORT_TABLE_APPROVED` is **`False`**: until
the team records that decision, no code is discarded and every code difference
stays visible.

Country agreement alone was never proof and is no longer used as such:
`PORT KLANG, MALAYSIA (MYZZZ)` has the right prefix but matches no recorded
code. Ports with split or thin evidence (Cebu, Tuticorin) are absent from the
table by design. Terminal qualifiers such as `(WESTPORT)` are never stripped.

Measured cost of the conservative default: **none on this corpus.** The gate is
exercised — 8 one-sided code comparisons across emails 516-520 — but the
outcome counts are identical with it on or off, because those cases are already
in review for other reasons.

**A role from a filename.** `email_501_BL.txt` is a commercial invoice. Roles
come from document headings and body content; the filename only ranks
candidates. When two documents tie for a role, that is a question, not a
coin flip.

**A value that only looks right.** Every value is bound to the private parser
block it was read from, and passes three gates before it can be compared —
whether a rule, a model, a person or a candidate selection produced it:

- **G1** the quote is the text stored at the *bound block's* value location in
  this run's artifact, with a matching content hash. Verifying against the page
  is not enough: every value on a PDF page shares `PdfPage(1)`, so a page-level
  check would accept one field's number as another field's value.
- **G2** the **bound block's own** label supports that canonical field. The
  label is read from the artifact, never from the candidate, so claiming
  `label_text="Gross Weight"` proves nothing. A gross weight is never supported
  by digits sitting in a seal number, a net weight or an invoice amount.
- **G3** the value is re-derived from the bound block's stored text — not from
  the quote the caller supplied — and must match exactly.

A candidate that names no block cannot be grounded at all.

## 3. Parser conventions (relied on by G1)

- Text is stored with line endings normalized to `\n`. Every `text_range`
  offset refers to that persisted sequence, and `text[start:end]` equals the
  quote exactly.
- A **boundary label** starts at column 0. An indented `label:` line is address
  continuation content — the corpus writes `  NEW NO : 23, L-BLOCK...` inside a
  consignee block, and `TEL:` / `P.O. BOX:` lines likewise stay in the block.
- A value span runs to the end of its last continuation line. An absent value
  is an empty span; it never borrows the next label's value.
- Layout-mode PDF pages also yield two-column `Label    value` blocks.
  `pdf_page` is one-based and addresses a page, so G1 checks containment.
- `docx_paragraph` is zero-based over body paragraphs. `docx_table_cell` uses
  zero-based table/row/column; a merged cell is read once, at the first
  position its underlying element appears.
- `sheet_cell` carries the exact sheet name and A1 coordinate. Values pair with
  cells to the *right* in the same row; pairing downwards is not done, because
  the sheet structure does not express it. Missing, zero, `FALSE` and empty
  string stay distinct.

## 4. Honest failure handling

| Situation | Result |
|---|---|
| PDF with no text layer but image XObjects | `UNREADABLE`, diagnosed as a scan; OCR is not claimed |
| PDF that cannot be opened by a known pypdf source error | `UNREADABLE`, established source corruption |
| Any other parser exception | `PermanentProcessingError` — a technical failure, never `NEEDS_REVIEW/unreadable` |
| Missing parser package, bad config | `PermanentProcessingError` |
| Provider timeout or 5xx | `RetryableProcessingError` |
| Undecodable text bytes | source-quality issue; `errors="replace"` is never used |

## 5. Human decisions

Person A returns a review **requirement**; Person B builds and persists the
Review. Validation happens before anything durable is written, and a rejected
proposal closes nothing, enqueues nothing and consumes no budget.

- A typed value is **document-confirmed** (`grounded=true`, real evidence) when
  it equals one of the readings the target document genuinely admits — which
  includes resolving an ambiguous separator the machine refused to resolve.
- Otherwise it is refused with `VALUE_NOT_FOUND_IN_DOCUMENT`, and the review
  stays open.
- A **manual override** needs a confirmation bound to the exact review, run,
  field, side and canonical value, with `confirmed: true`. It stays
  `grounded=false` with no evidence claiming to support it. Editing the value
  invalidates the confirmation.
- Correcting a consignee re-derives that side's `SAME AS CONSIGNEE` notify
  party deterministically, inheriting the override's ungrounded lineage. No new
  confirmation is invented for the dependent field, and an SI consignee never
  feeds a BL notify party.
- Budgets: at most two distinct fields per run, one accepted decision per
  `(field, side)`, two per field, one document choice per role and two per run.
  Beyond that the case blocks externally rather than looping.

Every accepted action, acknowledgment included, returns `202` with the case in
`PROCESSING`. `resolution` keeps the previously applied result, or null.

## 6. Measured behaviour on the supplied bundle

Recomputed by `scripts/inspect_intelligence_inputs.py`, not assumed:

| Item | Observed |
|---|---:|
| Email records | 520 |
| Emails with at least one attachment | 126 |
| Attachment files | 250 (TXT 192, PDF 28, DOCX 8, XLSX 22) |
| Records supplying `received_at` | 0 |
| Listed attachments absent on disk | 0 |
| Parsed OK | 242 |
| Parsed UNREADABLE | 8 (6 image-only, 2 corrupt) |
| Technical failures | 0 |

Classification over all 520 records, all deterministic:

| Category | Count |
|---|---:|
| SI_REQUEST | 216 |
| BL_COMPARISON | 129 |
| GENERAL | 71 |
| INVOICE_QUERY | 64 |
| SPAM | 40 |

All 126 attachment-bearing emails classify as `BL_COMPARISON`; the other three
are explicit comparison requests whose attachments were dropped.

**These counts are this implementation's output, not organizer labels.** No
evaluator was run and no accuracy score was observed or claimed.

### The numeric-convention trade-off

Outcomes for the 129 BL comparison cases, under the two policies:

| Policy | OK | MISMATCH | NEEDS_REVIEW |
|---|---:|---:|---:|
| `auto` (default, conservative) | 1 | 2 | 126 |
| `en` (',' groups, '.' decimal) | 52 | 39 | 38 |

An earlier revision of this document reported the `en` row as 52/38/39. That was
a transposition in the write-up: `58f2a7e` itself produced 52/39/38, which is
what an independent review also measured. Both policies process all 520 records
with zero technical failures, and neither changes the classification counts.
Switching to `en` moves 88 cases: 51 from NEEDS_REVIEW to OK and 37 from
NEEDS_REVIEW to MISMATCH.

Under `auto`, 108 of the 126 reviews are `unreadable`, almost all from
`LONE_SEPARATOR_AMBIGUOUS`. The corpus contains exactly **one** unambiguous
en-form value (`22,500.00`) and **zero** eu-form values — real evidence, but a
single instance, which is why registry-level detection requires three distinct
unambiguous values before adopting a convention.

**This is an open team decision, not a settled one.** Enabling `en` is
defensible for an English-language corpus and roughly triples decided outcomes;
it is also a policy choice that should be recorded rather than made silently.
Set `INTELLIGENCE_NUMERIC_LOCALE_POLICY=en` or
`INTELLIGENCE_SOURCE_NUMERIC_CONVENTION=en` to adopt it.

### Recorded interpretation question

91 emails say "please assist to send the draft BL ... for checking" with no
draft attached. The conservative selected policy classifies these as
`SI_REQUEST` (a draft is being requested, not compared) and flags the result
`unresolved`. The organizer mapping for this shape is not known.

## 7. Commands

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt

python -m pytest tests/ -q                     # everything
python -m pytest tests/intelligence/ -q        # Person A units
python -m pytest tests/integration/ -q         # worker, decisions, conformance

python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Use **one** worker-bearing server process. Point `DATABASE_URL` at a disposable
database for tests, and never run a reset fixture against a shared one.

Diagnostics (local and private; they upload nothing and call no evaluator):

```bash
python scripts/inspect_intelligence_inputs.py \
    --source resources/sdoc-hackathon-bundle \
    --output .local/input-inventory.json --parse

python scripts/run_intelligence_case.py \
    --source resources/sdoc-hackathon-bundle \
    --email-id email_004 --output .local/email_004-analysis.json

python scripts/build_demo_fixtures.py          # regenerate the demo registry
```

## 8. Configuration

See `.env.example`. Credentials stay in private environment configuration and
are never logged or included in the config identity.

`config_version` resolves to a full manifest — code release, parser versions,
policy versions, prompt hashes, the numeric policy and the provider/model
identity — digested into a single value recorded on every run. A generic `v1`
would not be reproducible.

## 9. Known limitations

- **OCR is not implemented.** Setting `INTELLIGENCE_OCR_ENABLED=true` fails
  fast rather than pretending. Six image-only PDFs in the bundle are reported
  as unreadable.
- **Semantic equivalence is off** and should stay off for scored evaluation.
- **No live model call has been executed.** The adapter, prompts, validation,
  budget, consent gate and failure mapping are implemented and tested offline
  against an injected client and a mock HTTP transport. Two cases genuinely
  depend on the provider: `email_demo_needs_model` (no rule can classify it) and
  `email_demo_ambiguous_weight` (two competing gross weights the rules refuse to
  choose between). Removing the provider changes what the system can do with
  both. A live smoke test needs credentials that do not exist in this repository.
- **Targeted AI extraction is connected, and deliberately narrow.** The model is
  asked only about fields where the document supports *several* readings the
  rules would not choose between, and it may only point at one of those blocks.
  It cannot supply a value for an absent field, relabel content, or introduce a
  number: the alias policy remains the authority on what a label means, the
  value is always recomputed from the block, and G1-G3 re-verify the result.
- **Gross weight from a column of detail rows with no declared total** is not
  extracted; only labelled values and explicit totals are. Such a document
  reports `missing_value` rather than summing rows the source did not total.
- **Port aliases are empty.** Only the validated code-consistency rule is
  applied; no pair-specific equivalence was added.
- **Participant ingestion is not yet behind authentication** — see
  `docs/person-a-integration.md`.


## 10. Correction pass (R1-R10)

An engineering review of `58f2a7e` found ten defects. Each was reproduced first,
given a regression test that fails on that commit, then fixed.

| Finding | Change |
|---|---|
| R1 | Candidates carry the private block they were read from. G1 verifies the quote against that block, G2 reads the label from it, G3 re-derives from it. A page locator is no longer proof of a label/value pairing. |
| R2 | One authoritative `load_working_state`, shared by validation and application, replaying exactly the decisions already applied. |
| R3 | The case write and the applied marker share one transaction under the run guard; a zero-row update marks nothing. |
| R4 | A supplied job id must match its decision exactly; no fallback to another pending record. |
| R5 | `allow_participant_content` is enforced at the pipeline boundary, and no provider client is built for a non-consented source. |
| R6 | `analyze_case` now calls the extraction adapter for genuinely ambiguous fields and reports real `ai_assisted_fields`. |
| R7 | Each run records its input and config identity in `run_snapshots`; a decision against changed inputs or policy fails visibly. Resumption never consults a provider, and the call budget is charged before the call. |
| R8 | Public document roles follow the operational selection. |
| R9 | Reprocessed runs are created with real pinned identities rather than `v1`. |
| R10 | Port codes are supplementary only under a versioned, source-derived table. |

Also fixed: a registry-level numeric convention now reaches G3 as well as
extraction. Previously it resolved the value during extraction and was then
rejected by the gate, producing `UNGROUNDED` — worse than either policy alone.


## 11. Second correction pass (C1-C4)

A follow-up review of `675f0d3` found four further defects. Each was reproduced,
given a regression test that fails on that commit, then fixed.

| Finding | Change |
|---|---|
| C1 | Resumption restored nothing: it disabled the model and reran the rules, so an AI classification silently became `GENERAL` and an AI-resolved field became unresolved — and acknowledging an AI-classified case crashed with `KeyError: 'shipper'`. The run now persists its full machine interpretation (classification, roles, every field outcome with block binding, evidence and provenance) in `run_snapshots.machine_state`, and resumption loads it instead of recomputing. A run with no recorded state refuses to resume rather than rebuilding an unverified one. |
| C2 | Several model proposals for one field overwrote each other, so the last one won and the count double-counted. Proposals are now collected per field, identical canonical values deduplicated, and genuinely different grounded readings left `COMPETING_CANDIDATES` for a person. A field the response both proposes and disclaims is not used. |
| C3 | `58f2a7e` and `675f0d3` shared a config identity despite changed semantics. Policy versions are now read from the modules that define them (a duplicated constant had drifted: the manifest claimed `ports-1.0.0` long after the module moved on), the tables behaviour depends on are digested into the manifest, and `CODE_RELEASE` moved to `person-a-1.2.0`. |
| C4 | The derivation accepted 3-of-7 as a "strict majority". It now requires `top > total/2` as well as the minimum count, and the table's provenance is stated honestly and gated behind team approval. |

### What resumption does and does not reconstruct

It restores the machine *interpretation* from the durable snapshot and reparses
the sources only to rebuild the artifacts the stored evidence points at, after
verifying that the input version and the configuration identity still match. It
does not archive the parsed artifacts themselves; if either identity has moved,
or the snapshot is absent, it refuses and asks for a new run rather than
guessing. No provider is ever consulted during resumption.
