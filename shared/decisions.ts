import { z } from "zod";
import type { CanonicalField, DecisionRequest } from "./types";
import { fields } from "./validation";
const id = z.string().min(1);
const scalar = z.union([z.string().min(1), z.number().finite()]);
export const overrideSchema = z.strictObject({
  review_id: id,
  run_id: id,
  field: z.enum(fields),
  side: z.enum(["SI", "BL"]),
  proposed_value: scalar,
  confirmed: z.literal(true),
});
const base = {
  review_id: id,
  run_id: id,
  channel: z.enum(["DASHBOARD", "TELEGRAM", "VOICE"]),
  actor_id: id,
  user_message: z.string().optional(),
};
export const decisionSchema = z.discriminatedUnion("action", [
  z.strictObject({
    ...base,
    action: z.literal("PROVIDE_VALUE"),
    field: z.enum(fields),
    side: z.enum(["SI", "BL"]),
    value: scalar,
    override_confirmation: overrideSchema.optional(),
  }),
  z.strictObject({
    ...base,
    action: z.literal("SELECT_OPTION"),
    option_id: id,
    override_confirmation: overrideSchema.optional(),
  }),
  z.strictObject({ ...base, action: z.literal("ACKNOWLEDGE") }),
]) satisfies z.ZodType<DecisionRequest>;
/** Canonical dashboard input, not document extraction. Numeric entry uses a dot decimal, no grouping. */
export function parseProposal(
  field: CanonicalField,
  input: string | number,
): string | number {
  const raw = String(input).trim();
  if (!raw) throw new Error("Enter a nonempty value.");
  if (field !== "container_count" && field !== "gross_weight_kg") {
    if (typeof input !== "string") throw new Error("This field requires text.");
    return raw.normalize("NFKC").replace(/\s+/g, " ").toLowerCase();
  }
  const cleaned =
    field === "gross_weight_kg"
      ? raw.replace(/\s*(kg|kgs|kilograms)$/i, "").trim()
      : raw;
  if (!/^\d+(?:\.\d+)?$/.test(cleaned))
    throw new Error(
      "Use a positive number with a decimal point, without grouping separators. Gross weight is in kg.",
    );
  const value = Number(cleaned);
  if (
    !Number.isFinite(value) ||
    value <= 0 ||
    value > Number.MAX_SAFE_INTEGER ||
    (field === "container_count" && !Number.isSafeInteger(value))
  )
    throw new Error(
      field === "container_count"
        ? "Container count must be a positive safe integer."
        : "Weight must be a positive finite number within the safe range.",
    );
  // Reject precision loss instead of silently rounding entered decimals.
  const canonical = (s: string) =>
    s
      .replace(/^0+(?=\d)/, " ")
      .trim()
      .replace(/(\.\d*?)0+$/, "$1")
      .replace(/\.$/, "");
  if (canonical(String(value)) !== canonical(cleaned))
    throw new Error(
      "This precision is not supported safely. Enter a representable canonical value.",
    );
  return value;
}
