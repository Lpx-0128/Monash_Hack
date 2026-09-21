import { useEffect, useRef, useState, type ReactNode } from "react";
import type {
  Case,
  DecisionRequest,
  FieldValue,
  OverrideConfirmation,
} from "../shared/types";
import { parseProposal } from "../shared/decisions";
import { api, isSimulation, RequestError } from "./api";

type Proposal =
  | { action: "PROVIDE_VALUE"; value: string | number }
  | { action: "SELECT_OPTION"; option_id: string; value?: string | number }
  | { action: "ACKNOWLEDGE" };
export function ReviewActions({
  c,
  onCase,
  onBusy,
  renderValue,
}: {
  c: Case;
  onCase: (c: Case) => void;
  onBusy: (busy: boolean) => void;
  renderValue: (v: FieldValue, side: string) => ReactNode;
}) {
  const r = c.review!,
    key = `${c.case_id}:${r.run_id}:${r.review_id}`;
  const [raw, setRaw] = useState(
    () => sessionStorage.getItem(`draft:${key}`) ?? "",
  );
  const [proposal, setProposal] = useState<Proposal>();
  const [override, setOverride] = useState(false),
    [busy, setBusy] = useState(false),
    [uncertain, setUncertain] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const guard = useRef(false),
    alive = useRef(true),
    errorRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      onBusy(false);
    };
  }, []);
  useEffect(() => {
    if (r.status === "CLOSED") {
      setError("");
      setProposal(undefined);
      setOverride(false);
      sessionStorage.removeItem(`draft:${key}`);
    }
  }, [r.status, key]);
  useEffect(() => {
    if (error) errorRef.current?.focus();
  }, [error]);
  const locked = busy || uncertain || r.status !== "OPEN" || !isSimulation;
  function edit(value: string) {
    setRaw(value);
    sessionStorage.setItem(`draft:${key}`, value);
    setProposal(undefined);
    setOverride(false);
    setError("");
    setNotice("");
  }
  function preview() {
    try {
      setProposal({
        action: "PROVIDE_VALUE",
        value: parseProposal(r.field!, raw),
      });
      setError("");
      setOverride(false);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  function choose(p: Proposal) {
    setProposal(p);
    setError("");
    setOverride(false);
    setNotice("");
  }
  async function refresh() {
    setBusy(true);
    onBusy(true);
    try {
      const fresh = await api.detail(c.case_id);
      if (!alive.current) return;
      onCase(fresh);
      setError("");
      setUncertain(false);
      setProposal(undefined);
      setOverride(false);
      setNotice(
        fresh.run.run_id !== r.run_id || fresh.review?.review_id !== r.review_id
          ? "The active review changed. The old proposal was discarded."
          : fresh.review.status === "CLOSED"
            ? "The review is closed. Do not resubmit; the current case shows its status."
            : "Refetch confirmed this review is still open. Your draft is retained; preview and confirm again to submit.",
      );
    } catch (e) {
      if (alive.current) {
        setUncertain(true);
        setError(
          `Cannot verify the decision state. ${(e as Error).message} Do not resubmit until a refetch succeeds.`,
        );
      }
    } finally {
      if (alive.current) {
        setBusy(false);
        onBusy(false);
        guard.current = false;
      }
    }
  }
  async function submit(manual = false) {
    if (!proposal || locked || guard.current) return;
    guard.current = true;
    setBusy(true);
    onBusy(true);
    setError("");
    setNotice("");
    const base = {
      review_id: r.review_id,
      run_id: r.run_id,
      channel: "DASHBOARD" as const,
      actor_id: "demo-guest",
    };
    const d: DecisionRequest =
      proposal.action === "PROVIDE_VALUE"
        ? {
            ...base,
            action: proposal.action,
            field: r.field!,
            side: r.side!,
            value: proposal.value,
          }
        : proposal.action === "SELECT_OPTION"
          ? { ...base, action: proposal.action, option_id: proposal.option_id }
          : { ...base, action: "ACKNOWLEDGE" };
    if (manual && d.action !== "ACKNOWLEDGE" && "value" in proposal)
      d.override_confirmation = {
        review_id: r.review_id,
        run_id: r.run_id,
        field: r.field!,
        side: r.side!,
        proposed_value: proposal.value!,
        confirmed: true,
      } satisfies OverrideConfirmation;
    try {
      const result = await api.decide(d);
      if (!alive.current) return;
      sessionStorage.removeItem(`draft:${key}`);
      setProposal(undefined);
      setOverride(false);
      setNotice(
        "202 Accepted — processing continues. This is not verification completion.",
      );
      onCase(result);
    } catch (e) {
      if (!alive.current) return;
      if (
        e instanceof RequestError &&
        [
          "VALUE_NOT_FOUND_IN_DOCUMENT",
          "OVERRIDE_CONFIRMATION_REQUIRED",
        ].includes(e.code)
      ) {
        setError(e.message);
        setOverride(true);
      } else if (e instanceof RequestError && e.status === 422) {
        setError(`${e.code}: ${e.message}`);
        setOverride(false);
        setProposal(undefined);
      } else if (e instanceof RequestError && e.status === 429) {
        setError(e.message);
        setProposal(undefined);
        setOverride(false);
      } else {
        setUncertain(true);
        setError(
          `${e instanceof RequestError ? e.code + ": " : ""}${(e as Error).message} Checking the authoritative case; this decision will not be resent automatically.`,
        );
        await refresh();
      }
    } finally {
      if (alive.current) {
        guard.current = false;
        setBusy(false);
        onBusy(false);
      }
    }
  }
  return (
    <div className="review-actions">
      {!isSimulation && (
        <p role="status">
          Live decision submission awaits a configured trusted identity
          integration. Simulator verification does not establish real-backend
          acceptance.
        </p>
      )}
      {error && (
        <div className="notice error" role="alert" tabIndex={-1} ref={errorRef}>
          <div>
            <strong>Review response needs attention</strong>
            <p id="decision-error">{error}</p>
            {r.ui_mode === "VALUE_INPUT" && (
              <a href="#review-value">Return to value input</a>
            )}
          </div>
        </div>
      )}
      {notice && (
        <p role="status" className="notice simulation">
          {notice.startsWith("202 Accepted") &&
          c.workflow_status !== "PROCESSING"
            ? c.workflow_status === "FAILED"
              ? "Accepted decision retained; operator recovery is required."
              : "Accepted decision applied. The current operational result is shown above."
            : notice}
        </p>
      )}
      {uncertain && (
        <button disabled={busy} onClick={() => void refresh()}>
          Refetch decision status
        </button>
      )}
      {r.ui_mode === "CHOICE" && (
        <div className="review-options">
          {r.options?.map((o) => (
            <div key={o.option_id}>
              <button
                disabled={
                  locked || !r.allowed_actions.includes("SELECT_OPTION")
                }
                onClick={() =>
                  choose(
                    o.kind === "VALUE"
                      ? {
                          action: "SELECT_OPTION",
                          option_id: o.option_id,
                          value: o.value.normalized!,
                        }
                      : { action: "SELECT_OPTION", option_id: o.option_id },
                  )
                }
              >
                {o.label}
              </button>
              {o.kind === "VALUE" && renderValue(o.value, r.side!)}
              {o.kind === "DOCUMENT" && (
                <a
                  href={api.documentUrl(o.document_id)}
                  target="_blank"
                  rel="noreferrer"
                >
                  Inspect candidate document ↗
                </a>
              )}
            </div>
          ))}
        </div>
      )}
      {r.ui_mode === "VALUE_INPUT" && (
        <div className="review-input">
          <label htmlFor="review-value">
            {r.side} {r.field?.replaceAll("_", " ")}
          </label>
          <p id="value-guidance">
            {r.field === "container_count"
              ? "Positive whole container count. Enter digits only."
              : r.field === "gross_weight_kg"
                ? "Gross weight in kg. Use a decimal point, no grouping separators (21707 or 21707.5)."
                : "Enter the complete labelled text, including the address where present."}
          </p>
          <input
            id="review-value"
            value={raw}
            onChange={(e) => edit(e.target.value)}
            disabled={locked}
            aria-describedby={
              error ? "value-guidance decision-error" : "value-guidance"
            }
            aria-invalid={!!error}
          />
          <button
            disabled={locked || !r.allowed_actions.includes("PROVIDE_VALUE")}
            onClick={preview}
          >
            Preview value
          </button>
          {r.allowed_actions.includes("ACKNOWLEDGE") && (
            <button
              disabled={locked}
              onClick={() => choose({ action: "ACKNOWLEDGE" })}
            >
              I can’t tell
            </button>
          )}
        </div>
      )}
      {r.ui_mode === "ACKNOWLEDGE" && (
        <>
          <p>
            <strong>Acknowledgment does not complete verification.</strong>{" "}
            Obtain a corrected source through the operator workflow; replaying
            unchanged sources will not repair them.
          </p>
          <button
            disabled={locked || !r.allowed_actions.includes("ACKNOWLEDGE")}
            onClick={() => choose({ action: "ACKNOWLEDGE" })}
          >
            {r.status === "CLOSED"
              ? "Acknowledgment recorded"
              : "Acknowledge external action"}
          </button>
        </>
      )}
      {proposal && r.status === "OPEN" && !uncertain && (
        <section
          className="proposal"
          aria-label={
            override ? "Manual override confirmation" : "Decision preview"
          }
        >
          <h3>
            {override
              ? "Source does not support this value"
              : "Confirm this proposal"}
          </h3>
          <p>
            {proposal.action === "ACKNOWLEDGE" ||
            (proposal.action === "SELECT_OPTION" &&
              proposal.option_id === "NONE_OF_THESE")
              ? "This closes the review and leaves the case externally blocked. Verification will not be complete."
              : "value" in proposal
                ? `${r.side} · ${r.field?.replaceAll("_", " ")} · canonical value: ${proposal.value}${r.field === "gross_weight_kg" ? " kg" : ""}`
                : `Assign the selected document to ${r.target_role}: ${r.options?.find((o) => o.option_id === (proposal as { option_id: string }).option_id)?.label}`}
          </p>
          {override && (
            <p>
              This value could not be verified against the {r.side} source. Use
              it as a human-provided, ungrounded manual override for this exact
              review?
            </p>
          )}
          <small className="mono">
            Review {r.review_id} · Run {r.run_id}
          </small>
          <div className="proposal-buttons">
            <button disabled={locked} onClick={() => void submit(override)}>
              {busy
                ? "Submitting…"
                : override
                  ? "Confirm manual override"
                  : "Confirm submission"}
            </button>
            <button
              disabled={busy}
              onClick={() => {
                setProposal(undefined);
                setOverride(false);
                setError("");
              }}
            >
              Cancel proposal
            </button>
          </div>
        </section>
      )}
      {r.status === "CLOSED" && (
        <p>
          Closed: {r.close_reason?.replaceAll("_", " ").toLowerCase()}. This
          review cannot accept another response.
        </p>
      )}
      <p className="review-note">
        Synthetic document grounding and delayed worker behavior are simulated.
        Human decisions update operational results; the machine assessment
        remains frozen.
      </p>
    </div>
  );
}
