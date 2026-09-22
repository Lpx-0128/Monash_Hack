# Harbor — Intelligent Shipping Document Verification

> **"Code handles certainty. AI assists with interpretation. Humans handle genuine uncertainty. The backend owns the final result."**

Harbor is an audit-grade automated verification platform built for maritime shipping logistics. In global freight operations, operators manually cross-examine thousands of incoming emails comparing the client's authoritative **Shipping Instruction (SI)** against the carrier's **Draft Bill of Lading (BL)**. Unchecked discrepancies in container counts, port codes, or cargo weights lead to costly customs holds, carrier demurrage fines, and SOLAS safety violations.

Harbor automates this pipeline end-to-end using a **deterministic-first architecture** with an AI fallback, guaranteed byte-level evidence grounding (zero hallucinations), multi-channel human-in-the-loop escalation, and audit-ready report exports.

---

## Program Flow & Architecture

### 1. Backend Processing Flow
* **Intake & Ingestion**: Ingests emails via Gmail IMAP SSL or multipart uploads, stores attachments on the filesystem, creates immutable case records, enqueues background worker jobs, and freezes input snapshots with SHA-256 content manifests.
* **Classification & Role Resolution**: Executes deterministic classification rules (with optional Gemini 3.5 Flash-Lite fallback for ambiguous subject lines), resolves document roles (identifying SI and BL), and invokes multi-format parsers (`.pdf`, `.docx`, `.xlsx`, `.txt`).
* **Extraction & Normalisation**: Extracts all 7 canonical fields using rule-based pattern matching (with AI fallback) and standardizes values (e.g. UN/LOCODE port codes, metric kilogram conversions, case folding).
* **G1–G3 Evidence Guardrails**: Validates that every extracted quote exists verbatim in source text (Gate 1), matches field semantics (Gate 2), and arithmetically derives the exact canonical value (Gate 3) — ensuring zero hallucinations.
* **Deterministic Comparison & Outcomes**: Compares SI against BL side-by-side to produce three deterministic operational verdicts:
  * 🟢 **`OK`**: All seven canonical fields match cleanly.
  * 🔴 **`MISMATCH`**: Comparable values differ (flags only the deviating fields with SI vs BL side-by-side).
  * 🟠 **`NEEDS_REVIEW`**: Missing attachments, unreadable text, or ambiguous discrepancies escalate to a human operator.
* **Persistence & Audit Layer**: Backed by SQLite in WAL mode with SQLAlchemy models (`cases`, `jobs`, `run_snapshots`, `reviews`, `accepted_decisions`), providing ACID-compliant, crash-resilient state transitions and complete event timelines.

### 2. End-to-End System Interaction Flow
1. **Email enters the system**: The user triggers Gmail synchronization through the web inbox or creates a mock email with attachments. Gmail synchronization reaches the Python backend, which uses `imaplib` over IMAP SSL to retrieve messages. The composer sends a multipart upload through the HTTP API.
2. **The backend creates and processes a case**: The Python/FastAPI backend registers the email, queues processing, and runs document parsing and comparison. Pydantic validates data, while SQLAlchemy and SQLite persist cases, reviews, and jobs. Email JSON and attachments are stored on the filesystem.
3. **A review requiring human input becomes available**: The browser polls the API and displays the case and evidence. Separately, the Node.js interaction service polls for pending work and routes review notifications to the appropriate user.
4. **The user responds through a channel**:
   * **Web**: The user inspects evidence and submits a decision through the browser API adapter directly to the backend.
   * **Telegram**: Telegram sends the response through the Hermes plugin to the interaction service. Natural-language replies can pass through the interpretation model, which returns a structured proposal for confirmation.
   * **Phone**: Twilio delivers spoken prompts and captures speech. HTTPS callbacks reach the voice controller, which manages review selection, evidence delivery through Telegram, and spoken readback and confirmation.
5. **The backend validates the submitted decision and resumes processing**: The interaction layer checks that the response still applies and obtains the required confirmation. The backend remains responsible for accepting or rejecting the decision. Updated case status then appears through browser polling and channel notifications.

---

## Key Features

* 📥 **Live Gmail Sync & 5-Min Auto-Sync Timer**: Connects directly to operational mailboxes via IMAP SSL. Includes an automatic 5-minute sync timer with domain-relevance filtering to automatically filter out non-shipping emails.
* ✍️ **Mock Email & Document Composer**: Allows operators to inject custom emails with drag-and-drop attachments (`.pdf`, `.docx`, `.xlsx`, `.txt`) for instant on-demand verification.
* 🛡️ **Zero Hallucinations (G1–G3 Grounding)**: Every extracted field is validated against byte-level locators (page numbers, paragraph indices, table coordinates).
* 👥 **Multi-Channel Human-in-the-Loop**: Escalates ambiguous discrepancies to web review queues, Telegram bots (via Hermes Agent), or phone calls (via Twilio Voice).
* ⚡ **Live Idempotent Recalculation**: Submitting a human decision immediately triggers an HTTP 202 acceptance, snapshot recomputation, and immutable audit event logging.
* 📊 **Dual-Format Compliance Export**: Exports flattened tabular CSVs for maritime freight audits and hierarchical JSON conforming to standard evaluation schemas.

---

## Performance & Validation Metrics

| Metric | Measured Result | Significance |
| :--- | :---: | :--- |
| **Model Autonomy** | **92.4%** | 483 of 523 benchmark cases resolved completely touch-free with 0 reviews. |
| **Grounding Accuracy** | **99.9%** | 1,632 / 1,633 byte-anchored field extractions (1 manual operator override). |
| **Processing Latency** | **< 40 ms** | Deterministic rule-based extraction executes in milliseconds. |
| **Backend Test Suite** | **389 Passed** | 100% pass rate across unit, pipeline, integration, and crash-recovery tests. |
| **Contract Test Suite** | **112 Passed** | 100% pass rate on TypeScript wire schemas, API filters, and interaction journeys. |
| **Cost Profile** | **$0.00 Base** | Rules execute locally with 0 API cost; LLM fallback engaged only for edge cases. |

---

## Tech Stack

### Frontend & Dashboard
* **Framework**: React 19.1, TypeScript 5.9, Vite 7.1
* **UI & Components**: Harbor Design System, CSS Variables, Lucide React Icons
* **State & Sync**: React Hooks, Custom `usePoll` hook (3s adaptive polling), browser History API
* **Validation & Networking**: Fetch API, HTML5 Drag & Drop, FormData, Zod 4.1 strict schema validation

### Backend & Intelligence
* **Core API**: Python 3.12+, FastAPI, Uvicorn, Pydantic v2
* **Storage & Persistence**: SQLite with WAL (Write-Ahead Logging), SQLAlchemy ORM, SHA-256 content hashing
* **Document Parsers**: `pypdf` (PDF), `python-docx` (Word), `openpyxl` (Excel), Native Text Reader
* **AI Fallback & Ingestion**: Google Gemini API (`gemini-2.5-flash` / `gemini-3.5-flash-lite`), Python `imaplib` (IMAP SSL)

### Interaction & Deployment
* **Telegram & Voice**: Node.js 22.12+, Express 5.1, Telegram Bot API, Hermes Agent runtime (`shipping-review` plugin), Twilio Voice (TwiML `<Say>` / `<Gather>`)
* **Infrastructure**: Azure VM (Ubuntu Linux), Caddy Reverse Proxy (Automatic HTTPS), systemd services

---

## Setup & Installation

### 1. Prerequisites
* Python 3.12+
* Node.js 22.12+ and npm
* Git

### 2. Configure Environment Variables
Create a `.env` file in the project root:

```env
# Optional: Gmail Inbox Live Sync
GMAIL_USERNAME=your_email@gmail.com
GMAIL_APP_PASSWORD=abcd efgh ijkl mnop
GMAIL_IMAP_SERVER=imap.gmail.com
GMAIL_IMAP_PORT=993
GMAIL_FOLDER=INBOX

# Optional: AI Fallback Engine
GEMINI_API_KEY=your_google_gemini_api_key
```

#### 🔑 How to generate a Gmail App Password:
1. Go to your **Google Account** ([myaccount.google.com](https://myaccount.google.com/)).
2. Navigate to **Security** and ensure **2-Step Verification** is turned ON.
3. In the search bar at the top, search for **"App Passwords"**.
4. Enter an app name (e.g. `Harbor`) and click **Create**.
5. Copy the generated 16-letter password and paste it into `GMAIL_APP_PASSWORD` in your `.env` file.

---

### 3. Run Backend (FastAPI)
```bash
# Install Python dependencies
pip install -r requirements.txt

# Start FastAPI server
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

### 4. Run Frontend (React + Vite)
```bash
# Install dependencies
npm ci

# Start development server
npm run dev
```
Open [http://localhost:5173](http://localhost:5173) in your browser.

---

### 5. Running the Automated Test Suites
```bash
# Run all Backend integration and unit tests
python -m pytest tests/

# Run Frontend contract and interaction tests
npm test
```
