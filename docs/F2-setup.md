# F2 setup — first Telegram bot

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

Already installed locally during this implementation. On a fresh machine with the same Hermes Desktop layout:

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

F2 exposes no model tools and does not invoke an LLM for shipping actions. No model key was needed by the native-plugin tests. Full live gateway startup still needs verification; if the installed gateway requires provider setup independently, configure it through Hermes's local credential UI, never by pasting a key into this repository or conversation.

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

**Pinned Hermes limitation:** initial gateway polling uses `drop_pending_updates=True`. Updates sent while the gateway is offline may therefore be discarded before the plugin sees them. Send `/start` after startup and use a fresh explicit confirmation if an offline action never arrived; never assume it was accepted. Plugin-received updates and application mappings are restart-tested, but this pre-receipt transport gap remains an upstream/live reliability limitation.

## Configuration reference

`TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USERS`, `HERMES_HOME`: dedicated Hermes gateway.

`F2_BRIDGE_TOKEN`, `F2_PORT` (5174), `F2_BRIDGE_PORT` (5175), `F2_BRIDGE_URL`: authenticated loopback integration. Do not expose these listeners publicly.

`F2_BACKEND_TOKEN`, `F2_ACTORS`, `F2_BACKEND_URL`, `F2_RECIPIENTS`: service credential and explicitly authorized actor/chat tuples. The simulator verifies actor assertions against this server-side allowlist; browser JSON cannot impersonate Telegram.

`F2_DASHBOARD_URL`, `PORT` (5176), `SIMULATOR_STATE_FILE`, `F2_STATE_FILE`: preview URL and persistent files. URLs contain no credentials. For a real backend, coordinate its authentication mapping and repeat all checks; do not assume the simulator-specific `X-Telegram-Actor` transport assertion is already supported.

Official references: [Hermes plugin handlers](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins), [Hermes Telegram setup](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/telegram). The implementation uses `register_platform_handler`, native PTB dispatch, and `Application.bot` delivery; it does not patch Hermes core or use generic clarification/approval prompts.
