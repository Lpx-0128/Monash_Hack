import {
  workHint,
  compareWork,
  type WorkHint,
} from "../shared/presentation-priority";
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
import {
  detailCopy,
  errorCopy,
  fieldName,
  mismatchSummary,
  outcomeCopy,
  reviewCopy,
} from "./copy";
import { ReviewApi, RemoteError } from "./api";
import {
  interpretationInput,
  interpretationGuard,
  interpretedDecision,
  deterministicValue,
  type Interpreter,
} from "./interpretation";

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
  edit?(
    chat: string,
    message: string,
    buttons: Button[][],
    text?: string,
  ): Promise<void>;
  send(chat: string, text: string, buttons?: Button[][]): Promise<string>;
  document(
    chat: string,
    file: { filename: string; data: string },
  ): Promise<string>;
}
type Binding = Recipient & { caseId: string; review: string; run: string };
type Proposal = Binding & {
  interpretation_source?: "deterministic" | "Copilot interpretation";
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
  cleanedButtons?: Record<string, { attempts: number; done: boolean }>;
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
// Structural typing does not strip delivery metadata from a Binding at runtime.
const cleanBinding = (b: Binding): Binding => ({
  actor: b.actor,
  chat: b.chat,
  caseId: b.caseId,
  review: b.review,
  run: b.run,
});
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
    private interpret?: Interpreter,
  ) {
    this.state = existsSync(file)
      ? JSON.parse(readFileSync(file, "utf8"))
      : initial();
    if (this.state.version !== 1)
      throw new Error("Unsupported interaction state");
    // Recover outcomes poisoned by a review's message ID in older state files.
    for (const p of Object.values(this.state.proposals)) {
      const legacy = p as Proposal & { message?: string };
      if (!legacy.message) continue;
      const key = `${p.run}/outcome/${p.review}/${recipientKey(p)}`;
      const d = this.state.deliveries[key];
      if (d?.message === legacy.message && d.attempts === 0) {
        delete d.message;
        delete d.held;
      }
    }
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
      actor: r.actor,
      chat: r.chat,
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
    this.state.buttons[id] = {
      binding: cleanBinding(b),
      action,
      proposal,
      option,
    };
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
  async cleanButtons() {
    if (!this.transport.edit) return;
    const groups = new Map<
      string,
      { b: Binding; message: string; text?: string }
    >();
    for (const button of Object.values(this.state.buttons)) {
      if (
        !button.message ||
        ["details", "dashboard", "show"].includes(button.action)
      )
        continue;
      const p = button.proposal
        ? this.state.proposals[button.proposal]
        : undefined;
      const done = Object.values(this.state.proposals).some(
        (p) =>
          p.phase === "done" &&
          p.actor === button.binding.actor &&
          p.chat === button.binding.chat &&
          p.run === button.binding.run &&
          p.review === button.binding.review,
      );
      if (!done && (!p || !["done", "cancelled"].includes(p.phase))) continue;
      const key = `${button.binding.chat}/${button.message}`;
      groups.set(key, {
        b: button.binding,
        message: button.message,
        text: p
          ? p.phase === "done"
            ? "Submitted — response accepted. Processing may still be underway; check the current result below."
            : "This proposal is closed — cancelled, replaced or rejected. Use the latest review or confirmation to continue."
          : undefined,
      });
    }
    let edits = 0;
    for (const [key, target] of groups) {
      const state = ((this.state.cleanedButtons ??= {})[key] ??= {
        attempts: 0,
        done: false,
      });
      if (state.done || state.attempts >= 5) continue;
      if (++edits > 3) break;
      const buttons = Object.entries(this.state.buttons)
        .filter(
          ([, b]) =>
            b.binding.chat === target.b.chat &&
            b.message === target.message &&
            ["details", "dashboard"].includes(b.action),
        )
        .map(([id, b]) => ({
          text: b.action === "details" ? "View details" : "Open dashboard",
          callback_data: "ship:" + id,
        }));
      try {
        await this.transport.edit(
          target.b.chat,
          target.message,
          buttons.length ? [buttons] : [],
          target.text,
        );
        state.done = true;
      } catch {
        state.attempts++;
        // Cosmetic retries never replay a decision. Deleted messages eventually stop retrying.
      }
      this.save();
    }
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
    source: "deterministic" | "Copilot interpretation" = "deterministic",
  ) {
    this.invalidate(b);
    const id = token();
    this.state.proposals[id] = {
      ...cleanBinding(b),
      decision: d,
      interpretation_source: source,
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
        : typeof value === "object"
          ? value?.label
          : value;
    const description =
      d.action === "ACKNOWLEDGE"
        ? "Acknowledge external action; this does not complete verification."
        : d.action === "SELECT_OPTION"
          ? `${r.target_role ? `Assign ${r.target_role} document` : `${r.side} ${fieldName(r.field)}`}: ${String(proposed)}${r.field === "gross_weight_kg" ? " kg" : ""}`
          : `${r.side} ${fieldName(r.field)}: ${String(proposed)}${r.field === "gross_weight_kg" ? " kg" : ""}`;
    await this.sendButtons(
      b,
      `${phase === "override" ? "I couldn’t verify this value in the source.\nUse it anyway as your own unverified value?" : "Does this look right?"}\n${description}\n\n${c.email.subject}\n${source === "deterministic" ? "I read your value using the input rules." : "Copilot interpreted your reply—please check it carefully."}\nNo decision submitted. Confirm below, or Cancel and reply to the original review with a different answer.\n\nSynthetic practice case`,
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
        [
          this.button(b, "View details", "details"),
          this.button(b, "Open dashboard", "dashboard"),
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
        "Thanks—your response was accepted (202).\nProcessing continues; this is not completion yet. I’ll send the result when it’s ready.\n" +
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
        errorCopy(e instanceof RemoteError ? e.code : "UNAVAILABLE"),
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
        ? "I checked: a decision is already saved for this review. Please don’t enter it again; I’ll report the processing result."
        : "The connection dropped, and I couldn’t confirm an accepted decision. I haven’t retried it. Send /reviews to check the latest state before answering again.",
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
            "You’re on pause—no new proactive notifications. Existing review buttons still work. Send /reviews when you’re ready to continue.",
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
            "Let’s review your practice cases. I’ll show a queue—pick one to see what needs your attention.\n\nNew notifications are on. Send /pause any time to quiet them.",
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
          if (btn.action === "details" || btn.action === "dashboard") {
            const c = await this.apiFor(b.actor).get(b.caseId);
            if (
              c.run.run_id !== b.run ||
              (btn.action === "details" &&
                b.review &&
                c.review?.review_id !== b.review)
            )
              throw new RemoteError(409, "STALE_RUN");
            if (btn.action === "dashboard") {
              const url = new URL(this.link(b));
              const local = ["localhost", "127.0.0.1", "[::1]"].includes(
                url.hostname,
              );
              await this.tell(
                b,
                local
                  ? `Open this on the laptop running the demo:\n${url}\n\nIf Telegram doesn’t make it clickable, copy it into the browser’s address bar. Keep the demo running. This local address won’t open the laptop’s dashboard on your phone.`
                  : `Open your case in the dashboard:\n${url}`,
              );
            } else {
              // Split long evidence without discarding a field or safety context.
              const text = detailCopy(c);
              for (let offset = 0; offset < text.length; offset += 3500)
                await this.tell(b, text.slice(offset, offset + 3500));
            }
            return;
          }
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
                "Cancelled—nothing submitted. Reply to the original review with a new answer when you’re ready.",
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
            ...cleanBinding(b),
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
            "Which case is this for? Use Telegram’s Reply on the review you want to answer. Send /reviews if you need to find it. Nothing submitted.",
          );
          return;
        }
        const c = await this.current(b),
          r = c.review!;
        this.invalidate(b);
        const text = u.text ?? "";
        const guard = interpretationGuard(c, text);
        if (guard) {
          await this.tell(b, guard);
          return;
        }
        let value: string | number | undefined;
        if (r.ui_mode === "VALUE_INPUT" && r.field && r.side) {
          try {
            value = deterministicValue(c, text);
          } catch {
            /* Consider bounded interpretation below. */
          }
        }
        if (value === undefined) {
          if (!this.interpret) {
            await this.tell(
              b,
              "I can’t interpret a sentence right now. Reply with just the value in the requested format, or use the review’s buttons.",
            );
            return;
          }
          await this.tell(
            b,
            "Let me check what you mean with Copilot. I’ll show a preview for you to confirm before submitting anything.",
          );
          try {
            const raw = await this.interpret(interpretationInput(c, text));
            const fresh = await this.current(b);
            const decision = interpretedDecision(fresh, b.actor, text, raw);
            if (!decision) {
              await this.tell(
                b,
                "I’m not sure which answer you mean. Could you reply with one exact value or choose an option? No decision submitted.",
              );
              return;
            }
            await this.proposal(
              b,
              decision,
              "preview",
              "Copilot interpretation",
            );
          } catch (e) {
            if (e instanceof RemoteError) throw e;
            await this.tell(
              b,
              "I couldn’t reliably interpret that reply. No decision submitted. Try just the value in the requested format, or use the review’s buttons.",
            );
          }
          return;
        }
        await this.proposal(b, {
          review_id: b.review,
          run_id: b.run,
          actor_id: b.actor,
          channel: "TELEGRAM",
          action: "PROVIDE_VALUE",
          field: r.field!,
          side: r.side!,
          value,
          user_message: u.text,
        });
      } catch (e) {
        await this.tell(
          recipient,
          e instanceof RemoteError
            ? errorCopy(e.code)
            : "Something interrupted this request. I haven’t automatically retried your decision. Check the current case through /reviews before trying again; if this continues, ask the operator to check the service.",
        );
      } finally {
        await this.cleanButtons();
      }
    });
  }
  async deliver(d: Delivery, c: Case) {
    const api = this.apiFor(d.actor);
    if (!d.message) {
      const b = cleanBinding(d),
        r = c.review;
      let text = "",
        buttons: Button[][] = [];
      if (d.type === "review" && r) {
        text = reviewCopy(c);
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
      } else if (d.type === "mismatch")
        text = `The check is finished, but corrections are still needed.\n${c.email.subject}\n\n${mismatchSummary(c)}\nPlease arrange a corrected document.\n\nSynthetic practice case · checks are simulated`;
      else if (d.type === "failure")
        text = `Processing stopped—operator help needed.\n${c.email.subject}\n\nAny accepted response is saved. Please inspect the failure in the dashboard before retrying.\n\nSynthetic practice case · checks are simulated`;
      else text = outcomeCopy(c);
      buttons.push([
        this.button(b, "View details", "details"),
        this.button(b, "Open dashboard", "dashboard"),
      ]);
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
              "I couldn’t attach the source document. I’ll retry delivery; meanwhile you can inspect it in the dashboard. Don’t guess a value without checking the source.\n" +
                this.link(d),
            );
        }
      }
    }
  }
  tick() {
    return this.exclusive(async () => {
      await this.cleanButtons();
      for (const p of Object.values(this.state.proposals))
        if (["sending", "uncertain"].includes(p.phase)) await this.reconcile(p);
      for (const recipient of this.recipients) {
        if (!this.state.recipients.includes(recipientKey(recipient))) continue;
        const api = this.apiFor(recipient.actor),
          summaries = await api.list();
        const hints: Record<string, WorkHint> = {};
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
          hints[s.case_id] = workHint(s, c);
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
              ...cleanBinding(p),
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
            const choices = [...(requested ? active : backlog)].sort((a, b) =>
              compareWork(
                summaries.find((s) => s.case_id === a.caseId)!,
                summaries.find((s) => s.case_id === b.caseId)!,
                hints,
                "quick",
              ),
            );
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
                `${choices.length} practice cases are queued.\nQuick reviews are listed first; investigation and external follow-up come later. This is guidance, not a guarantee of completion.\nPick one below; I won’t send the whole backlog.\n\nSend /pause to stop new notifications.`,
                choices.map((d) => [
                  this.button(
                    d,
                    `${hints[d.caseId]?.label ?? "Needs investigation"} · ${summaries.find((s) => s.case_id === d.caseId)?.subject ?? d.caseId}`.slice(
                      0,
                      80,
                    ),
                    "show",
                    undefined,
                    d.key,
                  ),
                ]),
              );
            else
              await this.tell(
                recipient,
                "You’re all caught up—no current case notices.\n" +
                  this.dashboard +
                  "/cases",
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
