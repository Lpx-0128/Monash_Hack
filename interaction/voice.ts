import { randomBytes, randomInt, createHash } from "node:crypto";
import {
  existsSync,
  readFileSync,
  writeFileSync,
  renameSync,
  mkdirSync,
} from "node:fs";
import { dirname } from "node:path";
import type { Case, DecisionRequest } from "../shared/types";
import { ReviewApi, RemoteError } from "./api";
import { ReviewEngine, type Incoming } from "./engine";
import { detailCopy, fieldName } from "./copy";
import { effectiveStatus } from "../shared/validation";
import type { VoiceProvider, VoiceReply } from "./voice-provider";
import { providerDiagnostic, type ProviderDiagnostic } from "./voice-provider";

type Binding = { caseId: string; review: string; run: string };
type Phase =
  | "auth"
  | "inbox"
  | "evidence"
  | "choice"
  | "confirm"
  | "override"
  | "submitting"
  | "accepted"
  | "uncertain"
  | "ended";
export type Enrollment = {
  actor: string;
  phone: string;
  optedIn: boolean;
  outboundCaseId?: string;
};
type Session = {
  id: string;
  actor: string;
  call?: string;
  direction: "inbound" | "outbound";
  phase: Phase;
  deadline: number;
  challenge: string;
  authPrompt?: string;
  authenticated: boolean;
  authenticationMethod?: "telegram" | "demo-handset";
  turn: string;
  reply: VoiceReply;
  processed: Record<string, VoiceReply>;
  failures: number;
  inbox: Binding[];
  binding?: Binding;
  proposal?: DecisionRequest;
  proposalExpires?: number;
  confirmedAt?: number;
  outcome?: "accepted" | "uncertain" | "rejected";
  notified?: boolean;
  providerFailure?: {
    stage: "create" | "limit";
    diagnostic: ProviderDiagnostic;
    hangupFailure?: ProviderDiagnostic;
  };
};
type State = {
  version: 1;
  sessions: Record<string, Session>;
  attempts: Record<string, boolean>;
  approvals: Record<string, boolean>;
};
const nonce = () => randomBytes(16).toString("hex");
const digest = (s: string) => createHash("sha256").update(s).digest("hex");
const normalized = (s: string) =>
  s
    .toLowerCase()
    .replace(/,/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/[.!?]+$/, "")
    .trim();
const yes = (s: string) =>
  /^(yes|yes please|confirm|submit|yes submit|yes submit it|yes confirm|yes please submit|yes please submit it|yes that is correct|yes that's correct|yes correct|yeah|yep)$/.test(
    s,
  );
const spokenOptions = ["Alpha", "Bravo", "Charlie"];
const binding = (c: Case): Binding => ({
  caseId: c.case_id,
  review: c.review!.review_id,
  run: c.run.run_id,
});

/** One owner: all operations share ReviewEngine's serialization and Telegram transport.
 * Only current authorized simulator state is used; no shipping truth is stored here.
 */
export class VoiceService {
  state: State;
  constructor(
    private file: string,
    private shared: ReviewEngine,
    private apiFor: (actor: string) => ReviewApi,
    private provider: VoiceProvider,
    private enrolled: Enrollment[],
    private now = Date.now,
    private capSeconds = 90,
    private quiet = { start: 22, end: 8 },
    private skipDemoChallenge = false,
  ) {
    if (skipDemoChallenge && !provider.applicationDeadlineOnly)
      throw new Error(
        "Skipping the challenge requires supervised trial-demo mode",
      );
    if (
      !Number.isInteger(capSeconds) ||
      capSeconds < 30 ||
      capSeconds > (provider.applicationDeadlineOnly ? 600 : 180)
    )
      throw new Error("Invalid voice session duration");
    this.state = existsSync(file)
      ? JSON.parse(readFileSync(file, "utf8"))
      : { version: 1, sessions: {}, attempts: {}, approvals: {} };
    if (this.state.version !== 1) throw new Error("Unsupported voice state");
    // A restarted process never reuses an earlier human confirmation or retries a POST.
    for (const s of Object.values(this.state.sessions)) {
      if (s.phase === "submitting") {
        s.phase = "uncertain";
        s.outcome = "uncertain";
      } else if (!["accepted", "uncertain", "ended"].includes(s.phase)) {
        s.phase = "ended";
        delete s.proposal;
      }
    }
    this.save();
  }
  private save() {
    mkdirSync(dirname(this.file), { recursive: true });
    writeFileSync(this.file + ".tmp", JSON.stringify(this.state), {
      mode: 0o600,
    });
    renameSync(this.file + ".tmp", this.file);
  }
  private recipient(s: Session) {
    const r = this.shared.recipients.find((r) => r.actor === s.actor);
    if (!r) throw new Error("Actor no longer enrolled");
    return r;
  }
  private reply(s: Session, text: string, end = false): VoiceReply {
    s.turn = nonce();
    s.reply = {
      text,
      end,
      turn: s.turn,
      waitSeconds: ["auth", "evidence"].includes(s.phase) ? 20 : 10,
    };
    if (end && !["accepted", "uncertain"].includes(s.phase)) {
      s.phase = "ended";
      delete s.proposal;
    }
    this.save();
    return s.reply;
  }
  private active(actor: string) {
    return Object.values(this.state.sessions).some(
      (s) =>
        s.actor === actor &&
        s.deadline > this.now() &&
        s.phase !== "ended" &&
        !s.reply.end,
    );
  }
  private create(e: Enrollment, direction: Session["direction"]) {
    if (this.active(e.actor)) throw new Error("An actor already has a call");
    const code = String(randomInt(100000, 1000000));
    const s: Session = {
      id: nonce(),
      actor: e.actor,
      direction,
      phase: "auth",
      deadline: this.now() + this.capSeconds * 1000,
      challenge: digest(code),
      authenticated: false,
      turn: nonce(),
      reply: { text: "", turn: "" },
      processed: {},
      failures: 0,
      inbox: [],
    };
    this.state.sessions[s.id] = s;
    if (this.skipDemoChallenge) {
      s.authenticated = true;
      s.authenticationMethod = "demo-handset";
      this.reply(
        s,
        "Harbor synthetic demo. This enrolled handset is using demo access. Say ready to hear pending reviews.",
      );
      return s;
    }
    this.reply(
      s,
      `Harbor synthetic demo. To authenticate, send slash voice then ${code.split("").join(" ")} in your enrolled Telegram chat. Then say ready.`,
    );
    s.authPrompt = s.reply.text;
    this.save();
    return s;
  }
  async approve(u: Incoming) {
    if (!/^\/voice\s+\d{6}$/.test(u.text ?? "")) return false;
    await this.shared.exclusive(async () => {
      const r = this.shared.recipients.find(
        (r) => r.actor === u.actor && r.chat === u.chat,
      );
      if (!r || this.state.approvals[u.id]) return;
      this.state.approvals[u.id] = true;
      const code = u.text!.split(/\s+/)[1];
      const s = Object.values(this.state.sessions).find(
        (s) =>
          s.actor === r.actor &&
          s.phase === "auth" &&
          s.deadline > this.now() &&
          s.challenge === digest(code),
      );
      if (s) {
        s.authenticated = true;
        s.authenticationMethod = "telegram";
      }
      this.save();
      await this.shared.tell(
        r,
        s
          ? "Voice call approved. Return to the call and say ready. Decisions will be made only in the synthetic simulator."
          : "No matching active voice challenge. Nothing approved.",
      );
    });
    return true;
  }
  /** Capability callbacks only resolve calls this process actually created.
   * The shared lock waits for the outbound REST result to be durably saved.
   */
  transportCall(session: string) {
    return this.shared.exclusive(async () => {
      const s = this.state.sessions[session];
      return s && s.deadline > this.now() && s.phase !== "ended"
        ? s.call
        : undefined;
    });
  }
  start(call: string, phone: string, session?: string) {
    return this.shared.exclusive(async () => {
      let s = session
        ? this.state.sessions[session]
        : Object.values(this.state.sessions).find((s) => s.call === call);
      if (!s) {
        if (session) throw new Error("Unknown outbound session");
        const e = this.enrolled.find((e) => e.phone === phone);
        if (!e) throw new Error("Handset not enrolled");
        if (
          this.provider.applicationDeadlineOnly &&
          !(await this.provider.verifyInbound?.(call, phone))
        )
          throw new Error("Incoming demo call could not be verified");
        s = this.create(e, "inbound");
        s.call = call;
        this.save();
        // Provider-enforced cap also survives a stopped laptop or unavailable notifier.
        try {
          await this.provider.limit(call, this.capSeconds);
        } catch (error) {
          s.providerFailure = {
            stage: "limit",
            diagnostic: providerDiagnostic(error),
          };
          return {
            session: s.id,
            ...this.reply(
              s,
              "I cannot safely start this call. Please use Telegram.",
              true,
            ),
          };
        }
      }
      if (
        (session && s.direction !== "outbound") ||
        (s.call && s.call !== call)
      )
        throw new Error("Call binding mismatch");
      s.call = call;
      this.save();
      if (s.deadline <= this.now() || s.phase === "ended")
        return this.reply(
          s,
          "This call session has ended. Please use Telegram.",
          true,
        );
      return { session: s.id, ...s.reply };
    });
  }
  private async current(s: Session) {
    if (!s.binding) throw new Error("No bound review");
    return this.shared.current({ ...s.binding, ...this.recipient(s) });
  }
  private async inbox(s: Session) {
    const api = this.apiFor(s.actor),
      summaries = await api.list();
    const cases: Case[] = [];
    for (const item of summaries.filter((i) => i.has_open_review).slice(0, 8)) {
      const c = await api.get(item.case_id);
      if (c.review?.status === "OPEN") cases.push(c);
    }
    const preferred = this.enrolled.find(
      (e) => e.actor === s.actor,
    )?.outboundCaseId;
    const choices = cases
      .filter((c) => c.review?.ui_mode === "CHOICE")
      .sort(
        (a, b) =>
          Number(b.case_id === preferred) - Number(a.case_id === preferred) ||
          a.case_id.localeCompare(b.case_id),
      )
      .slice(0, 3);
    s.inbox = choices.map(binding);
    s.phase = "inbox";
    const blocked = summaries.filter(
      (c) => c.workflow_status === "BLOCKED_EXTERNAL",
    ).length;
    return this.reply(
      s,
      `Currently ${summaries.filter((c) => c.has_open_review).length} pending reviews. ${blocked} cases await external action. Offering: ` +
        (choices.length
          ? choices
              .map((c, i) => `Review ${i + 1}: ${c.email.subject}.`)
              .join(" ") + " Say the review number."
          : "No choice reviews can be handled in this call. Please use Telegram or the dashboard."),
      !choices.length,
    );
  }
  private async evidence(s: Session, c: Case) {
    const api = this.apiFor(s.actor),
      r = this.recipient(s);
    if (!c.review!.source_documents.length)
      throw new Error("No inspectable evidence");
    for (const d of c.review!.source_documents)
      await this.shared.transport.document(
        r.chat,
        await api.document(c, d.document_id),
      );
    const refs = c
      .review!.options!.flatMap((o) =>
        o.kind === "VALUE" ? o.value.evidence : [],
      )
      .map(
        (e) =>
          `${e.document_id}: ${JSON.stringify(e.locator)} — ${e.source_text}`,
      )
      .join("\n");
    const text =
      detailCopy(c) +
      "\nSource locators:\n" +
      refs +
      "\n" +
      this.shared.link({ ...binding(c), ...r });
    for (let i = 0; i < text.length; i += 3500)
      await this.shared.tell(r, text.slice(i, i + 3500));
    s.phase = "evidence";
    return this.reply(
      s,
      "Source documents, locators and a dashboard link are in Telegram. When safe, inspect them and say I have checked. Otherwise say not now.",
    );
  }
  private choices(s: Session, c: Case) {
    s.phase = "choice";
    return this.reply(
      s,
      `Case ${c.case_id}. ${fieldName(c.review!.field)}, ${c.review!.side ?? c.review!.target_role ?? "document"}. ` +
        c
          .review!.options!.map(
            (o, i) =>
              `Option ${String.fromCharCode(65 + i)}${spokenOptions[i] ? ", " + spokenOptions[i] : ""}: ${o.label}.`,
          )
          .join(" ") +
        " Say " +
        c
          .review!.options!.map(
            (_, i) => spokenOptions[i] ?? String.fromCharCode(65 + i),
          )
          .join(", or ") +
        ", or say not now.",
    );
  }
  private readback(c: Case, d: DecisionRequest) {
    if (d.action !== "SELECT_OPTION")
      throw new Error("V1 supports choice reviews");
    const o = c.review!.options!.find((o) => o.option_id === d.option_id)!;
    const value =
      o.kind === "VALUE"
        ? `${o.value.normalized}${c.review!.field === "gross_weight_kg" ? " kilograms" : c.review!.field === "container_count" ? " containers" : ""}`
        : o.label;
    const alias = String.fromCharCode(65 + c.review!.options!.indexOf(o));
    return (
      `Case ${c.case_id}. ${fieldName(c.review!.field)}, ${c.review!.side ?? c.review!.target_role ?? "document"}. Option ${alias}, ${value}.` +
      (o.kind === "ESCAPE"
        ? " This closes this review and leaves verification blocked for external action."
        : "")
    );
  }
  turn(id: string, call: string, turn: string, speech: string) {
    return this.shared.exclusive(async () => {
      const s = this.state.sessions[id];
      if (!s || s.call !== call) throw new Error("Unknown call");
      if (s.deadline <= this.now() || s.phase === "ended")
        return this.reply(
          s,
          "The call has ended. Continue through Telegram.",
          true,
        );
      if (s.processed[turn]) return s.processed[turn];
      if (s.turn !== turn)
        return this.reply(
          s,
          "That response is no longer current. Please use Telegram.",
          true,
        );
      // Reserve before any external I/O. A crash cannot replay a confirmation.
      s.processed[turn] = {
        text: "This response was already handled. Please check Telegram.",
        end: true,
        turn: nonce(),
      };
      this.save();
      let r: VoiceReply;
      const priorFailures = s.failures;
      try {
        r = await this.handle(s, normalized(speech));
        if (s.failures === priorFailures) s.failures = 0;
      } catch (e) {
        r = this.reply(
          s,
          e instanceof RemoteError && e.status === 409
            ? "This review was handled or replaced. Please check the current work in Telegram."
            : "The service or evidence delivery is unavailable. Please continue in Telegram. No decision will be automatically retried.",
          true,
        );
      }
      s.processed[turn] = r;
      this.save();
      return r;
    });
  }
  private async handle(s: Session, text: string): Promise<VoiceReply> {
    if (
      /^(not now|defer|stop|cancel|i cannot look at this|i am driving|i'm driving|i cannot tell|i can't tell)$/.test(
        text,
      )
    )
      return this.reply(
        s,
        "Deferred. The review remains available in Telegram and the dashboard.",
        true,
      );
    if (s.phase === "auth") {
      if (!s.authenticated)
        return this.reply(
          s,
          text === "repeat" && s.authPrompt
            ? s.authPrompt
            : "Take your time to enter the code in Telegram. Then say ready. Say repeat to hear the code again.",
        );
      return this.inbox(s);
    }
    if (!s.authenticated)
      return this.reply(s, "Authentication required.", true);
    if (["accepted", "uncertain"].includes(s.phase)) return this.result(s);
    if (text === "repeat") return this.reply(s, s.reply.text);
    if (text === "no") {
      delete s.proposal;
      if (s.phase === "evidence")
        return this.reply(
          s,
          "Deferred. Please inspect the evidence later through Telegram.",
          true,
        );
      if (s.binding) return this.choices(s, await this.current(s));
      return this.inbox(s);
    }
    if (s.phase === "inbox") {
      const n =
        /^(?:(?:i (?:choose|select|want)|choose|select) )?(?:review )?(?:number )?(one|two|three|1|2|3)(?: please)?$/.exec(
          text,
        )?.[1];
      const i = n ? ({ one: 0, two: 1, three: 2 }[n] ?? Number(n) - 1) : -1;
      if (!s.inbox[i])
        return this.clarify(s, "Say the number of a listed review.");
      s.binding = s.inbox[i];
      return this.evidence(s, await this.current(s));
    }
    const c = await this.current(s);
    if (s.phase === "evidence") {
      if (
        ![
          "i have checked",
          "i've checked",
          "i checked",
          "i have checked the evidence",
          "i have checked the document",
        ].includes(text)
      )
        return this.clarify(
          s,
          "Inspect the evidence when safe, then say I have checked. Otherwise say not now.",
        );
      return this.choices(s, c);
    }
    const spoken =
      /^(?:(?:i (?:choose|select|want)|choose|select) )?(?:option )?([a-z]|alpha|bravo|charlie)(?: please)?$/.exec(
        text,
      )?.[1];
    const letter =
      spoken && ({ alpha: "a", bravo: "b", charlie: "c" }[spoken] ?? spoken);
    if (letter) {
      delete s.proposal;
      const option = c.review!.options?.[letter.charCodeAt(0) - 97];
      if (!option)
        return this.clarify(
          s,
          "That option was not listed. Please choose one listed letter.",
        );
      s.proposal = {
        channel: "VOICE",
        actor_id: s.actor,
        review_id: s.binding!.review,
        run_id: s.binding!.run,
        action: "SELECT_OPTION",
        option_id: option.option_id,
      };
      s.proposalExpires = this.now() + 30000;
      s.phase = "confirm";
      return this.reply(
        s,
        `${this.readback(c, s.proposal)} Shall I submit this to the simulator? Say yes or no.`,
      );
    }
    if (["confirm", "override"].includes(s.phase) && yes(text) && s.proposal) {
      if (this.now() >= s.proposalExpires!) {
        delete s.proposal;
        return this.choices(s, c);
      }
      const d = s.proposal;
      if (this.now() >= s.deadline)
        return this.reply(
          s,
          "The decision window has ended. Please hang up. Nothing submitted.",
          true,
        );
      if (s.phase === "override" && d.action === "SELECT_OPTION") {
        const o = c.review!.options!.find((o) => o.option_id === d.option_id);
        if (
          o?.kind !== "VALUE" ||
          o.value.normalized === null ||
          !c.review!.field ||
          !c.review!.side
        )
          throw new Error("Invalid override");
        d.override_confirmation = {
          review_id: d.review_id,
          run_id: d.run_id,
          field: c.review!.field,
          side: c.review!.side,
          proposed_value: o.value.normalized,
          confirmed: true,
        };
      }
      s.phase = "submitting";
      s.confirmedAt = this.now();
      this.save();
      try {
        await this.apiFor(s.actor).decide(d);
        s.phase = "accepted";
        s.outcome = "accepted";
        this.save();
        return this.reply(
          s,
          "Your decision was accepted by the simulator. Processing continues. Say status to check the result.",
        );
      } catch (e) {
        if (
          e instanceof RemoteError &&
          [
            "OVERRIDE_CONFIRMATION_REQUIRED",
            "VALUE_NOT_FOUND_IN_DOCUMENT",
          ].includes(e.code)
        ) {
          s.phase = "override";
          s.proposalExpires = this.now() + 30000;
          delete s.confirmedAt;
          return this.reply(
            s,
            `The simulator found that this value is not supported by the source. It will remain an ungrounded manual override. ${this.readback(c, d)} Confirm this exact override? Say yes or no.`,
          );
        }
        if (e instanceof RemoteError && e.status < 500) {
          s.outcome = "rejected";
          s.phase = "ended";
          throw e;
        }
        s.phase = "uncertain";
        s.outcome = "uncertain";
        this.save();
        return this.result(s);
      }
    }
    // Ambiguity cancels an existing proposal; a later bare yes cannot confirm it.
    if (s.proposal) {
      delete s.proposal;
      s.phase = "choice";
    }
    return this.clarify(
      s,
      "I could not identify one clear response. Say Alpha for A, Bravo for B, or Charlie for C, choosing only a listed option. Nothing submitted.",
    );
  }
  private clarify(s: Session, text: string) {
    s.failures++;
    return this.reply(
      s,
      s.failures >= 3
        ? "Let's stop here. Continue in Telegram or the dashboard."
        : text,
      s.failures >= 3,
    );
  }
  private async result(s: Session) {
    const c = await this.apiFor(s.actor).get(s.binding!.caseId);
    const accepted = c.history.some(
      (h) =>
        h.type === "DECISION_RECEIVED" &&
        (h.details?.decision as DecisionRequest | undefined)?.review_id ===
          s.binding!.review &&
        h.run_id === s.binding!.run,
    );
    if (s.phase === "uncertain") {
      if (!accepted)
        return this.reply(
          s,
          "I could not confirm acceptance. I have not retried. Check the current case in Telegram.",
          true,
        );
      s.phase = "accepted";
      s.outcome = "accepted";
    }
    if (c.run.run_id !== s.binding!.run)
      return this.reply(
        s,
        "That review has an accepted decision. A newer run now exists; check Telegram for its current status.",
        true,
      );
    if (c.workflow_status === "PROCESSING")
      return this.reply(
        s,
        "A decision was accepted. Processing is still continuing. Say status to check again.",
      );
    const result =
      c.workflow_status === "BLOCKED_EXTERNAL"
        ? "Your response is saved. Verification remains blocked on external action."
        : c.workflow_status === "AWAITING_HUMAN"
          ? "Your response is saved. Another review needs attention in Telegram."
          : c.workflow_status === "FAILED"
            ? "Your response is saved, but processing failed. The operator must investigate. Do not resubmit."
            : effectiveStatus(c) === "MISMATCH"
              ? "The simulated check is finished. Differences remain; a corrected document is needed."
              : "The simulated check is finished. The compared values now match.";
    return this.reply(
      s,
      result +
        " The original machine assessment is unchanged." +
        (c.resolution?.value_source === "MANUAL_OVERRIDE"
          ? " Your value remains an ungrounded manual override."
          : ""),
      true,
    );
  }
  disconnect(call: string) {
    return this.shared.exclusive(async () => {
      const s = Object.values(this.state.sessions).find((s) => s.call === call);
      if (!s) return;
      if (!["accepted", "uncertain"].includes(s.phase)) {
        s.phase = "ended";
        delete s.proposal;
      }
      s.reply.end = true;
      this.save();
    });
  }
  /** Called by the existing notifier, never a second polling coordinator. */
  tick() {
    return this.shared.exclusive(async () => {
      for (const s of Object.values(this.state.sessions)) {
        if (s.deadline <= this.now() && !s.reply.end) {
          // Reattempt hangup on a provider failure; never reattempt a decision.
          if (s.call) await this.provider.end(s.call);
          s.reply.end = true;
          if (!["accepted", "uncertain"].includes(s.phase)) {
            s.phase = "ended";
            delete s.proposal;
          }
          this.save();
        }
        if (["accepted", "uncertain"].includes(s.phase) && !s.notified) {
          const priorReply = s.reply,
            priorTurn = s.turn;
          const r = await this.result(s);
          // Background reconciliation must not invalidate the current spoken prompt.
          s.reply = priorReply;
          s.turn = priorTurn;
          this.save();
          if (r.end) {
            await this.shared.tell(this.recipient(s), r.text);
            s.notified = true;
            this.save();
          }
        }
      }
      const hour = Number(
        new Intl.DateTimeFormat("en", {
          timeZone: "Asia/Kuala_Lumpur",
          hour: "numeric",
          hourCycle: "h23",
        }).format(this.now()),
      );
      if (
        this.quiet.start <= this.quiet.end
          ? hour >= this.quiet.start && hour < this.quiet.end
          : hour >= this.quiet.start || hour < this.quiet.end
      )
        return;
      for (const e of this.enrolled) {
        if (
          !e.optedIn ||
          !e.outboundCaseId ||
          this.active(e.actor) ||
          !this.shared.state.recipients.includes(
            `${e.actor}/${this.shared.recipients.find((r) => r.actor === e.actor)?.chat}`,
          )
        )
          continue;
        const items = await this.apiFor(e.actor).list();
        for (const item of items.filter(
          (i) =>
            i.case_id === e.outboundCaseId &&
            i.has_open_review &&
            i.workflow_status === "AWAITING_HUMAN",
        )) {
          const c = await this.apiFor(e.actor).get(item.case_id);
          if (c.review?.status !== "OPEN" || c.review.ui_mode !== "CHOICE")
            continue;
          const key = `${e.actor}/${c.run.run_id}/${c.review.review_id}`;
          if (this.state.attempts[key]) continue;
          this.state.attempts[key] = true;
          const s = this.create(e, "outbound");
          this.save();
          try {
            s.call = await this.provider.start(e.phone, s.id, this.capSeconds);
            // Strict modes require provider control before readout. Explicit
            // trial-demo mode uses the approved application-only deadline.
            this.save();
            await this.provider.limit(s.call, this.capSeconds);
          } catch (error) {
            s.providerFailure = {
              stage: s.call ? "limit" : "create",
              diagnostic: providerDiagnostic(error),
            };
            this.save();
            if (s.call) {
              try {
                await this.provider.end(s.call);
              } catch (hangupError) {
                s.providerFailure.hangupFailure =
                  providerDiagnostic(hangupError);
              }
            }
            this.reply(s, "Call attempt failed. Please use Telegram.", true);
          }
          this.save();
          break;
        }
      }
    });
  }
}
