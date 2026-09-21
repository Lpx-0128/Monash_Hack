"""Gmail IMAP Inbox Connector.

Connects to Gmail via IMAP SSL using Gmail App Passwords.
Fetches unread emails, extracts text/html body and attachments,
stores them into the DEMO inbox registry, and registers cases for verification.
"""

from __future__ import annotations

import email
import email.header
import email.utils
import imaplib
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence
from sqlalchemy.orm import Session

from backend import crud, schemas

logger = logging.getLogger(__name__)


# --- Shipping & Freight Logistics Domain Relevance Rules ---

_SHIPPING_KEYWORDS = re.compile(
    r"\b(?:"
    # B/L and Shipping Instructions
    r"bill\s+of\s+lading|b/?l\b|shipping\s+instructions?|s/?i\b|draft\s+b/?l|final\s+b/?l"
    r"|seaway\s+bill|air\s*waybill|awb\b|booking\s*(?:confirmation|advice|no|ref|number)"
    # Freight, Cargo, Vessel & Voyage
    r"|ocean\s+freight|freight|vessel|voyage|feeder|container|fcl|lcl|teu|feu"
    r"|twenty[- ]foot|forty[- ]foot|40\s*h[cq]|20\s*gp|gross\s+weight|tare\s+weight|cbm\b|measurement"
    # Parties & Ports
    r"|port\s+of\s+loading|port\s+of\s+discharge|pol\b|pod\b|place\s+of\s+delivery|place\s+of\s+receipt"
    r"|shipper|consignee|notify\s+party|consignor|carrier|forwarder|freight\s+forwarder"
    # Documents & Customs
    r"|packing\s+list|commercial\s+invoice|customs\s+(?:clearance|declaration|entry|manifest)"
    r"|cargo\s+manifest|demurrage|detention|discrepanc\w+|seal\s+no|container\s+no"
    r"|hs\s*code|commodity|shipping\s+order|mate['’]?s\s+receipt|cargo\s+release"
    # Carriers & Shipping Lines
    r"|maersk|msc|cma\s*cgm|cosco|hapag[- ]lloyd|ocean\s+network\s+express|\bone\s+line\b|evergreen|yang\s+ming|oocl|zim|wan\s+hai|pil|hmt"
    r")",
    re.IGNORECASE,
)

_ATTACHMENT_SHIPPING_HINTS = re.compile(
    r"(?:"
    r"\b(?:si|bl|b_l|b-l|draft|bill|lading|instruction|shipping|invoice|packing|manifest|booking|vessel|freight|cargo|container|customs)\b"
    r"|shipping[-_ ]instruction"
    r"|bill[-_ ]of[-_ ]lading"
    r"|draft[-_ ]bl"
    r")",
    re.IGNORECASE,
)

_KNOWN_IRRELEVANT_SENDERS = re.compile(
    r"(?:"
    r"noreply|no-reply|notifications?@|alerts?@|newsletter@|marketing@|promotions?@"
    r"|google\.com|apple\.com|amazon\.|netflix\.com|spotify\.com|linkedin\.com"
    r"|facebookmail\.com|twitter\.com|x\.com|github\.com|uber\.com|paypal\.com"
    r"|grab\.com|foodpanda|doordash|stripe\.com|slack\.com|atlassian\.com"
    r")",
    re.IGNORECASE,
)

_KNOWN_IRRELEVANT_SUBJECTS = re.compile(
    r"(?:"
    r"security\s+alert|password\s+reset|verify\s+your\s+email|verification\s+code"
    r"|two-factor|2fa|login\s+attempt|sign-in|new\s+login"
    r"|your\s+order\s+(?:has\s+been|is\s+confirmed|receipt)|receipt\s+for\s+your"
    r"|subscription\s+(?:confirmed|renewed|cancelled)|statement\s+ready"
    r"|welcome\s+to\b|friend\s+request|invitation\s+to\s+connect"
    r"|weekly\s+digest|newsletter|daily\s+summary"
    r")",
    re.IGNORECASE,
)


def is_shipping_email_relevant(
    from_addr: str,
    subject: str,
    body: str,
    attachment_filenames: Sequence[str] = (),
) -> tuple[bool, str]:
    """Determine whether an incoming email is relevant to shipping / BL-SI verification."""
    from backend.intelligence import classification

    text_to_check = f"{subject}\n{body}"

    # 1. Spam & Phishing filtering
    spam_match = classification._SPAM.search(text_to_check)
    if spam_match:
        return False, f"Unsolicited promotional / spam content ({spam_match.group(0)})"

    # 2. Automated service / system notification filtering (unless containing explicit shipping doc keywords)
    if _KNOWN_IRRELEVANT_SENDERS.search(from_addr) or _KNOWN_IRRELEVANT_SUBJECTS.search(subject):
        if not _SHIPPING_KEYWORDS.search(text_to_check) and not any(_ATTACHMENT_SHIPPING_HINTS.search(f) for f in attachment_filenames):
            return False, "Automated third-party service / non-shipping notification"

    # 3. Structured classification check
    view = classification.build_view(subject=subject, body=body)
    rule_res = classification.classify_rules(view)
    if rule_res.category in ("BL_COMPARISON", "SI_REQUEST", "INVOICE_QUERY"):
        return True, f"Matched shipping intent: {rule_res.category}"
    if rule_res.category == "GENERAL":
        return True, "Matched operational maritime / shipping traffic"

    # 4. Domain keyword match in subject or body
    ship_kw = _SHIPPING_KEYWORDS.search(text_to_check)
    if ship_kw:
        return True, f"Contains shipping domain keyword ({ship_kw.group(0)})"

    # 5. Attachment inspection
    for filename in attachment_filenames:
        if _ATTACHMENT_SHIPPING_HINTS.search(filename):
            return True, f"Contains shipping document attachment: {filename}"

    # 6. Attachment with shipment context words
    has_doc_attachments = any(
        filename.lower().endswith((".pdf", ".docx", ".xlsx", ".txt", ".csv"))
        for filename in attachment_filenames
    )
    if has_doc_attachments and re.search(r"\b(?:shipment|cargo|goods|docs|check\s+docs|attached\s+docs)\b", text_to_check, re.IGNORECASE):
        return True, "Document attachment with shipment reference"

    return False, "No shipping, freight, B/L, or SI relevance detected"


def _decode_header_str(val: Optional[str]) -> str:
    """Decode RFC 2047 encoded email headers into unicode string."""
    if not val:
        return ""
    decoded_fragments = email.header.decode_header(val)
    parts = []
    for content, encoding in decoded_fragments:
        if isinstance(content, bytes):
            enc = encoding or "utf-8"
            try:
                parts.append(content.decode(enc, errors="replace"))
            except (LookupError, UnicodeDecodeError):
                parts.append(content.decode("utf-8", errors="replace"))
        else:
            parts.append(str(content))
    return "".join(parts).strip()


def _sanitize_filename(name: str) -> str:
    """Sanitize attachment filenames to prevent path traversal and unsafe characters."""
    clean = Path(name).name
    # Replace dangerous characters with underscore
    clean = re.sub(r'[^a-zA-Z0-9_.-]', '_', clean)
    if not clean or clean.startswith('.'):
        clean = f"attachment_{clean.lstrip('.')}"
    return clean


def _extract_body_and_attachments(msg: email.message.Message) -> tuple[str, list[tuple[str, bytes]]]:
    """Extract plain text / html body and list of (filename, bytes) attachments."""
    text_parts = []
    html_parts = []
    attachments: list[tuple[str, bytes]] = []

    if msg.is_multipart():
        for part in msg.walk():
            content_disposition = str(part.get("Content-Disposition", ""))
            content_type = part.get_content_type()
            filename = part.get_filename()

            if filename:
                filename = _decode_header_str(filename)

            # Check if this part is an attachment
            is_attachment = "attachment" in content_disposition.lower() or bool(filename)
            if is_attachment and filename:
                payload = part.get_payload(decode=True)
                if payload:
                    attachments.append((filename, payload))
            elif content_type == "text/plain" and not is_attachment:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        text_parts.append(payload.decode(charset, errors="replace"))
                    except LookupError:
                        text_parts.append(payload.decode("utf-8", errors="replace"))
            elif content_type == "text/html" and not is_attachment:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        html_parts.append(payload.decode(charset, errors="replace"))
                    except LookupError:
                        html_parts.append(payload.decode("utf-8", errors="replace"))
    else:
        payload = msg.get_payload(decode=True)
        content_type = msg.get_content_type()
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            try:
                decoded = payload.decode(charset, errors="replace")
            except LookupError:
                decoded = payload.decode("utf-8", errors="replace")
            if content_type == "text/html":
                html_parts.append(decoded)
            else:
                text_parts.append(decoded)

    # Prefer plain text, fallback to html (strip basic tags if only html)
    if text_parts:
        body = "\n\n".join(text_parts).strip()
    elif html_parts:
        # Basic tag stripping for clean plain-text representation
        raw_html = "\n\n".join(html_parts)
        body = re.sub(r'<[^>]+>', ' ', raw_html)
        body = re.sub(r'\s+', ' ', body).strip()
    else:
        body = ""

    return body, attachments


@dataclass(frozen=True)
class GmailConfig:
    username: str = ""
    app_password: str = ""
    imap_server: str = "imap.gmail.com"
    imap_port: int = 993
    folder: str = "INBOX"
    mark_as_read: bool = True

    @classmethod
    def from_env(cls) -> GmailConfig:
        return cls(
            username=os.environ.get("GMAIL_USERNAME", "").strip(),
            app_password=os.environ.get("GMAIL_APP_PASSWORD", "").strip(),
            imap_server=os.environ.get("GMAIL_IMAP_SERVER", "imap.gmail.com").strip(),
            imap_port=int(os.environ.get("GMAIL_IMAP_PORT", "993").strip()),
            folder=os.environ.get("GMAIL_FOLDER", "INBOX").strip(),
            mark_as_read=os.environ.get("GMAIL_MARK_AS_READ", "true").lower() in ("1", "true", "yes"),
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.username and self.app_password)


class GmailConnector:
    """Manages secure IMAP SSL communication with Gmail."""

    def __init__(self, config: Optional[GmailConfig] = None, *, demo_root: Optional[Path] = None):
        self.config = config or GmailConfig.from_env()
        if demo_root is None:
            demo_env = os.environ.get("INTELLIGENCE_DEMO_SOURCE_ROOT")
            if demo_env:
                self.demo_root = Path(demo_env).resolve()
            else:
                repo_root = Path(__file__).resolve().parent.parent.parent
                self.demo_root = repo_root / "resources" / "demo-fixtures"
        else:
            self.demo_root = Path(demo_root).resolve()

        self.inbox_dir = self.demo_root / "inbox"
        self.attachments_dir = self.demo_root / "attachments"
        self._last_skipped_count = 0

    def _ensure_dirs(self) -> None:
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.attachments_dir.mkdir(parents=True, exist_ok=True)

    def test_connection(self) -> dict[str, Any]:
        """Verify IMAP credentials and return unseen message count."""
        if not self.config.is_configured:
            return {
                "configured": False,
                "connected": False,
                "error": "GMAIL_USERNAME or GMAIL_APP_PASSWORD is not set"
            }
        try:
            with imaplib.IMAP4_SSL(self.config.imap_server, self.config.imap_port) as mail:
                mail.login(self.config.username, self.config.app_password)
                status, _ = mail.select(self.config.folder, readonly=True)
                if status != "OK":
                    return {"configured": True, "connected": False, "error": f"Failed to select folder {self.config.folder}"}
                status, search_data = mail.search(None, "UNSEEN")
                unseen_ids = search_data[0].split() if (status == "OK" and search_data and search_data[0]) else []
                return {
                    "configured": True,
                    "connected": True,
                    "folder": self.config.folder,
                    "unseen_count": len(unseen_ids),
                }
        except Exception as exc:
            return {"configured": True, "connected": False, "error": str(exc)}

    def fetch_unread(self, limit: int = 20) -> list[dict[str, Any]]:
        """Fetch up to `limit` unread shipping-relevant emails from Gmail, save to demo storage, and return metadata."""
        if not self.config.is_configured:
            raise RuntimeError("Gmail connector is not configured with username and app password.")

        self._ensure_dirs()
        fetched_records: list[dict[str, Any]] = []
        skipped_irrelevant = 0

        with imaplib.IMAP4_SSL(self.config.imap_server, self.config.imap_port) as mail:
            mail.login(self.config.username, self.config.app_password)
            status, _ = mail.select(self.config.folder, readonly=False)
            if status != "OK":
                raise RuntimeError(f"Could not select folder {self.config.folder}")

            status, search_data = mail.search(None, "UNSEEN")
            if status != "OK" or not search_data or not search_data[0]:
                self._last_skipped_count = 0
                return []

            email_nums = search_data[0].split()
            # Process unread emails up to limit
            to_process = email_nums[:limit]

            for msg_num in to_process:
                status, fetch_data = mail.fetch(msg_num, "(RFC822)")
                if status != "OK" or not fetch_data:
                    continue

                raw_bytes = None
                for part in fetch_data:
                    if isinstance(part, tuple) and len(part) >= 2:
                        raw_bytes = part[1]
                        break

                if not raw_bytes:
                    continue

                msg = email.message_from_bytes(raw_bytes)
                subject = _decode_header_str(msg.get("Subject", "No Subject"))
                from_addr = _decode_header_str(msg.get("From", "unknown@unknown.invalid"))

                date_header = msg.get("Date")
                received_iso = None
                if date_header:
                    try:
                        parsed_dt = email.utils.parsedate_to_datetime(date_header)
                        received_iso = parsed_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    except Exception:
                        received_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

                body, attachments = _extract_body_and_attachments(msg)
                att_names = [a[0] for a in attachments]

                # Evaluate domain relevance: only ingest shipping/freight correspondence
                is_relevant, reason = is_shipping_email_relevant(from_addr, subject, body, att_names)
                if not is_relevant:
                    logger.info("Gmail Sync: Skipping non-shipping email '%s' from '%s': %s", subject, from_addr, reason)
                    if self.config.mark_as_read:
                        mail.store(msg_num, "+FLAGS", "\\Seen")
                    skipped_irrelevant += 1
                    continue

                # Generate clean unique email ID
                stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                short_id = uuid.uuid4().hex[:6]
                email_id = f"email_gmail_{stamp}_{short_id}"

                # Write attachments
                saved_attachment_paths = []
                for idx, (raw_filename, att_bytes) in enumerate(attachments):
                    safe_name = _sanitize_filename(raw_filename)
                    # Prefix with email_id to prevent name collisions
                    target_filename = f"{email_id}_{idx}_{safe_name}"
                    att_path = self.attachments_dir / target_filename
                    att_path.write_bytes(att_bytes)
                    saved_attachment_paths.append(f"attachments/{target_filename}")

                email_record = {
                    "email_id": email_id,
                    "from": from_addr,
                    "subject": subject,
                    "body": body,
                    "received_at": received_iso,
                    "attachments": saved_attachment_paths,
                }

                # Save email JSON
                json_path = self.inbox_dir / f"{email_id}.json"
                json_path.write_text(json.dumps(email_record, indent=2, ensure_ascii=False), encoding="utf-8")

                if self.config.mark_as_read:
                    mail.store(msg_num, "+FLAGS", "\\Seen")

                fetched_records.append(email_record)

        self._last_skipped_count = skipped_irrelevant
        return fetched_records

    def sync(self, db: Session, limit: int = 20, *, run_kind: schemas.RunKind = schemas.RunKind.DEMO) -> dict[str, Any]:
        """Fetch unread shipping emails, register them in the database, and enqueue worker jobs."""
        records = self.fetch_unread(limit=limit)
        created_cases = []
        for rec in records:
            eid = rec["email_id"]
            case = crud.create_case_with_job(
                db,
                email_id=eid,
                run_kind=run_kind,
                public_caller=(run_kind == schemas.RunKind.DEMO),
            )
            created_cases.append(case.case_id)

        skipped = getattr(self, "_last_skipped_count", 0)
        return {
            "status": "OK",
            "fetched": len(records),
            "created_cases": created_cases,
            "skipped_irrelevant": skipped,
        }

