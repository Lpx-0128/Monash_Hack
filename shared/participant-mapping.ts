import { z } from "zod";
import type { Case, RunRef } from "./types";
import { validateCase } from "./validation";

/** The inspected participant bundle has exactly these five source keys. */
export const participantEmailSchema = z.strictObject({
  email_id: z.string().min(1),
  from: z.string().min(1),
  subject: z.string(),
  body: z.string(),
  attachments: z.array(z.string().min(1)),
});
export type ParticipantEmail = z.infer<typeof participantEmailSchema>;
const intakeSchema = participantEmailSchema.extend({
  received_at: z.iso.datetime({ offset: true }).nullable().optional(),
});

/** Pure intake mapping, not extraction. Caller supplies namespace/run and system creation time.
 * Missing source receipt is null; malformed supplied receipt raises a source-validation error.
 * Attachment paths/body are retained as source context, never fetched or parsed here.
 */
export function mapParticipantToCase(
  input: unknown,
  context: { run: RunRef; created_at: string },
): Case {
  const source = intakeSchema.parse(input);
  return validateCase({
    schema_version: "2.1.2",
    case_id: source.email_id,
    run: context.run,
    email: {
      email_id: source.email_id,
      from: source.from,
      subject: source.subject,
      received_at:
        source.received_at == null
          ? null
          : new Date(source.received_at).toISOString(),
      category: null,
      classified_by: null,
      classification_reason: null,
    },
    documents: [],
    workflow_status: "PROCESSING",
    machine_assessment: null,
    fields: [],
    review: null,
    resolution: null,
    follow_up: "NONE",
    failure: null,
    history: [
      {
        event_id: `${context.run.run_id}_created`,
        run_id: context.run.run_id,
        at: context.created_at,
        type: "CASE_CREATED",
        actor: { kind: "SYSTEM", id: null },
        summary:
          "Source email accepted; classification and attachment parsing pending.",
        details: { source_email: source },
      },
    ],
    metrics: {
      ai_calls: 0,
      ai_assisted_fields: 0,
      processing_ms: null,
      est_ai_cost_usd: null,
    },
    created_at: context.created_at,
    updated_at: context.created_at,
    completed_at: null,
  });
}
