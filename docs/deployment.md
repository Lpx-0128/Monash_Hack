# Hosted release — 20 September 2026

User-agreed target: public dashboard entry with a Telegram button, automatic private-chat enrollment, persistent personal mock workspaces, full organiser inbox, Azure AI interpretation, voice disabled. Serve through 30 September 2026 23:59 Malaysia time (stop at 2026-09-30T16:00:00Z). Minimize cost; USD20 is a target, not a strict limit. Real mode will share backend cases among all enrolled visitors while keeping mock decisions separate.

## Dataset

Validated organiser archive SHA-256: `2c7ef1eb3219ca1fced4df40a94020e374cc4981bddfa2a2e65dba6efca588d1`.
520 email records; 250 attachment files: 192 TXT, 28 PDF, 22 XLSX, 8 DOCX. 394 emails have no attachments, two have one, and 124 have two. Ground truth is withheld. The sample submission is a format example, not labels.

Run `python scripts/inspect_dataset.py ARCHIVE OUTPUT_DIRECTORY`. It validates paths, sizes, IDs, source schema and attachment existence without executing archive code. Store its source email output outside Git and the public web root. `MOCK_DATASET_FILE` points to that output. Every original email gets a case. Mock categories, comparisons and review outcomes are illustrative and reproducible, not predictions or organiser answers. Generated practice evidence remains separate from original attachment references. The original archive is retained privately; original binary attachments are not served as simulated evidence.

## Hosting configuration

`deploy/hosted.env.example` documents private configuration. Use a separate state directory from local F2/V1. Copy the pinned shipping plugin into `HERMES_HOME/plugins/shipping-review` and the provided minimal Hermes configuration into that profile. Install the exact Hermes commit in `hermes/hermes-pin.json`; build a Linux environment, never copy the Windows environment. The pinned auxiliary client supports explicit `azure-foundry` routing without provider fallback. A daily interpretation call budget persists in SQLite; failures leave structured controls available.

The systemd units assume Node at `/usr/bin/node`, an installed application release at `/opt/harbor-review/current`, and pinned Hermes plus its Python environment at `/opt/hermes-agent/.venv`. The `harbor` service account owns `/var/lib/harbor-review`; the environment file is root-owned mode 0600. Expose Caddy on 80/443 only. Keep ports 5173–5175 loopback. Stop the corresponding laptop gateway before starting the cloud gateway.

Hosted guests share a read-only sample. Telegram private-chat `/start` enrolls a user (maximum 99). Each user's mock store is independent. Telegram issues a five-minute HMAC link with a fragment token; the browser clears the fragment before exchanging it for a random HttpOnly Secure SameSite session. Consumed tokens and session hashes persist. Replays are rejected. Demo control routes are disabled server-side in hosted mode.

`BACKEND_MODE=mock` selects the simulator. `real` currently fails closed at startup until the backend adapter and contract integration are completed. It never quietly serves mock state as real data. Future integration must use authenticated HTTPS, the same browser/Telegram identity and a credential scoped to public-demo-safe real processing; frozen EVAL data remains excluded. This gate is not a completed real-backend integration.

## Release gates and operations

Before public release: verify Azure resource costs and capacity, production build, actual Azure model response, two Telegram identities, session restart, foreign evidence IDs, link replay, no public mutation controls and valid HTTPS. Verify supervised services recover after VM reboot. Register the exact release digest and resource IDs here after deployment, not before.

Before updating, stop interaction and Hermes, stop the web service, then take an application-consistent copy of `/var/lib/harbor-review` and record the release. Switch the release symlink, start the web service, Hermes and interaction, then verify readiness and evidence access. Roll back both release and compatible state if necessary. Never log credentials or session links.

Month-end stopping must deallocate the VM, not merely shut down Linux; retained disk/IP resources can still incur charges. Preserve a downloadable backup before removing retained resources. No shutdown schedule should be described as active until verified in Azure or the scheduler.

## Live deployment

Public entry: https://harbor-review-52597804.japaneast.cloudapp.azure.com — HTTPS verified with a trusted certificate. Telegram: https://t.me/IMNaughty_bot. Open Telegram, press Start, choose a review, and use the private dashboard link to preserve your own mock progress. The laptop gateway was stopped before the cloud gateway started. Do not start another polling consumer for this bot.

Subscription `52597804-7254-4ee7-99ea-43c49033b2a4`; resource group `harbor-review-rg`. Existing `prc-backend-rg` resources were untouched. VM `harbor-review-vm`, Japan East, Standard_B2pls_v2 (ARM64, 2 cores, 4 GiB), Ubuntu 24.04, 32 GiB Standard HDD. Public IP `20.210.235.124`. SSH is restricted to the deployment machine's IP; only HTTP/HTTPS are public. Application ports 5173–5175 listen on loopback. Caddy and three application services are enabled under systemd.

Azure account `harbor-review-ai-52597804`, deployment `harbor-interpretation`: GPT-4.1 mini version `2025-04-14`, GlobalStandard capacity 10. A live request through the deployed Hermes bridge returned a valid 20000 kg proposal for “twenty thousand kilos.” Model calls are capped at 200 per UTC day globally and 600 output tokens per call; this is a usage control, not a hard dollar limit.

Application archive SHA-256: `18748a37416a9ef3dfeeba087185cfb380d936d82da4b6e6e1c8fce599e1b7f4`, based on commit `1fcd069bce07cf67dcebdbc5138ce6c186645e91` plus the existing working-tree work and deployment changes. Installed release `/opt/harbor-review/releases/20260920T152008Z`. Shutdown files were installed separately afterward. Credentials and the archive remain in ignored `.local/deployment`; no credentials belong in Git.

Verification: 111 TypeScript tests and production build passed; Python interpretation/provider and pinned native Telegram dispatch tests passed with mocked Telegram transport. Hosted tests cover 520 unique source IDs, two identities, shared channel identity, isolated mock progress, restart persistence, public write rejection, foreign evidence rejection, tampered/replayed links and cross-origin writes. The actual VM reboot recovered all services; `/ready` returned ready and the gateway logged Telegram polling connected. Public browser verification confirmed the dataset count and Telegram entry button. Actual end-to-end review/confirmation by two human Telegram accounts remains a manual acceptance test; no messages were sent on a user's behalf.

## Cost and stopping

### Telegram queue hotfix — 20 September

The first live user report exposed queue delivery failures after expansion to 520 emails (75 actionable cases). The old digest rendered every case in one keyboard and saved its delivered signature before transport acceptance, suppressing retry on failure. The deployed engine now uses ten-case pages with authenticated Previous/Next callbacks and records digest completion only after delivery. Navigation refetches current case availability; individual selection retains run/review checks and document delivery. Progress and identities were preserved. Engine SHA-256 `407e4b55f0c11470d06ea22474c7fbdb746d1a52b4d5d6697e665c3336d7d525`; pre-fix engine and interaction state are backed up under the VM's private deployment directory. All 17 Telegram tests pass, including full-inbox traversal, selected documents/buttons and failed-send recovery across restart. Live user acceptance requires a fresh `/reviews` command.

Observed official [Azure Retail Prices API](https://prices.azure.com/api/retail/prices) rates on deployment day: VM USD0.0432/hour, Standard IPv4 USD0.005/hour, S4 LRS disk USD1.536/month plus USD0.0005 per 10,000 operations. Roughly 241 remaining hours gives about USD12.10 for VM, IP and prorated disk through the deadline, before AI, traffic, tax and other subscription resources. USD20 is a reasonable target for the expected light usage, not a guarantee. Actual Azure credits and billing totals remain unverified.

`harbor-deallocate.timer` is enabled on the VM and verified for `2026-09-30 16:00:00 UTC` (1 October 00:00 Malaysia). It persists across reboot and retries failures every five minutes. The Python script refuses execution before the deadline. The VM's managed identity has a custom role containing only `Microsoft.Compute/virtualMachines/deallocate/action`, assigned only on this VM. Role ID `50d47dc2-802b-4f87-ab10-2ed48877d1f2`; assignment `5ada0fef-3dce-400a-9b83-8a13596c9cff`. Do not broaden it. Deallocation itself was not triggered during verification because availability is required until month-end.

An additional Codex follow-up `stop-harbor-review-after-judging` checks deallocation at the deadline. The native VM timer does not depend on the laptop. Retained disk and static IP can continue accruing small charges after compute stops; preserve state before explicitly removing them. The timer does not delete data or unrelated resources.
