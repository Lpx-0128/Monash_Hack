"""Immutable input mapping, source registries and document identity (handoff §9).

Two registries are kept apart on purpose:

``participant``
    the organizer bundle. Real shipping correspondence, so its bytes are **not**
    demo-safe and are never streamed to a public DEMO caller.
``synthetic_demo``
    independently authored fixtures that exist to be shown publicly.

Nothing in this module invents a hash, a document, a role or a receipt time.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field as dc_field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping, Optional

from .config import IntelligenceConfig
from .normalization import detect_corpus_convention
from .types import SourceDataIssue

PARTICIPANT = "participant"
SYNTHETIC_DEMO = "synthetic_demo"

_MEDIA_TYPES = {
    ".txt": "text/plain",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

_ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")

# Source-reference problems that are facts about the input, not code defects.
MISSING_FILE = "MISSING_FILE"
UNSAFE_REFERENCE = "UNSAFE_REFERENCE"
OVERSIZED = "OVERSIZED"


@dataclass(frozen=True)
class SourceRef:
    """One ordered attachment reference and what is actually known about it."""

    document_id: str
    declared_path: str
    filename: str
    media_type: str
    content_hash: Optional[str]
    size_bytes: Optional[int]
    present: bool
    demo_safe: bool
    issue: Optional[str] = None
    issue_detail: str = ""


@dataclass(frozen=True)
class InputSnapshot:
    """The frozen input a run is computed from."""

    namespace: str          # run kind: DEMO or EVAL
    case_id: str
    email_id: str
    registry_kind: str
    from_address: str
    subject: str
    body: str               # private: used for classification, never put on the wire
    received_at: Optional[str]
    sources: tuple[SourceRef, ...]
    input_version: str
    demo_safe: bool

    def source_by_id(self, document_id: str) -> Optional[SourceRef]:
        for ref in self.sources:
            if ref.document_id == document_id:
                return ref
        return None

    @property
    def present_sources(self) -> tuple[SourceRef, ...]:
        return tuple(ref for ref in self.sources if ref.present)

    @property
    def missing_sources(self) -> tuple[SourceRef, ...]:
        return tuple(ref for ref in self.sources if not ref.present)


class SourceRegistry:
    """A configured, containment-checked root of immutable source files."""

    def __init__(self, kind: str, root: Path, *, demo_safe: bool,
                 declared_convention: str = ""):
        self.kind = kind
        self.root = Path(root).resolve()
        self.demo_safe = demo_safe
        self._declared_convention = declared_convention
        self._convention: Optional[str] = None

    def numeric_convention(self, *, sample_limit: int = 400) -> str:
        """The separator convention this registry's own documents establish.

        A convention declared in configuration wins. Otherwise the registry's
        text attachments are scanned once for repeated unambiguous evidence;
        with none, the result is ``""`` and a lone separator stays ambiguous.
        """
        if self._declared_convention:
            return self._declared_convention
        if self._convention is not None:
            return self._convention
        texts: list[str] = []
        attachments = self.root / "attachments"
        if attachments.is_dir():
            for path in sorted(attachments.glob("*.txt"))[:sample_limit]:
                try:
                    texts.append(path.read_text(encoding="utf-8", errors="strict"))
                except (OSError, UnicodeDecodeError):
                    continue
        self._convention = detect_corpus_convention(texts)
        return self._convention

    # -- listing -----------------------------------------------------------
    @property
    def inbox_dir(self) -> Path:
        return self.root / "inbox"

    def has_email(self, email_id: str) -> bool:
        if not _is_safe_email_id(email_id):
            return False
        return (self.inbox_dir / f"{email_id}.json").is_file()

    def email_ids(self) -> tuple[str, ...]:
        if not self.inbox_dir.is_dir():
            return ()
        return tuple(sorted(p.stem for p in self.inbox_dir.glob("email_*.json")))

    def read_email(self, email_id: str) -> dict:
        if not _is_safe_email_id(email_id):
            raise SourceDataIssue(f"unsafe email id {email_id!r}")
        path = self.inbox_dir / f"{email_id}.json"
        if not path.is_file():
            raise SourceDataIssue(f"no source record for {email_id!r} in registry {self.kind}")
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SourceDataIssue(f"source record for {email_id!r} is not readable JSON") from exc
        if not isinstance(record, dict):
            raise SourceDataIssue(f"source record for {email_id!r} is not a JSON object")
        return record

    # -- attachments -------------------------------------------------------
    def resolve(self, declared_path: str) -> Path:
        """Resolve an attachment reference inside the registry root.

        Rejects absolute paths, traversal, symlink escape and remote URLs
        *before* opening anything (handoff §9 step 3).
        """
        if not isinstance(declared_path, str) or not declared_path.strip():
            raise SourceDataIssue("attachment reference is empty")
        text = declared_path.strip()
        if "://" in text:
            raise SourceDataIssue(f"remote attachment reference is not fetched: {text!r}")
        candidate = Path(text)
        if candidate.is_absolute() or (len(text) > 1 and text[1] == ":"):
            raise SourceDataIssue(f"absolute attachment reference rejected: {text!r}")
        if ".." in candidate.parts:
            raise SourceDataIssue(f"traversing attachment reference rejected: {text!r}")
        resolved = (self.root / candidate).resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise SourceDataIssue(f"attachment reference escapes the source root: {text!r}")
        return resolved

    def read_bytes(self, declared_path: str) -> bytes:
        return self.resolve(declared_path).read_bytes()


def _is_safe_email_id(email_id: str) -> bool:
    return bool(email_id) and re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", email_id) is not None


def build_registries(config: IntelligenceConfig) -> dict:
    """The two configured registries, keyed by kind."""
    return {
        PARTICIPANT: SourceRegistry(
            PARTICIPANT, config.source_root, demo_safe=False,
            declared_convention=config.source_numeric_convention,
        ),
        SYNTHETIC_DEMO: SourceRegistry(
            SYNTHETIC_DEMO, config.demo_source_root, demo_safe=True,
            declared_convention=config.demo_numeric_convention,
        ),
    }


def find_registry(email_id: str, registries: Mapping[str, SourceRegistry]) -> Optional[SourceRegistry]:
    """Locate the registry holding ``email_id``. Demo fixtures take precedence."""
    demo = registries.get(SYNTHETIC_DEMO)
    if demo is not None and demo.has_email(email_id):
        return demo
    participant = registries.get(PARTICIPANT)
    if participant is not None and participant.has_email(email_id):
        return participant
    return None


def media_type_for(filename: str) -> str:
    return _MEDIA_TYPES.get(Path(filename).suffix.lower(), "application/octet-stream")


def _validate_received_at(record: Mapping) -> Optional[str]:
    """Return a validated receipt timestamp, or None when the source supplies none.

    A malformed non-null timestamp is rejected rather than coerced, and a receipt
    time is never inferred from quoted email history (handoff §9 step 2).
    """
    if "received_at" not in record:
        return None
    raw = record.get("received_at")
    if raw is None:
        return None
    if not isinstance(raw, str) or not _ISO_UTC.match(raw.strip()):
        raise SourceDataIssue(f"received_at is not a UTC ISO-8601 timestamp: {raw!r}")
    value = raw.strip()
    try:
        datetime.strptime(value.split(".")[0].rstrip("Z"), "%Y-%m-%dT%H:%M:%S")
    except ValueError as exc:
        raise SourceDataIssue(f"received_at is not a real timestamp: {raw!r}") from exc
    return value


def document_id_for(namespace: str, case_id: str, registry_kind: str,
                    declared_path: str, content_hash: Optional[str]) -> str:
    """An opaque document identity scoped to the case, namespace and registry.

    A filename is never a global document ID, and the same email ID in DEMO and
    EVAL produces different identities.
    """
    digest = hashlib.sha256(
        "\u0000".join([namespace, case_id, registry_kind, declared_path, content_hash or ""])
        .encode("utf-8")
    ).hexdigest()
    return f"doc_{digest[:20]}"


def compute_input_version(email_id: str, record: Mapping, sources: Iterable[SourceRef]) -> str:
    """A deterministic digest of the canonical email content and ordered sources.

    Genuinely missing references are marked, so a run that saw a missing BL has a
    different input version from one that saw it present.
    """
    canonical = {
        "email_id": email_id,
        "from": record.get("from"),
        "subject": record.get("subject"),
        "body": record.get("body"),
        "received_at": record.get("received_at"),
        "attachments": [
            {
                "path": ref.declared_path,
                "hash": ref.content_hash,
                "size": ref.size_bytes,
                "present": ref.present,
                "issue": ref.issue,
            }
            for ref in sources
        ],
    }
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "iv1_" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def ingest_case(email_id: str, *, namespace: str, case_id: str,
                registries: Mapping[str, SourceRegistry],
                config: IntelligenceConfig) -> InputSnapshot:
    """Map one registered source record into an immutable :class:`InputSnapshot`.

    Raises :class:`SourceDataIssue` when the email ID is not registered at all —
    an unregistered ID never produces a fabricated source.
    """
    registry = find_registry(email_id, registries)
    if registry is None:
        raise SourceDataIssue(f"email id {email_id!r} is not present in any configured source registry")

    record = registry.read_email(email_id)
    for key in ("email_id", "from", "subject", "body"):
        if key not in record:
            raise SourceDataIssue(f"source record for {email_id!r} is missing required key {key!r}")
    if record.get("email_id") != email_id:
        raise SourceDataIssue(
            f"source record identity mismatch: file {email_id!r} declares {record.get('email_id')!r}"
        )

    received_at = _validate_received_at(record)

    declared = record.get("attachments") or []
    if not isinstance(declared, list):
        raise SourceDataIssue(f"attachments for {email_id!r} is not a list")

    sources: list[SourceRef] = []
    for declared_path in declared:
        issue: Optional[str] = None
        issue_detail = ""
        content_hash: Optional[str] = None
        size_bytes: Optional[int] = None
        present = False
        try:
            resolved = registry.resolve(str(declared_path))
        except SourceDataIssue as exc:
            issue, issue_detail = UNSAFE_REFERENCE, str(exc)
        else:
            if not resolved.is_file():
                issue, issue_detail = MISSING_FILE, "listed attachment is absent on disk"
            else:
                size_bytes = resolved.stat().st_size
                if size_bytes > config.max_source_bytes:
                    issue = OVERSIZED
                    issue_detail = f"{size_bytes} bytes exceeds the configured source limit"
                else:
                    content_hash = _sha256_file(resolved)
                    present = True

        filename = Path(str(declared_path)).name
        sources.append(
            SourceRef(
                document_id=document_id_for(
                    namespace, case_id, registry.kind, str(declared_path), content_hash
                ),
                declared_path=str(declared_path),
                filename=filename,
                media_type=media_type_for(filename),
                content_hash=content_hash,
                size_bytes=size_bytes,
                present=present,
                demo_safe=registry.demo_safe,
                issue=issue,
                issue_detail=issue_detail,
            )
        )

    return InputSnapshot(
        namespace=namespace,
        case_id=case_id,
        email_id=email_id,
        registry_kind=registry.kind,
        from_address=str(record.get("from") or ""),
        subject=str(record.get("subject") or ""),
        body=str(record.get("body") or ""),
        received_at=received_at,
        sources=tuple(sources),
        input_version=compute_input_version(email_id, record, sources),
        demo_safe=registry.demo_safe,
    )


def read_source_bytes(snapshot: InputSnapshot, document_id: str, *,
                      registries: Mapping[str, SourceRegistry]) -> bytes:
    """Return the exact registered bytes for ``document_id``, verifying identity.

    Fails honestly instead of synthesizing placeholder content, and refuses bytes
    whose hash no longer matches the snapshot.
    """
    ref = snapshot.source_by_id(document_id)
    if ref is None:
        raise SourceDataIssue(f"document {document_id!r} does not belong to this input snapshot")
    if not ref.present or ref.content_hash is None:
        raise SourceDataIssue(f"document {document_id!r} has no registered content")
    registry = registries.get(snapshot.registry_kind)
    if registry is None:
        raise SourceDataIssue(f"source registry {snapshot.registry_kind!r} is not configured")
    data = registry.read_bytes(ref.declared_path)
    actual = hashlib.sha256(data).hexdigest()
    if actual != ref.content_hash:
        raise SourceDataIssue(
            f"document {document_id!r} changed on disk since the run was ingested"
        )
    return data


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
