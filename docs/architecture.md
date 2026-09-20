# System Architecture & Platform Design

**Version:** Contract v2.1.1-aligned  
**Owner:** Person B (Platform + Validation)

---

## 1. Overview & Philosophy

The shipping inbox verification platform automates the comparison between reference Shipping Instructions (SI) and draft Bills of Lading (BL) across 7 canonical shipping fields:
1. `shipper`
2. `consignee`
3. `notify_party`
4. `port_of_loading`
5. `port_of_discharge`
6. `container_count`
7. `gross_weight_kg`

The core product philosophy is: **"Don't monitor AI. Let it chase you."**
Shipping staff do not poll or monitor AI execution. The system processes cases automatically and contacts operators only when human judgment is needed (`CHOICE`, `VALUE_INPUT`, or `ACKNOWLEDGE`).

---

## 2. End-to-End Architecture

```mermaid
flowchart TD
    Client["Clients (Dashboard / Telegram Notifier)"]
    API["FastAPI REST Surface (/api/v1)"]
    Auth["Scope Guard (DEMO vs EVAL via X-Run-Kind)"]
    DB[("SQLite WAL Store (cases & jobs)")]
    WorkerLoop["Durable Polling Worker Loop"]
    WorkerExec["Worker Dispatch (process_case / apply_decision)"]
    Exporter["Fail-Closed EVAL Exporter"]

    Client -->|HTTP REST| API
    API --> Auth
    Auth -->|Atomic Transactions| DB
    WorkerLoop -->|Atomic CAS Lease| DB
    WorkerLoop --> WorkerExec
    WorkerExec -->|Guarded Commit (run_id)| DB
    DB --> Exporter
```

---

## 3. Dual-Status Invariant & State Transitions

Under Contract §6:
1. **Automated Machine Assessment (`machine_assessment`)**:
   - Finalized after initial extraction and deterministic comparison.
   - **Byte-for-byte immutable per run**.
   - Used exclusively for scored EVAL snapshots.
2. **Operational Resolution (`resolution`)**:
   - Tracks human operator decisions (`DOCUMENT_CONFIRMED` or `MANUAL_OVERRIDE`).
   - Updates working operational fields (`fields`).
   - Formula:
     $$\text{effective\_status} = \text{resolution.final\_status} \mathbin{??} \text{machine\_assessment.status} \mathbin{??} \text{null}$$
3. **Follow-Up Derivation (`follow_up`)**:
   - `BLOCKED_EXTERNAL` $\rightarrow$ `AWAIT_EXTERNAL`
   - `effective_status == MISMATCH` $\rightarrow$ `CORRECTION_REQUIRED`
   - Otherwise $\rightarrow$ `NONE`

---

## 4. Durable Work & Concurrency Control

```mermaid
sequenceDiagram
    participant User as Human Operator / Client
    participant API as FastAPI REST API
    participant DB as SQLite Transaction Store
    participant Loop as Background Worker Loop
    participant Worker as Worker Engine

    User->>API: POST /reviews/{id}/decision (DecisionRequest)
    Note over API: Recheck active run_id & OPEN review
    API->>DB: 1 Transaction: Close Review + Persist Decision + Enqueue Job (PENDING)
    API-->>User: 202 Accepted (Case PROCESSING)
    Loop->>DB: Atomic CAS Claim (UPDATE status='RUNNING' WHERE status='PENDING')
    Loop->>Worker: Dispatch apply_decision(case_id, run_id)
    Note over Worker: Check job_run_id == case.run.run_id (pre/post work)
    Worker->>DB: Update working fields & resolution
    Loop->>DB: Guarded completion (UPDATE status='COMPLETED' WHERE status='RUNNING')
```

### Safety Properties Guaranteed:
1. **Atomic Acceptance:** Case state mutation and job insertion occur in a single database transaction. No crash can strand a case in `PROCESSING` without an active work unit.
2. **Stale Run Protection:** Worker tasks check `job_run_id == case.run.run_id` before and after heavy processing. Reprocessing immediately supersedes old jobs, and superseded worker writes are dropped.
3. **Race Condition Immunity:** Competing decisions (e.g. concurrent Telegram and Dashboard submissions) execute compare-and-swap on `review.status == OPEN`. Exactly one wins; the second receives `409 Conflict` with `current_case`.
4. **Crash Recovery:** Abandoned `RUNNING` jobs are reset to `PENDING` on startup. Failed jobs are retried once (`MAX_ATTEMPTS=2`), then transition cleanly to `FAILED` with `PROCESSING_FAILED` events.

---

## 5. Security & Scope Boundaries

- **Public Scope (`DEMO`)**:
  - Default for unauthenticated or public callers.
  - Can only query or access cases and documents with `run_kind == DEMO` and `demo_safe == true`.
  - Supplying query parameter `?run_kind=EVAL` without credentials cannot widen scope.
- **Private Scope (`EVAL`)**:
  - Enforced on the server via `X-Run-Kind: EVAL`.
  - Public requests targeting EVAL cases return `404 NOT_FOUND` to conceal their existence.

---

## 6. Organizer Submission Exporter

The evaluation harness in [`backend/export.py`](file:///C:/Ahmad/YEAR%202%20SEM%201/monashXaveris/Monash_Hack/backend/export.py):
- Produces pure JSON mapping each email ID to category, machine status, review reason, defect flag, and defect fields.
- Verifies that all required IDs have finalized assessments. If any required ID is missing or unassessed, it **fails closed** (exit code 1).
- Generates a companion `manifest.json` containing SHA-256 content checksum and version pins.
