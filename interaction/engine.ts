import { randomBytes } from "node:crypto";
import {
  existsSync,
  readFileSync,
  writeFileSync,
  renameSync,
  mkdirSync,
} from "node:fs";
import { dirname } from "node:path";
import type { Case, DecisionRequest } from "../shared/types";
import { parseProposal } from "../shared/decisions";
import { effectiveStatus } from "../shared/validation";
import { ReviewApi, RemoteError } from "./api";

export type Recipient = { actor: string; chat: string; operator?: boolean };
export type Incoming = {
  id: string;
  actor: string;
  chat: string;
  message: string;
  reply?: string;
  text?: string;
  callback?: string;
};
export type Button = { text: string; callback_data: string };
export interface Transport {
  send(chat: string, text: string, buttons?: Button[][]): Promise<string>;
  document(
    chat: string,
    file: { filename: string; data: string },
  ): Promise<string>;
}
type Binding = Recipient & { caseId: string; review: string; run: string };
type Proposal = Binding & {
  decision: DecisionRequest;
  phase:
    "preview" | "override" | "sending" | "done" | "cancelled" | "uncertain";
  confirmation?: Incoming;
  updated: number;
};
type Delivery = Binding & {
  held?: boolean;
  key: string;
  type: "review" | "mismatch" | "failure" | "outcome";
  message?: string;
  marked?: boolean;
  attempts: number;
  due: number;
  documents: Record<string, string>;
  documentAttempts: number;
  documentDue: number;
};
type State = {
  digestRequested?: string[];
  version: 1;
  mappings: Record<string, Binding>;
  buttons: Record<
    string,
    {
      binding: Binding;
      action: string;
      proposal?: string;
      option?: string;
      message?: string;
    }
  >;
  proposals: Record<string, Proposal>;
  processed: Record<string, boolean>;
  recipients: string[];
  deliveries: Record<string, Delivery>;
  last: Record<string, number>;
  digests: Record<string, { at: number; signature: string }>;
};
const token = () => randomBytes(16).toString("hex");
const recipientKey = (r: Recipient) => `${r.actor}/${r.chat}`;
const initial = (): State => ({
  version: 1,
  mappings: {},
  buttons: {},
  proposals: {},
  processed: {},
  recipients: [],
  deliveries: {},
  last: {},
  digests: {},
});

/** Single serialized application owner. This is routing/delivery state, never shipping truth. */
export class ReviewEngine {
  state: State;
  private tail: Promise<unknown> = Promise.resolve();
  constructor(
    private file: string,
    public recipients: Recipient[],
    private apiFor: (actor: string) => ReviewApi,
    public transport: Transport,
    private dashboard: string,
    private now = Date.now,
  ) {
    this.state = existsSync(file)
      ? JSON.parse(readFileSync(file, "utf8"))
      : initial();
    if (this.state.version !== 1)
      throw new Error("Unsupported interaction state");
  }
  save() {
    mkdirSync(dirname(this.file), { recursive: true });
    writeFileSync(this.file + ".tmp", JSON.stringify(this.state), {
      mode: 0o600,
    });
    renameSync(this.file + ".tmp", this.file);
  }
  exclusive<T>(fn: () => Promise<T>): Promise<T> {
    const job = this.tail.then(fn);
    this.tail = job.catch(() => {});
    return job;
  }
  link(b: Binding) {
    return `${this.dashboard}/cases/${encodeURIComponent(b.caseId)}`;
  }
  async tell(r: Recipient, text: string, buttons?: Button[][]) {
    return this.transport.send(r.chat, text, buttons);
  }
  binding(c: Case, r: Recipient): Binding {
    return {
      ...r,
      caseId: c.case_id,
      run: c.run.run_id,
      review: c.review?.review_id ?? "",
    };
  }
  async current(b: Binding) {
    const c = await this.apiFor(b.actor).get(b.caseId);
    if (
      c.run.run_id !== b.run ||
      c.review?.review_id !== b.review ||
      c.review.status !== "OPEN"
    )
      throw new RemoteError(409, "REVIEW_ALREADY_CLOSED");
    return c;
  }
  button(
    b: Binding,
    text: string,
    action: string,
    proposal?: string,
    option?: string,
  ): Button {
    const id = token();
    this.state.buttons[id] = { binding: b, action, proposal, option };
    return { text, callback_data: "ship:" + id };
  }
  async sendButtons(b: Binding, text: string, buttons: Button[][]) {
    this.save();
    const message = await this.tell(b, text, buttons);
    for (const row of buttons)
      for (const x of row)
        this.state.buttons[x.callback_data.slice(5)].message = message;
    this.save();
    return message;
  }
  invalidate(b: Binding) {
    for (const p of Object.values(this.state.proposals))
      if (
        p.actor === b.actor &&
        p.chat === b.chat &&
        p.review === b.review &&
        p.run === b.run &&
        ["preview", "override"].includes(p.phase)
      )
        p.phase = "cancelled";
    this.save();
  }
  async proposal(
    b: Binding,
    d: DecisionRequest,
    phase: "preview" | "override" = "preview",
  ) {
    this.invalidate(b);
    const id = token();
    this.state.proposals[id] = {
      ...b,
      decision: d,
      phase,
      updated: this.now(),
    };
    const c = await this.current(b),
      r = c.review!;
    const value =
      d.action === "PROVIDE_VALUE"
        ? d.value
        : d.action === "SELECT_OPTION"
          ? r.options?.find((o) => o.option_id === d.option_id)
          : "";
    const proposed =
      typeof value === "object" && value?.kind === "VALUE"
        ? value.value.normalized
        : value;
    await this.sendButtons(
      b,
      `${phase === "override" ? "This value cannot be verified from the source. Confirm an ungrounded manual override?" : "Confirm canonical value"}\n${r.side} ${r.field}: ${String(proposed)}${r.field === "gross_weight_kg" ? " kg" : ""}\nCase ${b.caseId}\nReview ${b.review}\nRun ${b.run}\n${this.link(b)}`,
      [
        [
          this.button(
            b,
            phase === "override" ? "Confirm exact override" : "Confirm value",
            "confirm",
            id,
          ),
          this.button(b, "Cancel", "cancel", id),
        ],
      ],
    );
  }
  async submit(p: Proposal, u: Incoming) {
    const api = this.apiFor(p.actor),
      c = await this.current(p),
      r = c.review!;
    if (p.phase === "override") {
      const d = p.decision;
      const v =
        d.action === "PROVIDE_VALUE"
          ? d.value
          : d.action === "SELECT_OPTION"
            ? r.options?.find((o) => o.option_id === d.option_id)
            : null;
      const proposed =
        typeof v === "object" && v?.kind === "VALUE" ? v.value.normalized : v;
      if (
        !r.field ||
        !r.side ||
        (typeof proposed !== "string" && typeof proposed !== "number") ||
        d.action === "ACKNOWLEDGE"
      )
        throw new Error("Invalid override target");
      d.override_confirmation = {
        review_id: p.review,
        run_id: p.run,
        field: r.field,
        side: r.side,
        proposed_value: proposed,
        confirmed: true,
      };
    }
    // Persist actual authenticated human action BEFORE the API call. A restart never retries it.
    p.confirmation = u;
    p.phase = "sending";
    this.save();
    try {
      await api.decide(p.decision);
      p.phase = "done";
      this.save();
      await this.tell(
        p,
        "Decision accepted (202); processing continues. This is not completion.\n" +
          this.link(p),
      );
    } catch (e) {
      if (
        e instanceof RemoteError &&
        [
          "VALUE_NOT_FOUND_IN_DOCUMENT",
          "OVERRIDE_CONFIRMATION_REQUIRED",
        ].includes(e.code)
      ) {
        p.phase = "cancelled";
        this.save();
        await this.proposal(p, p.decision, "override");
        return;
      }
      p.phase =
        e instanceof RemoteError && e.status < 500 ? "cancelled" : "uncertain";
      this.save();
      if (p.phase === "uncertain") {
        await this.reconcile(p);
        return;
      }
      await this.tell(
        p,
        `${e instanceof RemoteError ? e.code : "Request unavailable"}. Review was not resubmitted.\n${this.link(p)}`,
      );
    }
  }
  async reconcile(p: Proposal) {
    const c = await this.apiFor(p.actor).get(p.caseId);
    const accepted = c.history.some(
      (h) =>
        h.type === "DECISION_RECEIVED" &&
        (h.details?.decision as DecisionRequest | undefined)?.review_id ===
          p.review,
    );
    p.phase = accepted ? "done" : "cancelled";
    this.save();
    await this.tell(
      p,
      accepted
        ? "Backend records a decision for this review. Processing/result will be reported; do not re-enter it."
        : `Response uncertain. Current state: ${c.workflow_status}. No automatic retry. Reply to an active review to create a new proposal.\n${this.link(p)}`,
    );
  }
  inbound(u: Incoming) {
    return this.exclusive(async () => {
      const recipient = this.recipients.find(
        (r) => r.actor === u.actor && r.chat === u.chat,
      );
      if (!recipient) return; // No case disclosure or outbound contact to undesignated chats.
      if (this.state.processed[u.id]) return;
      this.state.processed[u.id] = true;
      this.save();
      try {
        if (u.text === "/pause") {
          this.state.recipients = this.state.recipients.filter(
            (k) => k !== recipientKey(recipient),
          );
          this.save();
          await this.tell(
            recipient,
            "Proactive notifications paused. Existing review buttons still work. Use /reviews to resume with a selectable digest.",
          );
          return;
        }
        if (u.text === "/start" || u.text === "/reviews") {
          if (!this.state.recipients.includes(recipientKey(recipient)))
            this.state.recipients.push(recipientKey(recipient));
          this.state.digestRequested ??= [];
          if (!this.state.digestRequested.includes(recipientKey(recipient)))
            this.state.digestRequested.push(recipientKey(recipient));
          this.save();
          await this.tell(
            recipient,
            "Synthetic shipping review enabled. A selectable digest will follow. Choose one case to open its review and documents. Reply to that review for value input. /pause stops proactive notifications; /reviews opens the queue. Bare values never choose a review.",
          );
          return;
        }
        if (u.callback) {
          const btn = this.state.buttons[u.callback.replace(/^ship:/, "")];
          if (
            !btn ||
            btn.binding.actor !== u.actor ||
            btn.binding.chat !== u.chat ||
            btn.message !== u.message
          )
            throw new RemoteError(403, "FORBIDDEN");
          const b = btn.binding;
          if (btn.action === "show") {
            const d = this.state.deliveries[btn.option!];
            if (!d) throw new RemoteError(404, "NOT_FOUND");
            const c = await this.apiFor(b.actor).get(b.caseId);
            if (
              c.run.run_id !== b.run ||
              (d.type === "review" &&
                (c.review?.review_id !== b.review ||
                  c.review.status !== "OPEN"))
            )
              throw new RemoteError(409, "STALE_RUN");
            d.held = false;
            d.message = undefined; // Explicit user request may reopen an already delivered review.
            this.save();
            await this.deliver(d, c);
            return;
          }
          await this.current(b);
          if (btn.proposal) {
            const p = this.state.proposals[btn.proposal];
            if (!p || !["preview", "override"].includes(p.phase))
              throw new RemoteError(409, "REVIEW_ALREADY_CLOSED");
            if (btn.action === "cancel") {
              p.phase = "cancelled";
              this.save();
              await this.tell(
                b,
                "Proposal cancelled. Reply with a new value when ready.",
              );
              return;
            }
            await this.submit(p, u);
            return;
          }
          const d: DecisionRequest =
            btn.action === "choose"
              ? {
                  review_id: b.review,
                  run_id: b.run,
                  actor_id: b.actor,
                  channel: "TELEGRAM",
                  action: "SELECT_OPTION",
                  option_id: btn.option!,
                }
              : {
                  review_id: b.review,
                  run_id: b.run,
                  actor_id: b.actor,
                  channel: "TELEGRAM",
                  action: "ACKNOWLEDGE",
                };
          this.invalidate(b);
          const id = token();
          const p: Proposal = {
            ...b,
            decision: d,
            phase: "preview",
            updated: this.now(),
          };
          this.state.proposals[id] = p;
          this.save();
          await this.submit(p, u);
          return;
        }
        const b = u.reply
          ? this.state.mappings[`${u.chat}/${u.reply}`]
          : undefined;
        if (!b || b.actor !== u.actor) {
          await this.tell(
            recipient,
            "Reply to the specific review message. A bare value or generic yes cannot choose a review.",
          );
          return;
        }
        const c = await this.current(b),
          r = c.review!;
        this.invalidate(b);
        if (r.ui_mode !== "VALUE_INPUT" || !r.field || !r.side) {
          await this.tell(b, "Use this review’s action buttons.");
          return;
        }
        const value = parseProposal(r.field, u.text ?? "");
        await this.proposal(b, {
          review_id: b.review,
          run_id: b.run,
          actor_id: b.actor,
          channel: "TELEGRAM",
          action: "PROVIDE_VALUE",
          field: r.field,
          side: r.side,
          value,
          user_message: u.text,
        });
      } catch (e) {
        await this.tell(
          recipient,
          e instanceof RemoteError
            ? `${e.code}: review handled, replaced, or unavailable. Use the dashboard/current review.`
            : e instanceof Error && !(e instanceof TypeError)
              ? e.message
              : "Connection unavailable. No automatic decision retry.",
        );
      }
    });
  }
  async deliver(d: Delivery, c: Case) {
    const api = this.apiFor(d.actor);
    if (!d.message) {
      const b = d,
        r = c.review;
      let text = "",
        buttons: Button[][] = [];
      if (d.type === "review" && r) {
        text = `SYNTHETIC — simulated grounding\n${c.email.subject}\n${r.question}\n${r.context_summary}\nTarget: ${r.scope === "FIELD" ? `${r.side} ${r.field}${r.field === "gross_weight_kg" ? " (kg; dot decimal, no grouping)" : ""}` : `document role ${r.target_role ?? "external action"}`}\nKnown mismatches: ${
          c.fields
            .filter((f) => f.result === "MISMATCH")
            .map((f) => f.field)
            .join(", ") || "none"
        }\nReply to THIS message for value input.\n${this.link(b)}`;
        if (r.ui_mode === "CHOICE")
          buttons = (r.options ?? []).map((o) => [
            this.button(
              b,
              o.label.slice(0, 80),
              "choose",
              undefined,
              o.option_id,
            ),
          ]);
        else
          buttons = [
            [
              this.button(
                b,
                r.ui_mode === "VALUE_INPUT"
                  ? "I can’t tell — external action needed"
                  : "Acknowledge external action",
                "ack",
              ),
            ],
          ];
        for (const o of r.options ?? [])
          if (o.kind === "VALUE")
            text += `\n${o.label}: ${o.value.evidence.map((e) => e.source_text).join("; ") || "No grounding evidence; override confirmation may be required."}`;
        if (r.field) {
          const f = c.fields.find((f) => f.field === r.field);
          for (const side of ["si", "bl"] as const) {
            const v = f?.[side];
            text += `\n${side.toUpperCase()}: raw ${v?.raw ?? "unknown"}; canonical ${v?.normalized ?? "unknown"}; ${v?.value_origin ?? "unknown"}; ${v?.grounded ? "grounded" : "unverified"}. Evidence: ${v?.evidence.map((e) => e.source_text).join("; ") || "none"}`;
          }
        }
      } else if (d.type === "mismatch")
        text = `SYNTHETIC — correction required. Verification completed with mismatch: ${c.fields
          .filter((f) => f.result === "MISMATCH")
          .map(
            (f) => `${f.field}: SI ${f.si?.normalized}, BL ${f.bl?.normalized}`,
          )
          .join("; ")}\n${this.link(b)}`;
      else if (d.type === "failure")
        text = `SYNTHETIC — operator notice: ${c.failure?.step}, attempts ${c.failure?.attempts}. Accepted input, if any, is retained.\n${this.link(b)}`;
      else
        text = `SYNTHETIC — current workflow ${c.workflow_status}; operational ${effectiveStatus(c)}; frozen machine ${c.machine_assessment?.status ?? "unavailable"}; follow-up ${c.follow_up}. ${c.workflow_status === "BLOCKED_EXTERNAL" ? "External action still required." : ""}\n${this.link(b)}`;
      if (d.type === "outcome" && c.resolution)
        text += `\nHuman action: ${c.resolution.value_source ?? c.resolution.action}${c.resolution.value_source === "MANUAL_OVERRIDE" ? " — human-provided and ungrounded" : ""}.`;
      d.message = await this.sendButtons(b, text.slice(0, 3900), buttons);
      if (d.type === "review")
        this.state.mappings[`${d.chat}/${d.message}`] = b;
      this.state.last[recipientKey(d)] = this.now();
      this.save();
    }
    if (d.type === "review") {
      if (!d.marked) {
        await api.notified(d.review, d.run);
        d.marked = true;
        this.save();
      }
      if (d.documentAttempts < 3 && d.documentDue <= this.now()) {
        try {
          for (const source of c.review?.source_documents ?? [])
            if (!d.documents[source.document_id]) {
              d.documents[source.document_id] = await this.transport.document(
                d.chat,
                await api.document(c, source.document_id),
              );
              this.save();
            }
        } catch {
          d.documentAttempts++;
          d.documentDue =
            this.now() + Math.min(60000, 3000 * 2 ** d.documentAttempts);
          this.save();
          if (d.documentAttempts === 1)
            await this.tell(
              d,
              "Source document delivery failed. Review remains available in the authorized dashboard; delivery will retry.\n" +
                this.link(d),
            );
        }
      }
    }
  }
  tick() {
    return this.exclusive(async () => {
      for (const p of Object.values(this.state.proposals))
        if (["sending", "uncertain"].includes(p.phase)) await this.reconcile(p);
      for (const recipient of this.recipients) {
        if (!this.state.recipients.includes(recipientKey(recipient))) continue;
        const api = this.apiFor(recipient.actor),
          summaries = await api.list();
        for (const s of summaries) {
          const type =
            s.workflow_status === "FAILED"
              ? recipient.operator
                ? "failure"
                : null
              : s.has_open_review
                ? "review"
                : s.workflow_status === "COMPLETED" &&
                    s.final_status === "MISMATCH"
                  ? "mismatch"
                  : null;
          if (!type) continue;
          const c = await api.get(s.case_id),
            b = this.binding(c, recipient);
          const key = `${b.run}/${type === "review" ? b.review : type}/${recipientKey(recipient)}`;
          this.state.deliveries[key] ??= {
            ...b,
            key,
            type,
            attempts: 0,
            due: 0,
            documents: {},
            documentAttempts: 0,
            documentDue: 0,
          };
        }
        for (const p of Object.values(this.state.proposals))
          if (
            p.phase === "done" &&
            p.actor === recipient.actor &&
            p.chat === recipient.chat
          ) {
            const c = await api.get(p.caseId);
            if (c.run.run_id !== p.run || c.workflow_status === "PROCESSING")
              continue;
            const key = `${p.run}/outcome/${p.review}/${recipientKey(p)}`;
            this.state.deliveries[key] ??= {
              ...p,
              key,
              type: "outcome",
              attempts: 0,
              due: 0,
              documents: {},
              documentAttempts: 0,
              documentDue: 0,
            };
          }
        this.save();
        const active = Object.values(this.state.deliveries).filter(
          (d) =>
            d.actor === recipient.actor &&
            d.chat === recipient.chat &&
            d.type !== "outcome" &&
            summaries.some(
              (s) =>
                s.case_id === d.caseId &&
                s.run_id === d.run &&
                (d.type !== "review" || s.has_open_review),
            ),
        );
        const backlog = active.filter(
          (d) =>
            !d.message &&
            !Object.values(this.state.proposals).some(
              (p) =>
                p.phase === "done" && p.caseId === d.caseId && p.run === d.run,
            ),
        );
        const requested = this.state.digestRequested?.includes(
          recipientKey(recipient),
        );
        if (backlog.length > 3 || requested) {
          for (const d of backlog) d.held = true;
          const signature = backlog
            .map((d) => d.key)
            .sort()
            .join("|");
          const prior = this.state.digests[recipientKey(recipient)];
          if (
            requested ||
            !prior ||
            (prior.signature !== signature && this.now() - prior.at >= 60000)
          ) {
            const choices = requested ? active : backlog;
            this.state.digests[recipientKey(recipient)] = {
              at: this.now(),
              signature,
            };
            this.state.digestRequested = this.state.digestRequested?.filter(
              (k) => k !== recipientKey(recipient),
            );
            this.save();
            if (choices.length)
              await this.sendButtons(
                choices[0],
                `${choices.length} synthetic cases queued. Choose ONE case below to open its notice and source documents. The backlog will not be sent automatically. /pause stops proactive notifications.\n${this.dashboard}/cases`,
                choices.map((d) => [
                  this.button(
                    d,
                    `${d.type}: ${d.caseId}`.slice(0, 80),
                    "show",
                    undefined,
                    d.key,
                  ),
                ]),
              );
            else
              await this.tell(
                recipient,
                "No current case notices.\n" + this.dashboard + "/cases",
              );
          }
          this.save();
        }
        const pending = Object.values(this.state.deliveries).filter(
          (d) =>
            d.actor === recipient.actor &&
            d.chat === recipient.chat &&
            !d.held &&
            d.attempts < 5 &&
            d.due <= this.now() &&
            (!d.message || d.type === "review"),
        );
        let burst = 0;
        for (const d of pending) {
          if (!d.message && burst >= 3) continue;
          if (
            !d.message &&
            this.now() - (this.state.last[recipientKey(d)] ?? -Infinity) < 3000
          )
            continue;
          try {
            const c = await api.get(d.caseId);
            if (
              c.run.run_id !== d.run ||
              (d.type === "review" &&
                (c.review?.review_id !== d.review ||
                  c.review.status !== "OPEN"))
            ) {
              d.attempts = 5;
              this.save();
              continue;
            }
            if (!d.message) burst++;
            await this.deliver(d, c);
          } catch (e) {
            if (e instanceof RemoteError && e.status < 500 && e.status !== 429)
              d.attempts = 5;
            else d.attempts++;
            d.due = this.now() + Math.min(60000, 3000 * 2 ** d.attempts);
            this.save();
          }
        }
      }
    });
  }
}
