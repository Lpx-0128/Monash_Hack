# Setup and walkthrough

Current local simulator, dashboard, Telegram and optional Copilot setup. For verification boundaries see [verification](verification.md).

For a presentation, use the [four-minute rehearsal](#four-minute-judge-rehearsal) and [backup-recording plan](#backup-recording-plan). These prepare a simulator demonstration; they do not replace PRD 2's final real-integration gate.

## Run

Requires Node **22.12+** and npm. From this repository:

```sh
npm ci
npm run build
npm start
```

Open **http://localhost:5173**. This is the production build served alongside the API. For development with hot reload use `npm run dev` instead. Stop the other server before switching. `PORT` and `HOST` can be set in the launching environment; `.env.example` documents settings (the server does not automatically load a `.env` file).

## Try the F1 review journeys

Open **All cases**; reset through **Demo controls → Reset demo** to restore all 23 synthetic scenarios. Reset creates fresh run IDs so an old confirmation cannot target a new demonstration.

| Journey                | Case and steps                                                                                                              | Observable result                                                                                                        |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| Grounded input         | **Source available · enter BL gross weight**; enter `21707`, Preview value, Confirm submission                              | 202 acceptance, about four seconds of processing, then human document-confirmed value and operational OK                 |
| Manual override        | **Gross weight needs confirmation**; enter `22000`, preview and submit; inspect the rejection, then Confirm manual override | Review stays open on rejection; confirmed value stays ungrounded; operational mismatch and correction-required follow-up |
| Change/cancel          | Cancel an override proposal or edit the input                                                                               | Confirmation disappears; new value requires a new preview and confirmation                                               |
| Candidate choice       | **Two gross-weight candidates**; inspect evidence, select an option and confirm                                             | Grounded candidate applied; `21707` matches, `22000` produces mismatch                                                   |
| Unsupported candidate  | **Unsupported candidate · explicit override**; choose `23000` and confirm                                                   | Same grounding rejection and exact override flow as typed input                                                          |
| Document assignment    | **Identify the draft bill of lading**; inspect source, choose BL document and confirm                                       | Target role BL assigned; all BL values recomputed from that immutable synthetic source                                   |
| Two reviews            | **Two sides · SI before BL**; enter `21707` for SI, then again for the new BL review                                        | First result remains NEEDS_REVIEW; no proposal carries into the second review; then operational OK                       |
| Two fields             | **Two uncertainties · first review**; confirm count `3`, then weight `21707` (requires override)                            | Canonical field order and frozen machine assessment preserved                                                            |
| External action        | **Missing draft BL · external action**, or “I can’t tell” / “None of these” on other reviews                                | Brief accepted/processing state, then CLOSED review and BLOCKED_EXTERNAL, never completion                               |
| Known mismatch         | **Known container mismatch · weight review**; resolve weight with `21707` override                                          | Count mismatch remains visible throughout and ends with correction-required follow-up                                    |
| Lost response          | Demo controls: **Next decision simulation → Accept, then lose response once**; submit a grounded review                     | UI refetches authoritative state; no automatic resend or false failure                                                   |
| Resumption failure     | **Decision journey · simulated resumption failure**; submit `21707` override                                                | FAILED with accepted decision retained; operator recovery required, no re-entry                                          |
| Competing/stale action | Open the same review in two tabs; resolve or reprocess in one, then attempt an old action in the other                      | First acceptance wins; old actions return 409 and refresh; drafts never transfer to another review/run                   |

Ordinary numeric entry is deliberately canonical: positive whole counts; positive kg values with a dot decimal and no grouping separators. Unsupported/ambiguous notation is explained before submission. Known/unknown receipt times remain distinct from case creation and update times.

Polling runs every three seconds. Decisions normally resume after four seconds; replays after eight. **Advance processing** is an explicit shortcut. Source documents/evidence, filters, empty/reset states and connection fault controls remain available. Demo controls apply only to this browser's guest session.

The production preview atomically saves demo sessions, accepted decisions and pending jobs in ignored `.local/simulator-state.json` before returning 202. Restart recovery is tested. Set `SIMULATOR_STATE_FILE` for another writable location; retain that directory across container restarts if desired. This is a single-process synthetic store, not a production database or multi-instance coordination service. Reset intentionally clears that session's history/work. Guest sessions expire after two idle hours; use reset for a repeatable walkthrough. No browser credentials, model calls or real documents are involved.


## Telegram setup

This milestone uses synthetic cases and simulated grounding. Hermes owns Telegram connectivity; the shipping plugin owns deterministic routing, and the shared REST API owns all decisions. Real-backend acceptance is separate.

## 1. Create a dedicated bot

In Telegram, open the verified **@BotFather**, send `/newbot`, and choose a name and a username ending in `bot`. Keep the token private. Open your new bot and press Start. Do not configure this token in another polling bot or in the default Hermes Desktop profile.

## 2. Store credentials locally

From this repository in PowerShell:

```powershell
python scripts/f2_setup.py configure
```

The hidden prompt stores the token in ignored `.local/f2-settings.json`, `.local/f2.env`, and `.local/hermes-shipping/.env`. It generates separate backend and loopback-bridge credentials. Nothing is printed or committed. The profile is separate from your personal Hermes Desktop profile. Do not share `.local` or logs. On Windows these files inherit your user-directory ACL; POSIX modes are not an additional Windows security boundary.

The default F2 dashboard uses **http://localhost:5176/cases**, leaving the existing F1 preview on 5173 untouched. F2 deliberately shares one synthetic backend namespace between its dashboard and bot; reset/advance/fault controls affect both. The default F1 session isolation is unchanged.

## 3. Install pinned gateway dependencies

On a fresh machine with the Hermes Desktop runtime installed:

```powershell
uv pip install --python "$env:LOCALAPPDATA/hermes/hermes-agent/venv/Scripts/python.exe" --target .local/f2-python "python-telegram-bot[webhooks]==22.8" "aiohttp==3.14.3"
```

Hermes source is pinned to `44945d224c2ccd6e0a55f16223c7ab0dd39331bf` (installed package version 0.21.3). `gateway` refuses a different commit. Do not silently update the pin: repeat compatibility tests first. Use `--runtime <path>` with the setup script for another Hermes checkout. A runtime installation and its own dependencies are prerequisites; the command above adds the optional Telegram packages without modifying the Desktop runtime.

## 4. Pair your test account

```powershell
python scripts/f2_setup.py gateway
```

Keep this terminal running. Send `/start` to your new bot **again while this gateway is running**. During pairing, the bot deliberately sends no case data and no unsolicited reply. It records only the private sender/chat IDs locally. Hermes is the only Telegram inbound consumer; no setup script calls `getUpdates`.

In a second terminal:

```powershell
python scripts/f2_setup.py approve
```

Select your observed Telegram account and type `AUTHORIZE` only after checking the shown IDs. This explicitly authorizes synthetic documents/messages to that private chat, including test operator notices. No other chat is authorized. Stop the gateway with Ctrl+C and restart it to load the allowlist.

## 5. Run all three components

Use three terminals from this repository:

```powershell
# Terminal 1: simulator plus dashboard
npm run dev:f2

# Terminal 2: deterministic routing and the single notifier
npm run start:f2

# Terminal 3: Hermes gateway with the shipping plugin
python scripts/f2_setup.py gateway
```

After all three start, send `/start` again. Open **http://localhost:5176/cases**. A selectable digest lists the backlog; choose one case to open its review and source documents. Large backlogs do not automatically drain into chat. Subsequent reviews/results and small newly arriving batches remain proactive, with bounded spacing. A digest does not mark individual reviews delivered. `/pause` stops proactive notifications across restarts; `/reviews` resumes with a selectable queue.

The deterministic Telegram flow needs no LLM. Optional Copilot interpretation is configured below. Live Telegram checks against the simulator have passed; real-backend checks remain outstanding.

## Walkthrough

- **Source available:** reply to its individual review with `21707`; inspect canonical BL/kg preview; press Confirm value. Observe accepted, processing, then operational OK in the dashboard, with frozen NEEDS_REVIEW.
- **Gross weight needs confirmation:** reply with `22000`, confirm, then inspect the rejection and Confirm exact override. Cancel or reply with another value to invalidate the old proposal. The final value remains human-provided and ungrounded.
- **Two gross-weight candidates / Identify the draft BL:** use a candidate or document-role button; None of these leads to an external block.
- **Two sides:** reply `21707` to SI first; use the newly delivered BL review for the second value. An old message cannot address the new review.
- **Missing draft BL:** acknowledge; after processing it remains blocked externally.
- **Container quantity differs:** correction notice only, no invented review. Failures go to the authorized test operator.
- **Demo controls:** accept-then-lose-response and simulated resumption failure exercise recovery. Reset starts new run IDs; old Telegram buttons become stale.

Bare numbers and generic yes do not choose a review. `/reviews` enables review delivery; the digest/dashboard link provides case selection. `/reset` in this restricted profile never erases shipping routing or confirmations and does not invoke generic Hermes model commands.

## Restart and recovery

Stop a component with Ctrl+C, then repeat its start command. Keep `.local/f2-state.json`, `.local/f2-simulator.json`, and `.local/hermes-shipping/shipping-inbound.sqlite` with their companion SQLite WAL files. They serve different roles: application routing, backend truth, and received Telegram update progress. The notifier refuses a live owner lock and automatically recovers a positively dead PID; an invalid lock needs operator inspection, not blind deletion.

Received updates are persisted before forwarding. Proposals in `sending`/`uncertain` are reconciled by GET after restart and never automatically resubmitted. Successful notification sends are persisted before the API marker, allowing marker-only recovery. A crash after Telegram sends but before local persistence can duplicate a notification; backend decisions still accept only once.

## Configuration reference

`TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USERS`, `HERMES_HOME`: dedicated Hermes gateway.

`F2_BRIDGE_TOKEN`, `F2_PORT` (5174), `F2_BRIDGE_PORT` (5175), `F2_BRIDGE_URL`: authenticated loopback integration. Do not expose these listeners publicly.

`F2_BACKEND_TOKEN`, `F2_ACTORS`, `F2_BACKEND_URL`, `F2_RECIPIENTS`: service credential and explicitly authorized actor/chat tuples. The simulator verifies actor assertions against this server-side allowlist; browser JSON cannot impersonate Telegram.

`F2_DASHBOARD_URL`, `PORT` (5176), `SIMULATOR_STATE_FILE`, `F2_STATE_FILE`: preview URL and persistent files. URLs contain no credentials. For a real backend, coordinate its authentication mapping and repeat all checks; do not assume the simulator-specific `X-Telegram-Actor` transport assertion is already supported.

Official references: [Hermes plugin handlers](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins), [Hermes Telegram setup](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/telegram). The implementation uses `register_platform_handler`, native PTB dispatch, and `Application.bot` delivery; it does not patch Hermes core or use generic clarification/approval prompts.
## Offline messages and gateway restarts

The dedicated shipping plugin preserves pending Telegram updates on startup and recovery. Keep using `python scripts/f2_setup.py gateway`; it copies the current project plugin into the dedicated profile and checks the pinned Hermes version. This adjustment does not modify your general Hermes installation. Only long polling is verified; the launcher rejects `TELEGRAM_WEBHOOK_URL`.

You can send a review reply during a short gateway outage. Once the gateway restarts, the reply still needs its usual confirmation and must target a current review. Old reviews are rejected. Live offline replies and confirmation clicks were verified against the simulator on 20 September 2026.

Run only one gateway for this bot token. If Telegram reports a polling conflict, stop the other gateway rather than clearing pending updates. Telegram keeps pending updates for no longer than 24 hours; this is not unlimited offline storage. See [verification notes](verification.md) for the remaining transport crash window and real-backend gate.

## Optional Copilot interpretation

The dedicated Hermes shipping profile can interpret natural-language replies into review proposals. It cannot approve its own proposals or invoke general agent tools. Dashboard and canonical Telegram paths work without a model.

## Provider setup

From the repository, after F2 pairing:

```powershell
python scripts/f3_copilot.py login
python scripts/f3_copilot.py models
python scripts/f3_copilot.py enable --model gpt-4.1
```

Complete GitHub device authorization yourself. Never paste a token into chat. The helper stores the credential only in ignored local settings and the dedicated Hermes profile. `gpt-4.1` was available and verified for the test account; select an available model from your own catalog. Subscription entitlements and request limits still apply; this is not a claim of free or unlimited usage.

Restart the gateway and interaction service after changing settings. Keep one instance of each, in three terminals:

```powershell
# Terminal 1
npm run dev:f2
# Terminal 2
npm run start:f2
# Terminal 3
python scripts/f2_setup.py gateway
```

Open http://localhost:5176/cases. In the paired bot, `/reviews` opens the selectable backlog. Choose a review, then use Telegram's **Reply** on that individual review message. A bare message does not select a case.

## Try it

- Replay **Source available** (`demo_grounded-input`), open its fresh Telegram review, and reply “I think the BL says twenty-one thousand seven hundred and seven kilos.” Inspect the **21707 kg** proposal; only **Confirm value** submits it.
- For a candidate review, reply “Use the second option.” Inspect the selected label before confirming. Document-role proposals retain the explicit SI/BL target role.
- Try “twenty-ish tonnes,” a wrong-side answer, or two competing values. The bot asks for clarification instead of submitting.
- An unsupported precise value can become a proposal, but the simulator still rejects grounding. Only the separate exact override confirmation accepts it as human-provided and ungrounded.
- Change the reply or replay the case before confirming: old proposals cannot move to the new review/run.

Messages distinguish deterministic parsing/Copilot interpretation, proposal, human confirmation, 202 acceptance, and eventual simulated outcome. The dashboard shows backend history and operational outcome separately from the frozen machine assessment. A model proposal is not evidence of grounding.

`/pause` stops proactive notifications; `/reviews` resumes. To disable interpretation, run `python scripts/f3_copilot.py disable`, then restart terminals 2 and 3. Buttons and canonical values remain available.

## Evaluation

With the three services running and F3 enabled:

```powershell
npx tsx --env-file=.local/f2.env scripts/f3_evaluate.ts
```

This uses synthetic context and real Copilot requests, writes `docs/interpretation-evaluation.json`, and never submits decisions. Review the measured results, not just the process exit code. See [verification](verification.md) for limitations and real-backend gates.

## Message controls

The bot uses short action-first messages. **View details** reveals evidence, provenance and machine/operational state without submitting anything. Reply to the original review, not the details message. **Open dashboard** supplies the case URL; localhost works only on the laptop running the demo. Copy it into that browser if Telegram does not link it. Historical messages keep their old wording.

## Deployment configuration

No hosting provider, deployment project or credentials were supplied. **Hosted deployment is outstanding; F0's deployed exit gate is not claimed complete.** The local production preview is the verified deliverable.

A Dockerfile builds the client and runs a non-root Node service. On a container host:

```sh
docker build -t harbor-review-f0 .
docker run --rm -p 5173:5173 harbor-review-f0
```

Use a single always-running instance with a persistent writable state directory (the simulator does not coordinate multiple processes), port 5173, health route `/health`, readiness route `/ready`, and HTTPS at the hosting edge. Set `COOKIE_SECURE=true` for HTTPS. Do not deploy only `dist/` to a static host: the demo requires its Node API. Docker execution itself requires a local Docker daemon and is reported separately from the verified Node build.

## Four-minute judge rehearsal

**Internal rehearsal label:** “Synthetic cases; simulated extraction, grounding and processing. Telegram transport and optional Copilot interpretation are real when enabled.” Keep that distinction visible and say it aloud. Final submission must replace the simulated core with approved real processing and repeat this rehearsal.

Preparation, before the clock starts:

1. Browser-only: `npm run build`, then `npm start`; use http://localhost:5173. This isolated guest session does not send Telegram messages. For the Telegram variant, start the three configured components above and use http://localhost:5176 instead; this demo shares state with the paired bot.
2. Check `/health` and `/ready`; open the dashboard. Confirm the synthetic notice and normal connection mode. Close private tabs, terminals, configuration files and notification previews before screen sharing.
3. Use **Demo controls → Reset demo** for a clean rehearsal session, or open `demo_grounded-input` and **Replay / Reprocess** to reset only that case. Wait for its new OPEN review (replay normally takes eight seconds). Never reuse a preview or Telegram message from an earlier run. Reset on 5176 affects both the shared dashboard and bot; coordinate with other testers first.
4. Main fixture: **Source available · enter BL gross weight** (`demo_grounded-input`), source-supported BL weight **21707 kg**. Optional contrast: **Container quantity differs** (`demo_mismatch`) or **Missing draft BL · external action** (`demo_blocked-open`). Do not choose a missing-weight fixture expecting document-confirmed success: unsupported values require explicit override.

### Browser-only route (approximately 4 minutes)

| Time | Action and brief narration | Expected visible result | Recovery |
| --- | --- | --- | --- |
| 0:00–0:30 | Show overview. “A coordinator checks a draft BL against the shipping instructions. We surface uncertainty and discrepancies instead of asking them to monitor every step.” State the simulator label. | Distinct pending decisions, failures and operational/machine outcomes; synthetic banner remains visible. | If offline, use the labelled backup; do not describe stale data as current. |
| 0:30–1:00 | Select **Needs input**, then **Source available · enter BL gross weight**. | Correct case, OPEN BL weight review, current run and original Needs review assessment. | Search the exact title, or use All cases. If already closed, replay and wait for the new review before restarting the take. |
| 1:00–2:00 | In Gross weight, expand SI and BL evidence. Open the BL source, read its weight line and return to the case. “The value must be supported by the source, not just guessed.” | SI raw `21,707 KG`, BL raw `21707.00 kgs`, normalized 21707, explicit provenance and exact source quote. | If document access fails, stop the decision step; retry authorized access or use the backup. Do not submit an unchecked value. |
| 2:00–2:40 | Enter `21707`, **Preview value**, read BL/field/kg and proposed value, then **Confirm submission**. | No submission before confirmation; acceptance shows Processing and previous result updating. | Invalid input: correct the format. Stale review: refetch/open the new review. Uncertain response: refetch decision status; never click through old confirmations or automatically resend. |
| 2:40–3:20 | Wait for natural polling (normally four-second worker plus up to three-second poll). Show the result and history. “Accepted means queued, not finished. Human resolution updates the operational result without rewriting the automated assessment.” | Completed, operational OK, Human document-confirmed/Grounded, original machine Needs review; received/applied history. | If processing fails, show retained acceptance and operator recovery. Do not claim completion. Advance processing is a labelled simulator shortcut only, not evidence of real worker speed. |
| 3:20–4:00 | Open **Container quantity differs** to contrast a known mismatch. Close with “A completed check can still require a corrected document.” | Completed Mismatch with correction-required follow-up, not an invented approval review. | Use the main completed case if time is short; explain the distinction without claiming an unshown action occurred. |

### Telegram variant (approximately 4–5 minutes)

Use this instead of the browser input segment, not as a second full presentation. The operator must already have paired and explicitly approved the presenter's own private test account using `f2_setup.py approve`. There is no automatic judge enrollment or invitation flow. Use exactly one gateway per bot token and preserve its ignored routing state.

- **0:00–0:40:** show the shared dashboard/problem and disclose simulation. Send `/reviews` in the authorized bot; select the current **Source available** case. If its notice was already delivered, `/reviews` can reopen it. Large queues remain selectable; do not promise a message flood.
- **0:40–1:40:** inspect the attached BL or **View details**. Use Telegram **Reply on the review message itself**, type `21707`. Optional F3 alternative: the written-out weight sentence above, explicitly described as real Copilot reply interpretation, not AI extraction.
- **1:40–2:40:** read the preview, click **Confirm value**, show accepted/processing and wait for the resulting bot notice. If grounding rejects a value, do not silently override: inspect the source, cancel/change, or explicitly demonstrate the separate ungrounded override flow.
- **2:40–4:00:** open the same case on the shared dashboard; show operational OK, unchanged machine Needs review and TELEGRAM history. Explain that `/pause` stops proactive notifications, while existing review buttons remain usable.
- **Recovery:** if Telegram is unavailable, say so and switch to the browser route. Refetch a possibly accepted decision before retrying. Localhost links work only on the presenting laptop; copy the address into its browser if Telegram does not link it. Do not claim phone access without a hosted HTTPS address and a separate device check.

### Troubleshooting and integration configuration

| Symptom | Check / supported recovery |
| --- | --- |
| Blank production page after cleanup | Run `npm run build` before `npm start`; `dist/` is generated. Use `npm run dev` for hot reload. |
| Address already in use | Keep one service per configured port. Inspect the existing terminal; do not start duplicate gateways or blindly kill unrelated processes. |
| No private `/start` observed during pairing | Keep the dedicated gateway running and send `/start` again. Approve your own observed account locally; do not paste tokens into chat. |
| No proactive messages | Check `/pause` state, then `/reviews`, the queue, gateway connectivity and authorized recipient configuration. A large backlog is intentionally held until selected. |
| Reply not understood / no case selected | Reply to the original current review, not its details or a generic message. Try a canonical value or buttons if Copilot is unavailable. |
| Review replaced or already handled | Refresh/reopen the current case. Do not migrate an earlier proposal or confirmation. |
| Grounding rejection | The review remains open. Recheck the source; a manual override requires explicit exact confirmation and remains human-provided/ungrounded. |
| Lost response or failed resumption | Refetch authoritative state; accepted input is retained. Do not re-enter it as recovery. Use an operator recovery procedure when the real backend is available. |

Simulator launch commands always use the Node synthetic service. `VITE_API_MODE=live` and `VITE_API_BASE=/api/v1` select the frontend adapter at build time; they do not turn this server into PRD 1 or establish trusted live identity. Real deployment needs an authenticated same-origin gateway, approved DEMO cases/documents, trusted actor mapping and a real durable backend. Current live decision controls remain unavailable until that identity integration is supplied.

Server-side placeholder settings for coordinated integration (never put secrets in `VITE_*`): `F2_BACKEND_URL=<approved-backend-url>`, `F2_BACKEND_TOKEN=<server-secret>`, `F2_DASHBOARD_URL=<public-https-dashboard>`, and explicitly authorized `F2_RECIPIENTS` / `F2_ACTORS`. Match the agreed real-backend authentication scheme before connecting; the current transport assertion is simulator-specific. See `.env.example` and the configuration section above. These real-deployment steps are **not verified** without the backend/hosting dependency.

Unattended judge access is an **outstanding coordinated design dependency**, not an existing feature. PRD 2 §6.2 requires starting the bot and allowlisting/authentication; it permits a scoped safe dashboard guest but defines no automatic Telegram approval, invitation endpoint or isolated per-judge shared-bot session scheme. Agree ownership, invitation lifetime/revocation, actor binding, session isolation/reset, rate limits and DEMO document scope before implementing any extension. Retain the current allowlist meanwhile.

## Backup-recording plan

The storyboard follows the browser script; record the Telegram variant only with an authorized account and a working gateway. Target a continuous 3–5 minute take at 1440×900 or another readable landscape size; inspect at phone width separately. No final video is produced or certified by this plan.

| Segment | Screen / capture | Evidence to retain |
| --- | --- | --- |
| Opening (30 seconds) | Overview and synthetic label for rehearsal, or correctly labelled approved real environment for final take | Environment/build identifier and presenter statement of what is real |
| Find case (30 seconds) | Needs input → exact case | Current case/run, OPEN review and question |
| Inspect (60 seconds) | SI/BL comparison → BL source → return | Source quote, normalized value, document provenance; no private EVAL data |
| Decide (40 seconds) | Enter value → preview → confirm | Exact target/value and explicit human action; optional Telegram reply/preview instead |
| Observe (40 seconds) | Uncut acceptance → processing → result → history | Do not splice away a failure or replace processing with an unrelated completed fixture |
| Explain follow-up (40 seconds) | Known mismatch or external-block example | Completion versus correction/external work; honest boundary statement |

Before recording, reset/replay through the supported UI, wait for the new review, verify normal fault mode and source access, and hide unrelated browser tabs/chat lists, OS notifications, terminals, account IDs, device-login codes, `.env` and `.local` files. Capture the app window or bot conversation pane, not the full desktop. Use only explicitly demo-safe documents. Do not record BotFather, authorization setup or credential entry.

Keep an unedited master take and record the commit, environment, case/run IDs, date, actual provider usage and observed outcome in release notes. A short edited presentation may improve pacing but must not substitute for the continuous workflow evidence. If real services fail, stop and retain the failed take for investigation; use the clearly labelled simulator recording only for internal rehearsal. It does not satisfy the final real-integration requirement.

Final recording checklist:

- [ ] Approved real backend, deployment and trusted actor/document access verified; meaningful real AI processing evidence from PRD 1 available.
- [ ] Fresh approved DEMO case; correct source, review and run; resets/replays exercised against the real pipeline.
- [ ] Browser route rehearsed end to end on the final build; Telegram route verified or transparently omitted with its dependency stated.
- [ ] No credentials, private messages, EVAL data or misleading synthetic/real labels in any frame.
- [ ] Preview, explicit confirmation, acceptance and resulting state are visible; original machine assessment remains distinguishable.
- [ ] Audio, text size, playback, captions if used and duration checked; complete unedited backup saved.
- [ ] Video, public prototype, repository and submission links opened in a clean unauthenticated browser where intended; owners/access confirmed.
- [ ] Final release evidence and limitations updated; no all-F4-complete claim while any required real integration, final rehearsal or recording remains open.
