import type { CanonicalField, Side } from "../shared/types";
import type { ParticipantEmail } from "../shared/participant-mapping";

// Independently authored values. The participant bundle supplied structural
// reference only; no participant identities, document text or labels-as-truth.
export const syntheticValues: Record<CanonicalField, string | number> = {
  shipper: "Meridian Exports\n10 Harbour Road\nSuite 08, Demo District",
  consignee: "Straits Trading\n22 Bay Avenue\nUnit 04, Demo District",
  notify_party: "Straits Trading\n22 Bay Avenue\nUnit 04, Demo District",
  port_of_loading: "Port Klang",
  port_of_discharge: "Singapore",
  container_count: 3,
  gross_weight_kg: 21707,
};
export const documentLabels: Record<Side, Record<CanonicalField, string>> = {
  SI: {
    shipper: "Shipper (Principal or Seller)",
    consignee: "Consignee (Non-Negotiable)",
    notify_party: "Notify",
    port_of_loading: "Port of Loading (POL)",
    port_of_discharge: "POD",
    container_count: "Total Containers",
    gross_weight_kg: "Gross Wt (kgs)",
  },
  BL: {
    shipper: "SHIPPER",
    consignee: "To the Order of",
    notify_party: "NOTIFY PARTY",
    port_of_loading: "Load Port",
    port_of_discharge: "Port of Discharge (POD)",
    container_count: "No. of Containers",
    gross_weight_kg: "Gross Weight (KG)",
  },
};
export const alternateWeightQuote =
  "Gross Wt (kgs), alternate draft: 22,000 KG";
export function formatSyntheticValue(
  field: CanonicalField,
  side: Side,
  value: string | number,
) {
  if (field === "container_count")
    return side === "SI" ? `${value} x 40'HC` : `${value} × 40HC`;
  if (field === "gross_weight_kg")
    return side === "SI"
      ? `${Number(value).toLocaleString("en-US")} KG`
      : `${Number(value).toFixed(2)} kgs`;
  const text = side === "BL" ? String(value).toUpperCase() : String(value);
  return text.replaceAll("\n", "\n  ");
}

/** Only audits these controlled synthetic layouts; not a real extraction engine. */
export function canonicalSyntheticValue(
  field: CanonicalField,
  raw: string,
): string | number {
  if (field === "container_count") {
    const m = raw.match(/^(\d+)\s*[x×]\s*40'?HC$/i);
    if (!m || !Number.isSafeInteger(Number(m[1])) || Number(m[1]) <= 0)
      throw new Error("Invalid synthetic container expression");
    return Number(m[1]);
  }
  if (field === "gross_weight_kg") {
    // Every generated source explicitly declares comma grouping and dot decimals.
    const m = raw.match(/^((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s+KG(?:S)?$/i);
    if (
      !m ||
      !Number.isFinite(Number(m[1].replaceAll(",", ""))) ||
      Number(m[1].replaceAll(",", "")) <= 0
    )
      throw new Error("Invalid synthetic weight formatting");
    return Number(m[1].replaceAll(",", ""));
  }
  return raw.normalize("NFKC").trim().replace(/\s+/g, " ").toLowerCase();
}
export function supportsSyntheticField(
  quote: string,
  field: CanonicalField,
  normalized: string | number | null,
) {
  const colon = quote.indexOf(":");
  const label = quote.slice(0, colon);
  const supportedLabels = [documentLabels.SI[field], documentLabels.BL[field]];
  if (field === "gross_weight_kg")
    supportedLabels.push("Gross Wt (kgs), alternate draft");
  if (colon < 0 || !supportedLabels.includes(label)) return false;
  try {
    return (
      canonicalSyntheticValue(field, quote.slice(colon + 1).trim()) ===
      normalized
    );
  } catch {
    return false;
  }
}

export function syntheticSourceEmail(
  emailId: string,
  subject: string,
  attachments: string[],
  intentUnresolved = false,
): ParticipantEmail {
  if (emailId === "demo_non-bl")
    return {
      email_id: emailId,
      from: "operations@meridian.example",
      subject,
      body: "SYNTHETIC EMAIL — independently authored, not participant data.\nHello billing team,\nPlease explain the handling charge on synthetic invoice DEMO-INV-042. No document comparison is requested.\nRegards,\nDemo Documentation Desk",
      attachments,
    };
  return {
    email_id: emailId,
    from: "operations@meridian.example",
    subject,
    body: [
      "SYNTHETIC EMAIL — independently authored, not participant data.",
      "Hello documentation team,",
      "",
      intentUnresolved
        ? "Please prepare the draft BL from the shipment details below and revert when available. No documents are attached yet."
        : attachments.length > 1
          ? "Please check the attached shipping instruction and draft documents; advise any discrepancy."
          : attachments.length === 1
            ? "Please check the attached shipping instruction. The draft BL is missing and must be requested from the sender."
            : "Please review this synthetic correspondence. No source documents are attached.",
      "",
      "Shipper:",
      String(syntheticValues.shipper),
      "",
      "Consignee:",
      String(syntheticValues.consignee),
      "",
      "POL: Port Klang",
      "POD: Singapore",
      "Description of goods: synthetic paperboard shipment",
      "3X40'HC",
      "GROSS WT: 21,707 KG",
      "",
      "Numeric convention: comma groups thousands; dot is the decimal separator.",
      "Regards,",
      "Demo Documentation Desk",
      "operations@meridian.example",
      "",
      "______________________________",
      "From: prior-desk@meridian.example",
      "Subject: Re: SYNTHETIC booking DEMO-042",
      "Please follow the latest instructions.",
      ...(intentUnresolved
        ? [
            "",
            "Intent interpretation unresolved: this example must not be scored as an actionable skip or inferred GENERAL label.",
          ]
        : []),
    ].join("\n"),
    attachments,
  };
}
