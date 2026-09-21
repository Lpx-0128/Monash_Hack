"""Tests for Gmail IMAP connector and sync endpoints."""

import email.message
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from backend.inbox import GmailConfig, GmailConnector
from backend.inbox.gmail import _decode_header_str, _sanitize_filename, _extract_body_and_attachments
from backend.main import app
from backend.database import SessionLocal
from backend import crud


def test_sanitize_filename():
    assert _sanitize_filename("valid_file.pdf") == "valid_file.pdf"
    assert _sanitize_filename("../../etc/passwd") == "passwd"
    assert _sanitize_filename(".hidden") == "attachment_hidden"
    assert _sanitize_filename("spaces in name (1).docx") == "spaces_in_name__1_.docx"


def test_decode_header_str():
    assert _decode_header_str("Simple Header") == "Simple Header"
    assert _decode_header_str("=?utf-8?B?U2hpcHBpbmcgSW5zdHJ1Y3Rpb24=?=") == "Shipping Instruction"
    assert _decode_header_str(None) == ""


def test_extract_body_and_attachments():
    msg = MIMEMultipart()
    msg["Subject"] = "Test Subject"
    msg["From"] = "sender@example.com"

    text_part = MIMEText("Hello, this is the email body.", "plain", "utf-8")
    msg.attach(text_part)

    att_part = MIMEApplication(b"Mock Attachment Content", Name="document.pdf")
    att_part["Content-Disposition"] = 'attachment; filename="document.pdf"'
    msg.attach(att_part)

    body, attachments = _extract_body_and_attachments(msg)
    assert "Hello, this is the email body." in body
    assert len(attachments) == 1
    assert attachments[0][0] == "document.pdf"
    assert attachments[0][1] == b"Mock Attachment Content"


def test_gmail_connector_unconfigured():
    config = GmailConfig(username="", app_password="")
    assert not config.is_configured

    connector = GmailConnector(config=config)
    res = connector.test_connection()
    assert res["configured"] is False
    assert res["connected"] is False

    with pytest.raises(RuntimeError, match="not configured"):
        connector.fetch_unread()


def test_gmail_connector_mocked_fetch(tmp_path):
    config = GmailConfig(
        username="test@gmail.com",
        app_password="test-app-password-1234",
    )
    connector = GmailConnector(config=config, demo_root=tmp_path)

    # Build raw RFC 822 email bytes
    msg = MIMEMultipart()
    msg["Subject"] = "SHIPPING INSTRUCTION FOR CHECKING"
    msg["From"] = "carrier@freight.com"
    msg["Date"] = "Mon, 21 Sep 2026 10:00:00 +0000"

    text_part = MIMEText("Please verify the attached shipping instruction.", "plain", "utf-8")
    msg.attach(text_part)

    att_part = MIMEApplication(b"SHIPPING INSTRUCTION\nSHIPPER: TEST CORP", Name="si_doc.txt")
    att_part["Content-Disposition"] = 'attachment; filename="si_doc.txt"'
    msg.attach(att_part)

    raw_bytes = msg.as_bytes()

    # Mock IMAP4_SSL
    mock_imap = MagicMock()
    mock_imap.__enter__.return_value = mock_imap
    mock_imap.login.return_value = ("OK", [b"Logged in"])
    mock_imap.select.return_value = ("OK", [b"1"])
    mock_imap.search.return_value = ("OK", [b"1"])
    mock_imap.fetch.return_value = ("OK", [(b"1 (RFC822 {100}", raw_bytes), b")"])
    mock_imap.store.return_value = ("OK", [b"Flags updated"])

    with patch("imaplib.IMAP4_SSL", return_value=mock_imap):
        records = connector.fetch_unread(limit=5)
        assert len(records) == 1
        rec = records[0]
        assert rec["subject"] == "SHIPPING INSTRUCTION FOR CHECKING"
        assert rec["from"] == "carrier@freight.com"
        assert len(rec["attachments"]) == 1
        assert (tmp_path / "inbox" / f"{rec['email_id']}.json").exists()


def test_gmail_relevance_filtering(tmp_path):
    config = GmailConfig(
        username="test@gmail.com",
        app_password="test-app-password-1234",
    )
    connector = GmailConnector(config=config, demo_root=tmp_path)

    # 1. Shipping Relevant Email
    msg_ship = MIMEMultipart()
    msg_ship["Subject"] = "Draft BL and Shipping Instructions - VOYAGE 2026"
    msg_ship["From"] = "ops@oceanfreight.com"
    msg_ship.attach(MIMEText("Please verify the attached draft B/L against SI.", "plain", "utf-8"))
    msg_ship.attach(MIMEApplication(b"DRAFT BL CONTENT", Name="draft_bl.pdf"))

    # 2. Irrelevant Personal Email
    msg_personal = MIMEMultipart()
    msg_personal["Subject"] = "Dinner plans for Friday night"
    msg_personal["From"] = "friend@gmail.com"
    msg_personal.attach(MIMEText("Hey, let me know if we are still going to that restaurant.", "plain", "utf-8"))

    # 3. Spam / Marketing Email
    msg_spam = MIMEMultipart()
    msg_spam["Subject"] = "Claim your 50% discount on web hosting today!"
    msg_spam["From"] = "promotions@hostingservice.com"
    msg_spam.attach(MIMEText("Click here to claim your limited-time offer now!", "plain", "utf-8"))

    # 4. Third-party Automated Alert
    msg_alert = MIMEMultipart()
    msg_alert["Subject"] = "Security alert: New login detected"
    msg_alert["From"] = "no-reply@accounts.google.com"
    msg_alert.attach(MIMEText("A new device just signed in to your account.", "plain", "utf-8"))

    raw_ship = msg_ship.as_bytes()
    raw_personal = msg_personal.as_bytes()
    raw_spam = msg_spam.as_bytes()
    raw_alert = msg_alert.as_bytes()

    fetch_map = {
        b"1": [(b"1 (RFC822 {100}", raw_ship), b")"],
        b"2": [(b"2 (RFC822 {100}", raw_personal), b")"],
        b"3": [(b"3 (RFC822 {100}", raw_spam), b")"],
        b"4": [(b"4 (RFC822 {100}", raw_alert), b")"],
    }

    mock_imap = MagicMock()
    mock_imap.__enter__.return_value = mock_imap
    mock_imap.login.return_value = ("OK", [b"Logged in"])
    mock_imap.select.return_value = ("OK", [b"1"])
    mock_imap.search.return_value = ("OK", [b"1 2 3 4"])
    mock_imap.fetch.side_effect = lambda num, query: ("OK", fetch_map[num])
    mock_imap.store.return_value = ("OK", [b"Flags updated"])

    with patch("imaplib.IMAP4_SSL", return_value=mock_imap):
        records = connector.fetch_unread(limit=10)
        # Only the shipping email should be fetched
        assert len(records) == 1
        assert records[0]["subject"] == "Draft BL and Shipping Instructions - VOYAGE 2026"
        assert connector._last_skipped_count == 3
        # All 4 emails should be marked as seen on IMAP so they don't block subsequent syncs
        assert mock_imap.store.call_count == 4


def test_gmail_api_status_endpoint():
    client = TestClient(app)
    resp = client.get("/api/v1/inbox/gmail/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "configured" in data
    assert "connected" in data


def test_gmail_api_sync_unconfigured():
    client = TestClient(app)
    # Without credentials in env or body, should return 400
    with patch.dict("os.environ", {"GMAIL_USERNAME": "", "GMAIL_APP_PASSWORD": ""}):
        resp = client.post("/api/v1/inbox/gmail/sync", json={})
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "INVALID_VALUE"


def test_gmail_api_clear_endpoint():
    client = TestClient(app)
    resp = client.post("/api/v1/inbox/gmail/clear")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "OK"
    assert "deleted_count" in data


