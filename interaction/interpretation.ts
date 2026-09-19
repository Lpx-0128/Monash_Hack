import { z } from "zod";
import type { Case, DecisionRequest } from "../shared/types";
import { parseProposal } from "../shared/decisions";

export const interpretationSchema = z.strictObject({
  status: z.enum(["PROPOSE", "CLARIFY"]),
  action: z.enum(["PROVIDE_VALUE", "SELECT_OPTION", "ACKNOWLEDGE"]).nullable(),
  field: z.string().nullable(),
  side: z.enum(["SI", "BL"]).nullable(),
  target_role: z.enum(["SI", "BL"]).nullable(),
  value: z.union([z.string().min(1).max(500), z.number().finite()]).nullable(),
  option_id: z.string().max(200).nullable(),
  reason: z.string().max(300),
});
export type Interpretation = z.infer<typeof interpretationSchema>;
export type Interpreter = (
  input: ReturnType<typeof interpretationInput>,
) => Promise<unknown>;
export function deterministicValue(c: Case, text: string): string | number {
  const field = c.review!.field!;
  if (field === "gross_weight_kg") {
    const units = text
      .trim()
      .match(/^(\d+(?:\.\d+)?)\s*(tonnes?|metric tons?|grams?|g)$/i);
    if (units) {
      const [whole, fraction = ""] = units[1].split(".");
      const digits = whole + fraction;
      const point = whole.length + (/^(grams?|g)$/i.test(units[2]) ? -3 : 3);
      const converted =
        point <= 0
          ? "0." + "0".repeat(-point) + digits
          : point >= digits.length
            ? digits + "0".repeat(point - digits.length)
            : digits.slice(0, point) + "." + digits.slice(point);
      return parseProposal(field, converted);
    }
  }
  if (
    field &&
    !["gross_weight_kg", "container_count"].includes(field) &&
    /\b(I think|it says|please use|could be)\b/i.test(text)
  )
    throw new Error("Natural language requires interpretation");
  return parseProposal(field, text);
}
export function interpretationInput(c: Case, text: string) {
  const r = c.review!;
  return {
    text: text.slice(0, 2000),
    review: {
      scope: r.scope,
      ui_mode: r.ui_mode,
      field: r.field,
      side: r.side,
      target_role: r.target_role,
      question: r.question,
      allowed_actions: r.allowed_actions,
      options: (r.options ?? []).map((o) => ({
        option_id: o.option_id,
        label: o.label,
        kind: o.kind,
      })),
    },
  };
}
export function interpretationGuard(c: Case, text: string): string | null {
  const r = c.review!;
  if (text.length > 2000)
    return "Keep the reply under 2,000 characters, or use the review buttons.";
  if (/\d,\d/.test(text))
    return "The comma is ambiguous. Enter a number without grouping separators.";
  if (
    /-ish\b|\b(approximately|approx|roughly|around|about|almost|nearly)\b/i.test(
      text,
    )
  )
    return "Please provide an exact value; an approximation cannot be confirmed as a precise measurement.";
  if (/-\s*\d|\b(minus|negative|zero)\b/i.test(text))
    return "Enter a positive value; negative or zero values cannot be proposed.";
  if (
    r.side &&
    new RegExp(`\\b${r.side === "SI" ? "BL" : "SI"}\\b`, "i").test(text)
  )
    return `This review targets ${r.side}. Reply only for that side, or use the dashboard.`;
  if (
    /\b(ignore|system prompt|developer|override instructions|auto.?submit|confirmed\s*=)\b/i.test(
      text,
    )
  )
    return "Use a value or the review buttons; instructions cannot change this review's rules.";
  if (/\b(not|instead|either|maybe|perhaps|or)\b/i.test(text))
    return "Please clarify one intended value or option; the reply contains uncertainty or a correction.";
  if ((text.match(/\d+(?:\.\d+)?/g) ?? []).length > 1)
    return "Please specify one value for this review.";
  return null;
}
export function interpretedDecision(
  c: Case,
  actor: string,
  text: string,
  raw: unknown,
): DecisionRequest | null {
  const p = interpretationSchema.parse(raw),
    r = c.review!;
  if (p.status === "CLARIFY") return null;
  if (
    !p.action ||
    !r.allowed_actions.includes(p.action) ||
    p.field !== r.field ||
    p.side !== r.side ||
    p.target_role !== r.target_role
  )
    throw new Error(
      "Interpretation target or action does not match the active review.",
    );
  const base = {
    review_id: r.review_id,
    run_id: c.run.run_id,
    actor_id: actor,
    channel: "TELEGRAM" as const,
    user_message: text,
  };
  if (p.action === "PROVIDE_VALUE") {
    if (
      r.ui_mode !== "VALUE_INPUT" ||
      !r.field ||
      !r.side ||
      p.value === null ||
      p.option_id !== null
    )
      throw new Error("Invalid interpreted value.");
    return {
      ...base,
      action: p.action,
      field: r.field,
      side: r.side,
      value: parseProposal(r.field, p.value),
    };
  }
  if (p.action === "SELECT_OPTION") {
    if (
      r.ui_mode !== "CHOICE" ||
      p.value !== null ||
      !r.options?.some((o) => o.option_id === p.option_id)
    )
      throw new Error("Unknown interpreted option.");
    return { ...base, action: p.action, option_id: p.option_id! };
  }
  if (p.value !== null || p.option_id !== null)
    throw new Error("Invalid acknowledgment proposal.");
  return { ...base, action: p.action };
}
