# F3 — Copilot interpretation

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

This uses synthetic context and real Copilot requests, writes `docs/F3-evaluation.json`, and never submits decisions. Review the measured results, not just the process exit code. See [verification](F3-verification.md) for limitations and real-backend gates.
