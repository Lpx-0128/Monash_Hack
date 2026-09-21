import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { participantEmailSchema, type ParticipantEmail } from "../shared/participant-mapping";
import { validateCase } from "../shared/validation";
import { makeFixture, type Scenario } from "./fixtures";

export function loadDataset(file: string): ParticipantEmail[] {
  const emails = participantEmailSchema.array().min(1).max(1000).parse(JSON.parse(readFileSync(file, "utf8")));
  if (new Set(emails.map(e => e.email_id)).size !== emails.length)
    throw new Error("Duplicate dataset email IDs");
  return emails;
}

/** Illustrative outcomes, never a classifier or organiser ground truth.
 * Original correspondence is retained separately from generated training evidence.
 */
export function datasetScenario(source: ParticipantEmail): Scenario {
  if (!source.attachments.length) return "non-bl";
  if (source.attachments.length === 1) return "blocked-open";
  const choices: Scenario[] = ["match", "match", "match", "mismatch", "grounded-input", "candidate-choice", "field-input", "document-choice"];
  return choices[createHash("sha256").update(source.email_id).digest()[0] % choices.length];
}

export function makeDatasetFixture(source: ParticipantEmail, documents: Map<string, string>, runId: string) {
  const scenario = datasetScenario(source);
  const base = makeFixture(scenario, documents, runId);
  // Fixture references to case IDs also occur inside archived review history.
  const replace = (value: unknown): unknown => {
    if (value === base.case_id) return source.email_id;
    if (Array.isArray(value)) return value.map(replace);
    if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([k,v]) => [k, replace(v)]));
    return value;
  };
  const c = validateCase(replace(base));
  c.email.email_id = source.email_id;
  c.email.from = source.from;
  c.email.subject = source.subject;
  c.email.received_at = null;
  c.email.classification_reason = "SIMULATED outcome for workflow demonstration; not analysis of the organiser email or its attachments.";
  if (scenario === "non-bl") {
    const categories = ["SI_REQUEST", "INVOICE_QUERY", "GENERAL", "SPAM"] as const;
    c.email.category = categories[createHash("sha256").update(source.email_id).digest()[1] % categories.length];
    for (const event of c.history) if (event.type === "EMAIL_CLASSIFIED") event.summary = "Illustrative non-comparison category; no classification performed.";
  }
  c.run.input_version = "organiser-520-simulated-v1";
  const created = c.history.find(h => h.type === "CASE_CREATED")!;
  created.summary = "Organiser email represented in mock mode; outcomes and review documents are simulated.";
  created.details = {
    source_email: source,
    receipt_timestamp_provenance: "SOURCE_ABSENT",
    outcome_provenance: "SIMULATED_NOT_GROUND_TRUTH",
    evidence_provenance: "GENERATED_PRACTICE_DOCUMENTS_NOT_ORGANISER_ATTACHMENTS",
  };
  return validateCase(c);
}
