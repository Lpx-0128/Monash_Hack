import { ReviewActions } from "./ReviewActions";
import { useEffect, useState, type ReactNode } from "react";
import {
  Anchor,
  ArrowDownLeft,
  ArrowRight,
  Check,
  CircleHelp,
  Clock3,
  FileText,
  LayoutDashboard,
  ListFilter,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  SlidersHorizontal,
  TriangleAlert,
  X,
} from "lucide-react";
import type {
  Case,
  CaseSummary,
  FieldValue,
  Review,
  Stats,
} from "../shared/types";
import {
  categories,
  effectiveStatus,
  statuses,
  workflows,
} from "../shared/validation";
import { api, demoControl, isSimulation, type Filters } from "./api";
import { usePoll } from "./usePoll";
import { participantEmailSchema } from "../shared/participant-mapping";

const titles: Record<string, string> = {
  PROCESSING: "Processing",
  AWAITING_HUMAN: "Awaiting human",
  BLOCKED_EXTERNAL: "External block",
  COMPLETED: "Completed",
  FAILED: "Failed",
  OK: "OK",
  MISMATCH: "Mismatch",
  NEEDS_REVIEW: "Needs review",
  BL_COMPARISON: "BL comparison",
  SI_REQUEST: "SI request",
  INVOICE_QUERY: "Invoice enquiry",
  GENERAL: "General",
  SPAM: "Spam",
  DOCUMENT_EXTRACTED: "Extracted",
  DOCUMENT_CONFIRMED: "Human document-confirmed",
  MANUAL_OVERRIDE: "Manual override",
  CORRECTION_REQUIRED: "Correction required",
  AWAIT_EXTERNAL: "Awaiting external source",
};
const fieldTitles: Record<string, string> = {
  shipper: "Shipper",
  consignee: "Consignee",
  notify_party: "Notify party",
  port_of_loading: "Port of loading",
  port_of_discharge: "Port of discharge",
  container_count: "Container count",
  gross_weight_kg: "Gross weight (kg)",
};
const human = (v: string) => titles[v] ?? v.toLowerCase().replaceAll("_", " ");
const date = (v: string | null) =>
  v === null
    ? "Received time unavailable"
    : new Date(v).toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
function Badge({
  value,
  children,
}: {
  value: string | null;
  children?: ReactNode;
}) {
  return (
    <span className={`badge ${value?.toLowerCase() ?? "unknown"}`}>
      {children ?? (value ? human(value) : "Not assessed")}
    </span>
  );
}
function useRoute() {
  const [path, setPath] = useState(location.pathname + location.search);
  useEffect(() => {
    const f = () => setPath(location.pathname + location.search);
    addEventListener("popstate", f);
    return () => removeEventListener("popstate", f);
  }, []);
  return path;
}
function go(path: string) {
  history.pushState(null, "", path);
  dispatchEvent(new PopStateEvent("popstate"));
  window.scrollTo(0, 0);
}
function Link({
  to,
  children,
  className,
}: {
  to: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <a
      className={className}
      href={to}
      onClick={(e) => {
        if (!e.ctrlKey && !e.metaKey && !e.shiftKey && e.button === 0) {
          e.preventDefault();
          go(to);
        }
      }}
    >
      {children}
    </a>
  );
}
function Panel({
  title,
  subtitle,
  children,
  action,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <h2>{title}</h2>
          {subtitle && <p>{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}
function ErrorState({
  error,
  retry,
  stale = false,
}: {
  error: Error;
  retry: () => void;
  stale?: boolean;
}) {
  return (
    <div className="notice error" role="alert">
      <TriangleAlert aria-hidden="true" size={20} />
      <div>
        <strong>
          {stale
            ? "Connection interrupted · showing stale data"
            : "Data unavailable"}
        </strong>
        <p>{error.message}</p>
      </div>
      <button onClick={retry}>Retry</button>
    </div>
  );
}
function Loading() {
  return (
    <div className="loading" role="status">
      <RefreshCw aria-hidden="true" size={20} /> Loading current API data…
    </div>
  );
}
function Empty({
  title = "No cases to show",
  children,
}: {
  title?: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      <FileText size={30} aria-hidden="true" />
      <h3>{title}</h3>
      <p>
        {children ??
          "Adjust your filters or reset the synthetic demonstration."}
      </p>
    </div>
  );
}

export function App({
  initialFault = "none",
  initialDecisionFault = "none",
  sharedTelegramDemo = false,
}: {
  initialFault?: string;
  initialDecisionFault?: string;
  sharedTelegramDemo?: boolean;
}) {
  const path = useRoute(),
    [refresh, setRefresh] = useState(0),
    [controls, setControls] = useState(false),
    [busy, setBusy] = useState(false),
    [controlMessage, setControlMessage] = useState(""),
    [fault, setFault] = useState(initialFault),
    [decisionFault, setDecisionFault] = useState(initialDecisionFault);
  const retry = () => setRefresh((v) => v + 1),
    isCases = path.startsWith("/cases");
  async function control(
    action: "reset" | "advance" | "fault" | "decision-fault",
    body: object = {},
    message = "Demo updated.",
  ) {
    setBusy(true);
    setControlMessage("");
    try {
      await demoControl(action, body);
      setControlMessage(message);
      retry();
      if (action === "reset") {
        setFault("none");
        setDecisionFault("none");
        go("/");
      }
    } catch (e) {
      setControlMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="app">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <aside className="sidebar">
        <Link to="/" className="brand">
          <span className="brand-icon">
            <Anchor size={25} aria-hidden="true" />
          </span>
          <span>
            Harbor<span className="brand-sub">REVIEW WORKSPACE</span>
          </span>
        </Link>
        <div className="workspace-label">OPERATIONS</div>
        <nav aria-label="Main navigation">
          <Link to="/" className={!isCases ? "nav-link active" : "nav-link"}>
            <LayoutDashboard size={19} aria-hidden="true" />
            Overview
          </Link>
          <Link
            to="/cases"
            className={isCases ? "nav-link active" : "nav-link"}
          >
            <ListFilter size={19} aria-hidden="true" />
            All cases
          </Link>
          <Link to="/cases?has_open_review=true" className="nav-link">
            <CircleHelp size={19} aria-hidden="true" />
            Review queue
          </Link>
        </nav>
        <div className="sidebar-bottom">
          <ShieldCheck size={22} aria-hidden="true" />
          <strong>
            {isSimulation ? "Safe to explore" : "Connected workspace"}
          </strong>
          <p>
            {isSimulation
              ? "Synthetic documents. Isolated demo session. No real shipments."
              : "Server-authorized cases only."}
          </p>
          <span className="contract-label">SHARED CONTRACT v2.1.1</span>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div className="breadcrumb">
            Workspace <span>/</span>{" "}
            <strong>{isCases ? "Cases" : "Overview"}</strong>
          </div>
          <div className="top-actions">
            <span className="environment">
              <span />
              {isSimulation ? "SYNTHETIC DEMO" : "LIVE API"}
            </span>
            {isSimulation && (
              <button
                className="button quiet"
                aria-expanded={controls}
                onClick={() => setControls(!controls)}
              >
                <SlidersHorizontal size={16} aria-hidden="true" />
                Demo controls
              </button>
            )}
            <span className="avatar" aria-label="Demo guest">
              DG
            </span>
          </div>
        </header>
        {controls && (
          <section className="demo-controls" aria-label="Demo controls">
            <div>
              <strong>Simulation controls</strong>
              <p>
                Seeded processing examples stay inspectable until advanced.
                Replays finish after 8 seconds. Resets affect only this browser
                session.
              </p>
            </div>
            <div className="control-row">
              <button
                disabled={busy}
                onClick={() =>
                  void control(
                    "advance",
                    {},
                    "Seeded processing states advanced.",
                  )
                }
              >
                <ArrowRight size={16} aria-hidden="true" />
                Advance processing
              </button>
              <button
                disabled={busy}
                onClick={() =>
                  void control(
                    "reset",
                    {},
                    "Demo reset to 23 known synthetic cases.",
                  )
                }
              >
                <RotateCcw size={16} aria-hidden="true" />
                Reset demo
              </button>
              <button
                disabled={busy}
                onClick={() =>
                  void control(
                    "reset",
                    { empty: true },
                    "Empty dataset loaded.",
                  )
                }
              >
                Load empty dataset
              </button>
              <label>
                Connection
                <select
                  aria-label="Connection"
                  value={fault}
                  disabled={busy}
                  onChange={(e) => {
                    setFault(e.target.value);
                    void control(
                      "fault",
                      { mode: e.target.value },
                      `Connection mode: ${e.target.value}.`,
                    );
                  }}
                >
                  <option value="none">Normal</option>
                  <option value="slow">Slow / loading</option>
                  <option value="outage">Service outage</option>
                  <option value="denied">Access denied</option>
                </select>
              </label>
              <label>
                Next decision simulation
                <select
                  aria-label="Next decision simulation"
                  value={decisionFault}
                  onChange={(e) => {
                    setDecisionFault(e.target.value);
                    void control(
                      "decision-fault",
                      { mode: e.target.value },
                      "Decision simulation updated.",
                    );
                  }}
                >
                  <option value="none">Normal delayed resumption</option>
                  <option value="lost-response">
                    Accept, then lose response once
                  </option>
                  <option value="fail-resumption">
                    Accept, then fail resumption
                  </option>
                </select>
              </label>
            </div>
            <p role="status">
              {busy ? "Updating demonstration…" : controlMessage}
            </p>
          </section>
        )}
        <main id="main" tabIndex={-1}>
          {path.split("?")[0] === "/" ? (
            <Overview refresh={refresh} retry={retry} />
          ) : path.split("?")[0] === "/cases" ? (
            <Cases
              key={path}
              query={path.split("?")[1] ?? ""}
              refresh={refresh}
              retry={retry}
            />
          ) : path.startsWith("/cases/") ? (
            <Detail
              key={path}
              id={decodeURIComponent(path.split("?")[0].slice(7))}
              refresh={refresh}
              retry={retry}
            />
          ) : (
            <Empty title="Page not found">
              <Link to="/">Return to overview</Link>
            </Empty>
          )}
        </main>
        <footer>
          Harbor Review{" "}
          <span>
            {sharedTelegramDemo ? "F2" : "F1"} ·{" "}
            {isSimulation
              ? sharedTelegramDemo
                ? "Shared synthetic demo. Telegram delivery requires the authorized gateway. No real AI extraction."
                : "Predefined simulation. No AI extraction or notifications run."
              : "Live API adapter. Review actions available in F1."}
          </span>
        </footer>
      </div>
    </div>
  );
}
function Overview({ refresh, retry }: { refresh: number; retry: () => void }) {
  const { data, error, loading, updated } = usePoll(
    `overview:${refresh}`,
    async (signal) => {
      const [stats, cases] = await Promise.all([
        api.stats(signal),
        api.list({}, signal),
      ]);
      return { stats, cases };
    },
  );
  const s = data?.stats,
    cases = data?.cases ?? [],
    queue = cases.filter((c) => c.has_open_review),
    acknowledged = cases.filter(
      (c) => c.workflow_status === "BLOCKED_EXTERNAL" && !c.has_open_review,
    ).length;
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">YOUR OPERATIONS, AT A GLANCE</div>
          <h1>Keep shipments moving.</h1>
          <p>
            A clear view of what’s settled, what needs you, and what comes next.
          </p>
        </div>
        <Link to="/cases" className="button primary">
          Explore cases <ArrowRight size={17} aria-hidden="true" />
        </Link>
      </div>
      <div className="notice simulation">
        <ShieldCheck size={20} aria-hidden="true" />
        <div>
          <strong>
            {isSimulation
              ? "A safe place to rehearse."
              : "Current authorized scope."}
          </strong>{" "}
          {isSimulation
            ? "Every case and document is synthetic. Review actions use simulated grounding and processing."
            : "Showing data from the configured API."}
        </div>
      </div>
      {error && <ErrorState error={error} retry={retry} stale={!!data} />}{" "}
      {loading && <Loading />}
      {s && (
        <>
          <div className="metric-grid">
            <Metric
              title="Total cases"
              value={s.total_cases}
              note="Latest run per DEMO case"
            />
            <Metric
              title="Pending decisions"
              value={s.awaiting_human_now}
              note="Open reviews needing attention"
              accent
            />
            <Metric
              title="Auto-completed"
              value={s.auto_completed}
              note="Completed with zero reviews"
            />
            <Metric
              title="Visible failures"
              value={s.by_workflow.FAILED}
              note="Operator recovery required"
              warning={s.by_workflow.FAILED > 0}
            />
          </div>
          <div className="overview-grid">
            <Panel
              title="Attention queue"
              subtitle="The next step is always explicit."
              action={
                <Link to="/cases?has_open_review=true">
                  View queue <ArrowRight size={14} aria-hidden="true" />
                </Link>
              }
            >
              {queue.length ? (
                <div className="attention-list">
                  {queue.slice(0, 4).map((c) => (
                    <Link
                      to={`/cases/${c.case_id}`}
                      key={c.case_id}
                      className="attention-item"
                    >
                      <span
                        className={`queue-icon ${c.workflow_status === "BLOCKED_EXTERNAL" ? "external" : ""}`}
                      >
                        <CircleHelp size={20} aria-hidden="true" />
                      </span>
                      <div>
                        <strong>{c.subject}</strong>
                        <small>
                          {c.case_id.replace("demo_", "").replaceAll("-", " ")}{" "}
                          · {c.from}
                        </small>
                      </div>
                      <ArrowRight size={17} aria-hidden="true" />
                    </Link>
                  ))}
                </div>
              ) : (
                <Empty title="No pending decisions">
                  Acknowledged external blocks remain visible in the workflow
                  summary.
                </Empty>
              )}
              <div className="panel-foot">
                <span className="dot amber" />
                {acknowledged} acknowledged external{" "}
                {acknowledged === 1 ? "block" : "blocks"} · follow-up still
                needed
              </div>
            </Panel>
            <Panel
              title="Workflow distribution"
              subtitle="Processing state, independent of the verdict."
            >
              <div className="workflow-list">
                {workflows.map((w) => (
                  <Link
                    className="workflow-row"
                    to={`/cases?workflow_status=${w}`}
                    key={w}
                  >
                    <div>
                      <span className={`dot ${w.toLowerCase()}`} />
                      {human(w)}
                      <strong>{s.by_workflow[w]}</strong>
                    </div>
                    <div className="bar-track">
                      <span
                        className={w.toLowerCase()}
                        style={{
                          width: `${s.total_cases ? (s.by_workflow[w] / s.total_cases) * 100 : 0}%`,
                        }}
                      />
                    </div>
                  </Link>
                ))}
              </div>
            </Panel>
          </div>
          <div className="outcome-grid">
            <StatusPanel
              title="Frozen machine assessment"
              subtitle="The original automated result is never rewritten."
              counts={s.by_machine_status}
              extra={`${s.unclassified} unclassified · ${s.total_cases - Object.values(s.by_machine_status).reduce((a, b) => a + b, 0)} not assessed`}
            />
            <StatusPanel
              title="Current operational outcome"
              subtitle="Latest applied resolution, or the machine result."
              counts={s.by_effective_status}
              extra="Processing and failure stay visible independently."
            />
          </div>
          <div className="facts-strip">
            <span>
              <strong>{s.ai_assisted_cases}</strong> AI-assisted runs{" "}
              <small>
                {isSimulation ? "No AI calls in this simulation" : ""}
              </small>
            </span>
            <span>
              <strong>{s.bl_comparison.total}</strong> assessed BL comparisons
            </span>
            <span>
              <strong>
                {s.avg_processing_ms === null
                  ? "—"
                  : `${Math.round(s.avg_processing_ms)} ms`}
              </strong>{" "}
              mean active processing{" "}
              <small>{isSimulation ? "Synthetic fixture metric" : ""}</small>
            </span>
          </div>
          <div className="sync-line">
            <span className="dot completed" />{" "}
            {error ? "Last successful refresh" : "Polling every 3 seconds"} ·{" "}
            {updated?.toLocaleTimeString()}
          </div>
        </>
      )}
    </>
  );
}
function Metric({
  title,
  value,
  note,
  accent,
  warning,
}: {
  title: string;
  value: number;
  note: string;
  accent?: boolean;
  warning?: boolean;
}) {
  return (
    <section className={`metric ${accent ? "accent" : ""}`}>
      <div>
        {title}
        {warning ? (
          <TriangleAlert size={17} aria-hidden="true" />
        ) : (
          <ArrowDownLeft size={17} aria-hidden="true" />
        )}
      </div>
      <strong>{value.toString().padStart(2, "0")}</strong>
      <p>{note}</p>
    </section>
  );
}
function StatusPanel({
  title,
  subtitle,
  counts,
  extra,
}: {
  title: string;
  subtitle: string;
  counts: Stats["by_machine_status"];
  extra: string;
}) {
  return (
    <Panel title={title} subtitle={subtitle}>
      <div className="status-counts">
        {statuses.map((s) => (
          <div key={s}>
            <Badge value={s} />
            <strong>{counts[s]}</strong>
          </div>
        ))}
      </div>
      <div className="panel-foot">{extra}</div>
    </Panel>
  );
}
function Cases({
  query,
  refresh,
  retry,
}: {
  query: string;
  refresh: number;
  retry: () => void;
}) {
  const params = new URLSearchParams(query);
  const [filters, setFilters] = useState<Filters>(Object.fromEntries(params));
  const [search, setSearch] = useState(""),
    [createBusy, setCreateBusy] = useState(false),
    [createError, setCreateError] = useState<Error>();
  const { data, error, loading } = usePoll(
    `cases:${JSON.stringify(filters)}:${refresh}`,
    (signal) => api.list(filters, signal),
  );
  const visible = data?.filter((c) =>
    `${c.subject} ${c.case_id} ${c.from}`
      .toLowerCase()
      .includes(search.toLowerCase()),
  );
  async function create() {
    setCreateBusy(true);
    setCreateError(undefined);
    try {
      const c = await api.create("demo_match");
      go(`/cases/${c.case_id}`);
    } catch (e) {
      setCreateError(e as Error);
      retry();
    } finally {
      setCreateBusy(false);
    }
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">SHIPMENT WORKSPACE</div>
          <h1>All cases</h1>
          <p>Inspect the evidence. Understand the next step.</p>
        </div>
        {isSimulation && (
          <button
            className="primary"
            disabled={createBusy}
            onClick={() => void create()}
          >
            {createBusy ? "Opening fixture…" : "Process sample email"}
            <ArrowRight size={17} aria-hidden="true" />
          </button>
        )}
      </div>
      {createError && <ErrorState error={createError} retry={retry} />}
      <section className="panel filter-panel" aria-label="Case filters">
        <label className="search-label">
          Search cases
          <input
            type="search"
            placeholder="Subject, sender or case ID"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <div className="filter-grid">
          {(
            [
              { key: "workflow_status", label: "Workflow", options: workflows },
              { key: "category", label: "Category", options: categories },
              {
                key: "final_status",
                label: "Operational outcome",
                options: statuses,
              },
              {
                key: "has_open_review",
                label: "Review state",
                options: ["true", "false"],
              },
            ] as const
          ).map(({ key, label, options }) => (
            <label key={key}>
              {label}
              <select
                aria-label={label}
                value={filters[key] ?? ""}
                onChange={(e) =>
                  setFilters((f) => ({ ...f, [key]: e.target.value }))
                }
              >
                <option value="">All</option>
                {options.map((o) => (
                  <option key={o} value={o}>
                    {o === "true"
                      ? "Open review"
                      : o === "false"
                        ? "No open review"
                        : human(o)}
                  </option>
                ))}
              </select>
            </label>
          ))}
          <button
            className="quiet"
            onClick={() => {
              setFilters({});
              setSearch("");
            }}
          >
            Clear filters
          </button>
        </div>
      </section>
      {error && <ErrorState error={error} retry={retry} stale={!!data} />}{" "}
      {loading && <Loading />}
      {visible && (
        <Panel
          title={`${visible.length} ${visible.length === 1 ? "case" : "cases"}`}
          subtitle="Synthetic fixtures · current runs only"
        >
          <div className="case-table">
            {visible.length ? (
              <>
                <div className="case-table-head">
                  <span>Case / sender</span>
                  <span>Workflow</span>
                  <span>Machine / operational</span>
                  <span>Review / updated</span>
                </div>
                {visible.map((c) => (
                  <CaseRow c={c} key={c.case_id} />
                ))}
              </>
            ) : (
              <Empty />
            )}
          </div>
        </Panel>
      )}
      <p className="muted footnote">
        “Process sample email” uses the approved clean-match fixture. An
        existing case opens its current run; use Replay on its detail page to
        start a new run.
      </p>
    </>
  );
}
function CaseRow({ c }: { c: CaseSummary }) {
  return (
    <article className="case-row">
      <div>
        <Link to={`/cases/${c.case_id}`} className="case-title">
          {c.subject}
          <ArrowRight size={15} aria-hidden="true" />
        </Link>
        <small>{c.from}</small>
        <div className="case-meta">
          <span>{c.category ? human(c.category) : "Classifying"}</span>
          <span>{c.mismatch_count} mismatches</span>
        </div>
      </div>
      <div>
        <Badge value={c.workflow_status} />
      </div>
      <div className="dual-status">
        <span>
          <small>Machine</small>
          <Badge value={c.machine_status} />
        </span>
        <span>
          <small>Operational</small>
          <Badge value={c.final_status} />
        </span>
      </div>
      <div>
        <span className={c.has_open_review ? "review-open" : "muted"}>
          {c.has_open_review ? "● Open review" : "No open review"}
        </span>
        <small>Last updated: {date(c.updated_at)}</small>
      </div>
    </article>
  );
}
function Detail({
  id,
  refresh,
  retry,
}: {
  id: string;
  refresh: number;
  retry: () => void;
}) {
  const [pending, setPending] = useState(false),
    [mutationError, setMutationError] = useState<Error>(),
    [localRefresh, setLocalRefresh] = useState(0);
  const {
    data: c,
    error,
    loading,
    replace,
  } = usePoll(`detail:${id}:${refresh}:${localRefresh}`, (signal) =>
    api.detail(id, signal),
  );
  async function replay() {
    setPending(true);
    setMutationError(undefined);
    try {
      await api.reprocess(id);
    } catch (e) {
      setMutationError(
        new Error(
          `${(e as Error).message} Refetching to determine the current run; replay was not retried.`,
        ),
      );
    } finally {
      setLocalRefresh((v) => v + 1);
      setPending(false);
    }
  }
  return (
    <>
      <Link className="back-link" to="/cases">
        ← All cases
      </Link>
      {error && <ErrorState error={error} retry={retry} stale={!!c} />}{" "}
      {loading && <Loading />}
      {mutationError && <ErrorState error={mutationError} retry={retry} />}
      {c && (
        <>
          <div className="page-heading detail-heading">
            <div>
              <div className="eyebrow">
                {isSimulation ? "SYNTHETIC FIXTURE" : "CASE DETAIL"}{" "}
                <span className="mono">/ {c.case_id}</span>
              </div>
              <h1>{c.email.subject}</h1>
              <p>
                {c.email.from} <span className="separator">·</span>{" "}
                {c.email.received_at !== null &&
                  (isSimulation
                    ? "Fictional fixture receipt time: "
                    : "Received ")}
                {date(c.email.received_at)}
              </p>
              <p>
                Case created: {date(c.created_at)} · Last updated:{" "}
                {date(c.updated_at)}
              </p>
            </div>
            <button onClick={() => void replay()} disabled={pending}>
              <RefreshCw size={16} aria-hidden="true" />
              {pending ? "Starting run…" : "Replay / Reprocess"}
            </button>
          </div>
          <div className="run-strip">
            <Badge value={c.workflow_status} />
            <span>
              {c.email.category ? human(c.email.category) : "Classifying"}
            </span>
            <span className="mono">Run: {c.run.run_id}</span>
            {c.completed_at && <span>Completed {date(c.completed_at)}</span>}
          </div>
          {isSimulation && <SyntheticEmailContext c={c} />}
          {c.failure && (
            <div className="notice error" role="alert">
              <TriangleAlert size={22} aria-hidden="true" />
              <div>
                <strong>Processing failed · {c.failure.step}</strong>
                <p>
                  {c.failure.message} Attempts: {c.failure.attempts}.
                </p>
                {c.history.some(
                  (h) =>
                    h.type === "DECISION_RECEIVED" && h.run_id === c.run.run_id,
                ) && (
                  <p>
                    <strong>Accepted decision retained.</strong> Operator
                    recovery is required; do not re-enter it.
                  </p>
                )}
              </div>
            </div>
          )}
          {c.workflow_status === "PROCESSING" && (
            <div className="notice simulation">
              <Clock3 size={22} aria-hidden="true" />
              <div>
                <strong>
                  {c.review?.close_reason === "DECISION_ACCEPTED"
                    ? "Decision accepted; processing continues."
                    : "Synthetic processing in progress."}
                </strong>
                <p>
                  {c.machine_assessment
                    ? "Last result; updating. The accepted action has not finished processing."
                    : "Classification and assessment are not available yet."}{" "}
                  {isSimulation
                    ? "Seeded examples advance via Demo controls; decisions and replays update automatically."
                    : ""}
                </p>
              </div>
            </div>
          )}
          <div className="assessment-grid">
            <section className="assessment">
              <div className="eyebrow">FROZEN PER RUN</div>
              <h2>Automated assessment</h2>
              <Badge value={c.machine_assessment?.status ?? null} />
              <p>
                {c.machine_assessment
                  ? `Reason: ${c.machine_assessment.review_reason ? human(c.machine_assessment.review_reason) : "No uncertainty"}. Defects: ${c.machine_assessment.defect_fields.map((f) => fieldTitles[f]).join(", ") || "None"}.`
                  : "Not assessed. Unknown does not mean OK."}
              </p>
              <small>
                The original machine result remains unchanged by human input.
              </small>
            </section>
            <section className="assessment operational">
              <div className="eyebrow">
                {c.workflow_status === "PROCESSING"
                  ? "LAST RESULT · UPDATING"
                  : "LATEST APPLIED RESULT"}
              </div>
              <h2>Current operational outcome</h2>
              <Badge value={effectiveStatus(c)} />
              <p>
                {c.follow_up === "NONE"
                  ? "No external follow-up recorded."
                  : human(c.follow_up) + "."}{" "}
                {c.resolution
                  ? `Latest action: ${human(c.resolution.action)}.`
                  : "No human resolution applied."}
              </p>
              <small>Always read alongside the workflow status above.</small>
            </section>
          </div>
          {c.review && (
            <ReviewPanel c={c} onCase={replace} onBusy={setPending} />
          )}{" "}
          {c.follow_up === "CORRECTION_REQUIRED" && (
            <div className="notice warning">
              <TriangleAlert size={21} aria-hidden="true" />
              <div>
                <strong>External correction required</strong>
                <p>
                  A dependable discrepancy remains. Obtain corrected documents;
                  this is not an approval review.
                </p>
              </div>
            </div>
          )}
          <Panel
            title="Document comparison"
            subtitle={
              c.fields.length
                ? "SI is the reference · BL is the draft · expand evidence to verify a value."
                : c.email.category && c.email.category !== "BL_COMPARISON"
                  ? "Not applicable to this email category."
                  : "Comparison fields are not available yet."
            }
            action={
              <span className="subtle-chip">
                {c.fields.length} /{" "}
                {c.email.category === "BL_COMPARISON" ? 7 : 0} fields
              </span>
            }
          >
            {c.fields.length ? (
              <div className="comparison-table">
                <div className="comparison-head">
                  <span>Canonical field</span>
                  <span>Shipping instruction · SI</span>
                  <span>Draft bill of lading · BL</span>
                  <span>Comparison</span>
                </div>
                {c.fields.map((f) => (
                  <article className="comparison-row" key={f.field}>
                    <h3>{fieldTitles[f.field]}</h3>
                    <Value value={f.si} side="SI" />
                    <Value value={f.bl} side="BL" />
                    <div>
                      <Badge value={f.result} />
                      {f.not_comparable_cause && (
                        <small>{human(f.not_comparable_cause)}</small>
                      )}
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <Empty
                title={
                  c.email.category && c.email.category !== "BL_COMPARISON"
                    ? "No comparison required"
                    : "Waiting for comparison data"
                }
              >
                No placeholder values or verdicts are invented.
              </Empty>
            )}
          </Panel>
          <div className="detail-bottom">
            <Panel
              title="Original documents"
              subtitle="Authorized synthetic source files."
            >
              {c.documents.length ? (
                <div className="document-list">
                  {c.documents.map((d) => (
                    <div className="document-item" key={d.document_id}>
                      <FileText size={24} aria-hidden="true" />
                      <div>
                        <a
                          target="_blank"
                          rel="noreferrer"
                          href={api.documentUrl(d.document_id)}
                        >
                          {d.filename} ↗
                        </a>
                        <small>
                          {d.role} · {d.media_type} ·{" "}
                          {d.size_bytes ?? "Unknown"} bytes ·{" "}
                          {human(d.parse_status)}
                        </small>
                        <details>
                          <summary>Source integrity</summary>
                          <code className="hash">
                            SHA-256: {d.content_hash}
                          </code>
                        </details>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <Empty title="No documents available">
                  The case may still be processing or waiting for an external
                  source.
                </Empty>
              )}
            </Panel>
            <Panel
              title="Activity history"
              subtitle="Stored events, including earlier runs."
            >
              <ol className="timeline">
                {c.history.map((h) => (
                  <li key={h.event_id}>
                    <span className="timeline-dot" />
                    <strong>{human(h.type)}</strong>
                    <p>{h.summary}</p>
                    <small>
                      {date(h.at)} · {h.actor.kind} ·{" "}
                      <span className="mono">{h.run_id}</span>
                    </small>
                    {h.details && (
                      <details>
                        <summary>Event context</summary>
                        <pre>{JSON.stringify(h.details, null, 2)}</pre>
                      </details>
                    )}
                  </li>
                ))}
              </ol>
            </Panel>
          </div>
        </>
      )}
    </>
  );
}
function SyntheticEmailContext({ c }: { c: Case }) {
  const context = [...c.history]
    .reverse()
    .find((h) => h.run_id === c.run.run_id && h.details?.source_email)?.details;
  const source = participantEmailSchema.safeParse(context?.source_email);
  return (
    <Panel
      title="Synthetic email context"
      subtitle="Participant-shaped correspondence, independently authored for this demo."
    >
      <div className="email-context">
        <p>
          <strong>Participant receipt time is unavailable.</strong> Contract
          v2.1.1 preserves absent receipt time as null without blocking intake.
          Any known receipt time in this demo is explicitly fictional. Case
          creation and update times describe system activity, never email
          receipt.
        </p>
        {context?.intent_mapping === "UNRESOLVED" && (
          <div className="notice warning">
            <TriangleAlert aria-hidden="true" size={20} />
            <div>
              <strong>No-attachment intent remains unresolved</strong>
              <p>
                The current contract baseline keeps comparison blocked. A
                future-draft request is not treated as a completed comparison or
                a new category.
              </p>
            </div>
          </div>
        )}
        {source.success && (
          <>
            <details>
              <summary>Read synthetic email body</summary>
              <pre tabIndex={0} aria-label="Synthetic email body">
                {source.data.body}
              </pre>
            </details>
            <details>
              <summary>Inspect participant-shaped source record</summary>
              <pre tabIndex={0} aria-label="Synthetic source record">
                {JSON.stringify(source.data, null, 2)}
              </pre>
            </details>
            <small>
              Source record: email_id, from, subject, body, attachments. No
              received_at field.
            </small>
          </>
        )}
      </div>
    </Panel>
  );
}
function Value({ value: v, side }: { value: FieldValue | null; side: string }) {
  return (
    <div className="field-value">
      <span className="mobile-side">{side}</span>
      <strong>{v?.raw ?? "Unknown"}</strong>
      {v?.normalized != null && (
        <small>Canonical: {String(v.normalized)}</small>
      )}
      {v && (
        <>
          <span
            className={`provenance ${v.value_origin === "MANUAL_OVERRIDE" ? "override" : ""}`}
          >
            {human(v.value_origin)} · {v.grounded ? "Grounded" : "Ungrounded"}
          </span>
          {v.flags.map((flag) => (
            <small key={flag}>{flag}</small>
          ))}
          {v.evidence.length > 0 ? (
            <details>
              <summary>View evidence ({v.evidence.length})</summary>
              {v.evidence.map((e, i) => (
                <div className="evidence" key={i}>
                  <blockquote>{e.source_text}</blockquote>
                  <small>
                    {e.locator.kind === "text_range"
                      ? `Text code points ${e.locator.start}–${e.locator.end} (end exclusive)`
                      : JSON.stringify(e.locator)}
                  </small>
                  <a
                    href={api.documentUrl(e.document_id)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open source ↗
                  </a>
                </div>
              ))}
            </details>
          ) : (
            <small>No supporting document evidence</small>
          )}
          {v.override_confirmations.length > 0 && (
            <details>
              <summary>Override confirmation lineage</summary>
              <pre>{JSON.stringify(v.override_confirmations, null, 2)}</pre>
            </details>
          )}
        </>
      )}
    </div>
  );
}
function ReviewPanel({
  c,
  onCase,
  onBusy,
}: {
  c: Case;
  onCase: (c: Case) => void;
  onBusy: (busy: boolean) => void;
}) {
  const r = c.review!;
  return (
    <section
      className={`review-panel ${r.status === "CLOSED" ? "closed" : ""}`}
    >
      <div className="review-heading">
        <CircleHelp size={24} aria-hidden="true" />
        <div>
          <div className="eyebrow">
            {r.status} REVIEW · {r.ui_mode.replaceAll("_", " ")}
          </div>
          <h2>{r.question}</h2>
        </div>
        <Badge value={r.status} />
      </div>
      <p>{r.context_summary}</p>
      <p className="review-target">
        {r.scope === "FIELD"
          ? `Target: ${r.side} · ${fieldTitles[r.field!]}`
          : r.target_role
            ? `Target document role: ${r.target_role}`
            : "External source needed"}{" "}
        <span className="mono">· {r.review_id}</span>
      </p>
      <ReviewActions
        key={`${r.run_id}:${r.review_id}`}
        c={c}
        onCase={onCase}
        onBusy={onBusy}
        renderValue={(v, side) => <Value value={v} side={side} />}
      />
      {r.source_documents.length > 0 && (
        <div className="review-sources">
          Review sources:{" "}
          {r.source_documents.map((d) => (
            <a
              href={api.documentUrl(d.document_id)}
              target="_blank"
              rel="noreferrer"
              key={d.document_id}
            >
              {d.filename} ↗
            </a>
          ))}
        </div>
      )}
    </section>
  );
}
