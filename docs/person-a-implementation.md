# Person A — document intelligence implementation

What was built, how it behaves, what it refuses to guess, and how to run it.

- **Branch:** `claude/loving-bohr-x6whx9`, based on `main` at `72e6940`.
- **Contract:** shared contract v2.1.1, retained **unchanged**. No new wire
  field, enum value, review action or endpoint was introduced.
- **Baseline before this change:** 15 tests passed in 21.34 s.
- **After this change:** 233 tests pass in 77.17 s.

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

**A port code that contradicts its port.** The corpus contains
`BALTIMORE, US (NGAPP)` — a Nigerian code on a US port. A parenthesised
five-letter token is treated as a supplementary UN/LOCODE only when its
country prefix matches a country named in the same value. A *consistent* code
may differ in spelling (`NHAVA SHEVA, INDIA` equals `NHAVA SHEVA, INDIA
(INNSA)`); an *inconsistent* one is a real difference and is reported as one.
Terminal qualifiers such as `(WESTPORT)` are never stripped.

**A role from a filename.** `email_501_BL.txt` is a commercial invoice. Roles
come from document headings and body content; the filename only ranks
candidates. When two documents tie for a role, that is a question, not a
coin flip.

**A value that only looks right.** Every value passes three gates before it can
be compared, whether a rule, a model, a person or a candidate selection
produced it:

- **G1** the exact quote occurs at that exact location in *this run's* parsed
  artifact, with a matching content hash.
- **G2** the structural label supports that canonical field. A gross weight is
  never supported by digits sitting in a seal number, a net weight or an
  invoice amount.
- **G3** the value is re-derived from the evidence and must match exactly.

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
| `en` (',' groups, '.' decimal) | 52 | 38 | 39 |

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
  budget and failure mapping are implemented and tested offline against an
  injected client and a mock HTTP transport. `email_demo_needs_model` is a case
  the rules genuinely cannot decide — removing the provider changes what the
  system can do with it. A live smoke test needs credentials that do not exist
  in this repository.
- **Gross weight from a column of detail rows with no declared total** is not
  extracted; only labelled values and explicit totals are. Such a document
  reports `missing_value` rather than summing rows the source did not total.
- **Port aliases are empty.** Only the validated code-consistency rule is
  applied; no pair-specific equivalence was added.
- **Participant ingestion is not yet behind authentication** — see
  `docs/person-a-integration.md`.
