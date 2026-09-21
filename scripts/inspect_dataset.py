"""Validate the organiser archive without executing its loader or extracting paths.

Usage: python scripts/inspect_dataset.py archive.zip output-directory
The output contains private source emails; keep it outside Git and the public web root.
"""
import collections
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
import zipfile


def inspect(archive, destination):
    archive, destination = Path(archive), Path(destination)
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate archive entries")
        for entry in bundle.infolist():
            path = PurePosixPath(entry.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in entry.filename or ":" in entry.filename:
                raise ValueError("Unsafe archive path")
            if entry.file_size > 20_000_000:
                raise ValueError("Oversized archive entry")
        if sum(e.file_size for e in bundle.infolist()) > 100_000_000:
            raise ValueError("Oversized dataset")
        emails = []
        for name in sorted(names):
            if not name.startswith("inbox/") or not name.endswith(".json"):
                continue
            email = json.loads(bundle.read(name))
            if set(email) != {"email_id", "from", "subject", "body", "attachments"}:
                raise ValueError("Unexpected email schema")
            if not all(isinstance(email[k], str) for k in ("email_id", "from", "subject", "body")):
                raise ValueError("Invalid email text")
            if not isinstance(email["attachments"], list):
                raise ValueError("Invalid attachment list")
            for attachment in email["attachments"]:
                if not isinstance(attachment, str) or not attachment.startswith("attachments/") or attachment not in names:
                    raise ValueError("Missing attachment")
            emails.append(email)
        ids = [e["email_id"] for e in emails]
        if len(ids) != len(set(ids)) or not ids:
            raise ValueError("Missing or duplicate email IDs")
        attachments = [n for n in names if n.startswith("attachments/") and not n.endswith("/")]
        report = {
            "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "email_count": len(emails),
            "attachment_count": len(attachments),
            "attachment_types": dict(sorted(collections.Counter(PurePosixPath(n).suffix for n in attachments).items())),
            "emails_by_attachment_count": dict(sorted(collections.Counter(len(e["attachments"]) for e in emails).items())),
            "ground_truth_available": False,
            "sample_submission_is_ground_truth": False,
            "review_count": None,
        }
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "emails.json").write_text(json.dumps(emails, ensure_ascii=False, indent=2), encoding="utf-8")
        (destination / "inspection.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return report


if __name__ == "__main__":
    inspect(*sys.argv[1:])
