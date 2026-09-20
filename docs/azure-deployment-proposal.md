# Azure deployment proposal — application hosting and backend integration

Draft, 20 September 2026. This is a deployment plan, not a deployment completion report. Source reviewed: `feat/prd-2-interaction-frontend` in `C:/Users/lee/Downloads/Monash_Hack`, including uncommitted V1 work, PRDs 1–3 and Shared Contract. No application code or contract was changed by this review.

## Purpose and target outcome

Deploy the Interaction Layer as a continuously available application: dashboard, Telegram/Hermes, and Azure-hosted AI interpretation must work without laptop terminals. Establish the deployment and API boundaries now so the team can connect PRD 1's real backend when it is ready. The backend remains authoritative for business data and workflow execution.

The plan covers three stages: hosting the current application with a simulated backend, integrating the real backend, and operating/updating the combined product. A public judge demo is an additional supported mode within this plan, with separate synthetic data and access rules.

## Recommended first deployment

Deploy the existing three processes together on one small, always-on Azure Linux VM, with a separate Azure-hosted model deployment. Keep voice disabled initially. Build the backend adapter/configuration boundary during deployment preparation, while using the simulator until the real backend passes integration tests.

PRD 1 may run in its own deployment or eventually share infrastructure. Neither choice should require redesigning the dashboard or Telegram flows: they access backend capabilities through the Shared Contract. Preserve the permanent synthetic demo independently of this transition. A single VM is the first prototype hosting choice, not a requirement that every future service share one machine.

This is a conditional recommendation. The signed-in portal confirms an active Azure for Students subscription with Owner access. Available VM capacity and model quota are not yet verified. Do not interpret the advertised student offer as proof that a particular model can be deployed in this account.

### Read-only Azure check results

| Check | Observed result |
|---|---|
| Subscription | Azure for Students; Active; current user is Owner |
| Current costs | Portal shows USD0.70; this is not confirmation of remaining credit |
| Allowed-location policy | `indiasouthcentral`, `uaenorth`, `eastasia`, `centralindia`, `japaneast` |
| Compute quota | Portal reports selected provider not registered; quota/capacity not verified |
| Foundry inventory | No AI resources displayed with all subscription/type/location filters |
| Model entitlement and deployment quota | Not yet verified; empty resource inventory does not mean zero quota |

The next provisioning preparation step is to register the required resource providers, then inspect compute and Azure AI quota in permitted regions. Provider registration changes subscription configuration and was not performed during this read-only check. Do not change the region policy to bypass the restriction. Select a supported model in an allowed region or obtain an approved alternative. Existing unrelated Container App resources were left untouched.

## Deployment modes

| Mode | Purpose | Backend and access |
|---|---|---|
| Initial hosted application | Verify cloud operation before teammates finish PRD 1 | Simulator; authorized team users; persistent state |
| Integrated application | Exercise the full product across PRD 1 and PRD 2 | Real backend; agreed identity and authorization; backend-owned business state |
| Public judge demo | Provide a reliable, independently available demonstration | Isolated synthetic workspaces; automatic demo enrollment; no access to real data |

Use the same application code and explicit server-side configuration where practical. Keep credentials, state and bot consumers separated between modes. The user must not be able to select a real backend by modifying a browser parameter. An integrated environment may still use contract-defined DEMO runs for permitted sample cases; backend implementation choice and run kind are different concepts.

## Architecture

```text
User browser ─ HTTPS ─ reverse proxy ─ dashboard / authenticated API adapter
                                                       │
Telegram ─ outbound long polling ─ Hermes ─ interaction service
                                   │                   │
                                   └─ Azure AI         └─ Shared Contract
                                                              │
                                   configured backend target ─┤
                                   simulator (initial/demo)   │
                                   PRD 1 backend (integrated) ─┘

First interaction host: Node application, Node interaction service, Python Hermes
Interaction storage: sessions, interaction state, Hermes profile/SQLite
Simulator storage: synthetic data only
Real backend storage/workers: owned and deployed by PRD 1
```

This diagram is the target boundary; the current Node application always starts the simulator and still needs an authenticated real-backend adapter. Use a service supervisor such as systemd to start and restart the three processes after reboot. Bind internal APIs to loopback and expose only the HTTPS application. Serve a production frontend build. Use a stable DNS name and valid TLS certificate so access survives laptop shutdown and application updates.

Start with a candidate 2-vCPU/4-GiB general-purpose or burstable VM, subject to quota, price and memory verification. Keep one instance and one Telegram polling consumer. Persistent single-writer JSON/SQLite is acceptable for this small prototype, not an architecture for horizontal scaling. Maintain an application-consistent backup before releases.

### Why this hosting method

| Option | Fit for this branch | Recommendation |
|---|---|---|
| Linux VM, three supervised processes | Preserves localhost bridge assumptions and ordinary local persistent files | First deployment |
| Container Apps with multiple containers | Requires complete packaging, persistent-storage validation and careful single-consumer rollout | Revisit after prototype |
| Separate hosted services now | Requires changing loopback connections and securing new service boundaries | Avoid for the first deployment |

The existing Dockerfile packages only the dashboard/simulator. It is not a complete Telegram/Hermes deployment artifact. A VM still requires a reproducible install/start procedure; copying a Windows virtual environment is not sufficient.

## Application deployment requirements

| Gap verified in current code | Required change |
|---|---|
| `hermes/shipping-review/interpretation.py` explicitly resolves `copilot` | Add configurable Azure inference compatible with the pinned Hermes version; preserve bounded interpretation and strict proposal validation |
| Node application always starts the simulator | Add explicit backend selection and an authenticated real-backend adapter; never silently fall back to synthetic state on backend failure |
| Browser and Telegram identity are not securely linked | Map both to the same authorized user and data scope; use secure browser sessions and an expiring link exchange where applicable |
| Local Windows paths and separate terminals | Configure Linux runtime/data paths and supervised startup with persistent storage |
| Health endpoints currently return basic `ok` | Add readiness checks and operational checks for state access, gateway and model configuration; distinguish degraded AI from app outage |

Enforce authorization on evidence downloads as well as case APIs. Store secrets server-side, separate each environment's configuration, and use bounded request/model consumption. Keep real business state in the backend; interaction storage holds session, routing and delivery information. Define backup, restart and rollback procedures for each state owner.

Do not upgrade Hermes opportunistically: first validate the pinned runtime's provider support. If a provider adapter is needed, keep it small and test malformed responses, timeouts and unsupported model parameters. A model error should leave the review pending and offer existing structured controls; it must not produce a guessed decision.

## Public judge demo requirements

This mode is part of the deployment, not the definition of the whole product. It must remain available independently of the real backend's readiness.

1. A judge follows the public website's link(Dashboard), from ther navigate to Telegram link and starts the bot without manual approval.
2. The server creates an isolated synthetic workspace and preserves progress on return.
3. The judge reviews evidence, replies naturally in text, confirms the Azure-interpreted proposal, and sees simulated processing continue.
4. A secure Telegram dashboard link opens the same judge's cases and decisions.

The existing `shared-f2-demo` session must be replaced for this mode. Add private-chat demo enrollment, per-judge ownership checks, bounded enrollment/model usage, and single-use expiring dashboard links exchanged for HttpOnly Secure sessions. Protect links against replay and token leakage. Disable reset/advance/fault routes server-side and remove their UI controls; no judge-facing reset is required. Never expose EVAL or real operational data.

Label this mode “Synthetic shipping cases and simulated processing; live Azure-hosted AI interpretation.” Public enrollment must not become authorization to the integrated application. These additions gate public-demo release, not a private team deployment.

## Azure readiness gate

Before provisioning, record these facts without secrets:

- Remaining credit (subscription Active and Owner role already verified).
- Required provider registrations and any additional resource-specific permissions.
- Available VM quota/SKU within the verified allowed-region policy.
- Azure model name/version, deployment type, supported API, quota and available capacity.
- Estimated VM, managed disk, public IP, inference and logging costs for the planned hosting period, including judging access.
- DNS/TLS approach and data directory/backup location.

A missing model quota is a blocker for the requested Azure-hosted AI capability, even if the VM is deployable. Do not silently fall back to Copilot or another non-Azure provider.

## Cost and timing

The user's stated credit is USD100; the actual remaining balance is unverified. No exact total can responsibly be quoted until a region, VM SKU and model are selected. Estimate:

`VM hourly price × running hours + disk + public IP + model tokens + network/logging`.

Use pay-as-you-go model inference, bounded output and application rate limits for the initial prototype. Configure budget alerts, remembering that alerts do not themselves stop spending. Plan costs separately for the interaction host, PRD 1 infrastructure and public-demo mode; logically separate environments do not necessarily require separate VMs. Leave the required services running throughout their agreed availability period. Deallocating a VM can stop compute billing, but disks and other retained resources may still cost money.

The one-hour objective applies to the initial hosting step after prerequisites and required fixes pass. It is not a promise for backend integration or all public-demo development. Azure provider support gates the Azure AI requirement; per-judge isolation separately gates public enrollment.

## Rollout stages and acceptance

### Stage 1 — Host the current application

Complete provider/quota preparation and select resources/costs. Checkpoint the branch while preserving V1 work. Configure Azure interpretation, Linux paths, persistent storage, HTTPS and supervised startup. Run Node tests/build, relevant browser tests and Hermes interpretation tests before releasing the committed application.

Acceptance: an authorized team user can use Telegram and the matching dashboard with all laptop terminals stopped, inspect evidence, confirm a decision against the simulator and see its updated state. Verify a restart preserves state, one polling consumer resumes, and AI failure leaves work pending. Record the deployed release and operating instructions. Stop the corresponding local bot consumer before cloud startup.

### Stage 2 — Connect the real backend

Agree contract version, service identity, user mapping, document access, notification marking and decision response semantics with the backend team. Implement the adapters, configure authenticated HTTPS to their deployment, and test in an integrated environment. PRD 1 retains responsibility for its worker startup, durable business storage and processing health.

Acceptance: real backend cases appear in both channels; authorized evidence loads; confirmed decisions receive contract-compliant acceptance; backend processing resumes and refreshed state agrees across interfaces. Stale/concurrent decisions and backend outages behave correctly. No synthetic fallback masks integration failure. Promote only after the merge guide's tests pass.

### Public-demo release — parallel to backend integration

Once Stage 1 is stable, enable the isolated public-demo mode after its enrollment and security tests pass. This work can proceed while Stage 2 waits for the backend. Test two independent judge accounts, returning sessions, inaccessible foreign case/document IDs, replayed links and unavailable model behavior. Use a separate bot identity if both modes run concurrently.

### Ongoing releases and operations

Pin deployed commits and runtime versions. Keep environment-specific configuration and secrets outside Git. Check health/readiness and logs after each release; monitor process restarts, polling errors, backend timeouts, inference failures and cost. Back up persistent state before incompatible changes and retain the previous release for rollback. Update the merge guide's release record with URLs, resource names, model deployment, configuration locations and test evidence, never secret values.

Voice stays disabled and must not require Twilio credentials, a tunnel, a voice port or handset testing for this release.

## Backend integration boundary

Hosting this frontend separately does not prevent integration. Both deployments communicate through authenticated HTTPS APIs. Keep a same-origin browser-facing adapter/proxy and a server-side interaction adapter so backend credentials do not reach browsers. Preserve the standalone synthetic demo as a separate configuration and dataset. A future endpoint change is only the final configuration step after schema, identity, evidence and workflow semantics are verified.

No new backend business truth model is proposed. Any actual wire-schema incompatibility must be resolved through the authoritative Shared Contract and coordinated team review.

## Sources and limits

- [Azure for Students](https://azure.microsoft.com/en-us/free/students): offer information, not account-specific entitlement verification.
- [Azure model quota management](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/quota) and [current quotas and limits](https://learn.microsoft.com/en-us/azure/foundry/openai/quotas-limits): model/deployment availability needs subscription-specific checks.
- [Linux VM pricing](https://azure.microsoft.com/en-us/pricing/details/virtual-machines/linux/): select region/SKU before quoting cost.
- [Container Apps storage](https://learn.microsoft.com/en-us/azure/container-apps/storage-mounts): persistent storage must be configured explicitly.
- [Hermes Azure Foundry guide](https://hermes-agent.nousresearch.com/docs/guides/azure-foundry): current documentation does not prove support in this repository's pinned runtime.

This review did not deploy resources, run a cloud smoke test or establish full organizer compliance. Live backend extraction/comparison remains PRD 1 work.
