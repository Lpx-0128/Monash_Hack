# Participant reference review — F0 continuation

Reviewed 19 September 2026. This is a structural reference review, not extraction, classification tuning or dataset evaluation.

## Sources and allowed scope

- [Official problem statement](https://drive.google.com/file/d/1BV6-ljccjmqZm4MVmwg3O89mUuEJkyze/view): the participant-facing Shipping Document Verification Use Case PDF.
- [Static participant bundle](https://drive.google.com/file/d/1K5WH580YwXHfmSpyfw-4ju0SnqD1gZOP/view): `sdoc-hackathon-bundle.zip`, selected from the supplied folder by name and MIME type.
- Read the participant README, inspected source email structure, representative plain-text SI/BL layouts and the submission template's shape. Reference examples: `email_004` with its SI/BL, `email_198_SI.txt`, `email_367_BL.txt`, and one no-attachment email. Original identities and content were not copied into public fixtures.
- The static ZIP contains only `README.md`, `loader.py`, `sample_submission.json`, `inbox/` and `attachments/` at its root. No private key or organizer-only material was inspected. The separate Docker distribution was not opened. No self-evaluation endpoint, real extraction pipeline or Hermes setup was run.
- The downloaded reference ZIP stays under ignored `.local/reference/`; it is excluded from Git and the Docker build context. Neither the web client nor the server serves it. Only newly authored synthetic material is exposed.

## Verified input facts

All **520** participant email records have exactly these five keys: `email_id`, `from`, `subject`, `body`, `attachments`. Attachments are arrays of relative path strings. There is **no `received_at`**. Dates in quoted correspondence, file modification metadata and ingestion time are not receipt timestamps.

Archive inventory: **250** attachments: 192 TXT, 28 PDF, 22 XLSX and 8 DOCX. Only representative TXT content was used for fixture-layout design; richer-format parsing/rendering is not claimed verified.

The representative plain-text layouts use document titles and dividers, multiline party blocks, additional non-comparison fields and varied labels such as `Shipper (Principal or Seller)`, `Consignee (Non-Negotiable)`, `To the Order of`, `Notify`, `POD`, `Total Containers`, `No. of Containers`, and `Gross Wt (kgs)`. Container expressions include a quantity and equipment type (for example `6 x 40'HC`), and weights include grouping and explicit KG units.

The simulator adopts these structural patterns with independent names, addresses, subjects, correspondence and references. SI/BL case, whitespace and label variations are intentional. Generated documents explicitly declare numeric punctuation conventions, avoiding a claim that ambiguous punctuation can always be interpreted. The fixture audit verifies bytes, exact evidence ranges, correct field labels and canonical values. It is a controlled synthetic consistency check, not a participant document parser.

## `sample_submission.json` is not ground truth

The template has 520 email-ID entries, all with `category: GENERAL`, `status: OK`, `review_reason: null`, `defect_fields: []`, and `has_defect: false`. These are **format placeholders**, not labels. The participant guide describes it as the required submission shape and says participants do not have ground truth.

No production code imports this file, derives fixture classifications from it, or uses it as expected output. Simulator outcomes are independently authored scenarios. Full dataset coverage, real classification accuracy and scoring are future work.

## No-attachment intent is unresolved

Some correspondence requests preparation of a draft to be returned later rather than supplying two documents. This does not authorize a new category, NOT_READY wire status, GENERAL label from the template, or silently skipped comparison.

The new `demo_no-attachment-intent` fixture explicitly records the unresolved interpretation in its context. It follows the existing contract baseline: BL_COMPARISON, NEEDS_REVIEW / missing_attachment, BLOCKED_EXTERNAL, all seven fields NOT_COMPARABLE, no defects and no completion timestamp. Its acknowledgment is preview-only in F0. Replay remains blocked. This is an authored baseline scenario, not a verified classification of a participant email. Resolve the actual intent mapping through participant-facing clarification and coordinated A/B/C approval before changing behavior.

See [SC-01 receipt timestamp discrepancy](shared-contract-discrepancies.md) for the superseding v2.1.1 adoption: source absence now maps to null without blocking conversion.
