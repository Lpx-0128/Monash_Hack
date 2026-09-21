import { Check, Clock3, Pause, TriangleAlert } from "lucide-react";
import type { Case } from "../shared/types";

/** Progress comes from this run's recorded events, never elapsed time. */
export function CaseProgress({ c }: { c: Case }) {
  const events = c.history.filter((event) => event.run_id === c.run.run_id);
  const has = (type: string) => events.some((event) => event.type === type);
  const running = c.workflow_status === "PROCESSING";
  const stages = [
    { label: "Received", done: true },
    { label: "Classified", done: has("EMAIL_CLASSIFIED") },
    { label: "Documents parsed", done: has("DOCUMENT_PARSED") },
    { label: "Compared", done: has("COMPARISON_COMPLETED") },
  ];
  const accepted = has("DECISION_RECEIVED");
  const outcome =
    c.workflow_status === "FAILED"
      ? "Processing failed"
      : c.workflow_status === "BLOCKED_EXTERNAL"
        ? "Awaiting external source"
        : c.workflow_status === "AWAITING_HUMAN"
          ? "Needs your decision"
          : running
            ? accepted
              ? "Resuming after decision"
              : "Processing"
            : c.follow_up === "CORRECTION_REQUIRED"
              ? "Correction required"
              : "Processing complete";
  return (
    <section
      className={`case-progress ${running ? "is-running" : ""}`}
      aria-label="Case processing progress"
    >
      <div className="progress-heading">
        <span className="eyebrow">CASE PROGRESS</span>
        <strong>{outcome}</strong>
      </div>
      <ol className="progress-stages">
        {stages.map((stage) => (
          <li key={stage.label} className={stage.done ? "done" : "unrecorded"}>
            <span className="stage-icon">
              {stage.done ? (
                <Check size={14} aria-hidden="true" />
              ) : (
                <span>—</span>
              )}
            </span>
            <span>
              {stage.label}
              <small>{stage.done ? "Recorded" : "Not recorded"}</small>
            </span>
          </li>
        ))}
        <li
          className={`current ${c.workflow_status.toLowerCase()}`}
          aria-current="step"
        >
          <span className="stage-icon">
            {running ? (
              <Clock3 size={16} aria-hidden="true" />
            ) : c.workflow_status === "FAILED" ? (
              <TriangleAlert size={16} aria-hidden="true" />
            ) : c.workflow_status === "COMPLETED" && c.follow_up === "NONE" ? (
              <Check size={16} aria-hidden="true" />
            ) : (
              <Pause size={16} aria-hidden="true" />
            )}
          </span>
          <span>
            {outcome}
            <small>
              {accepted
                ? "Decision received in this run"
                : "Current case state"}
            </small>
          </span>
        </li>
      </ol>
    </section>
  );
}
