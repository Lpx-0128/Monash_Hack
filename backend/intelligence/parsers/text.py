"""Plain-text parsing with exact code-point offsets."""

from __future__ import annotations

from ..config import PARSER_VERSIONS
from ..types import Block, Diagnostic, ParsedDocument, ParseStatus, TextRange
from .base import iter_label_spans, normalize_line_endings

NAME = "text"
VERSION = PARSER_VERSIONS["text"]

# Tried in order, strictly. ``errors="replace"`` is never used: a corrupted byte
# sequence is reported as a source-quality issue instead of a trusted field.
ENCODINGS = ("utf-8-sig", "utf-8", "cp1252")


def decode(data: bytes) -> tuple[str, str]:
    """Return ``(text, encoding)`` or raise ``UnicodeDecodeError`` from the last try."""
    last: Exception | None = None
    for encoding in ENCODINGS:
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError as exc:
            last = exc
    raise last  # type: ignore[misc]


def parse(data: bytes, *, document_id: str, content_hash: str,
          filename: str, media_type: str) -> ParsedDocument:
    try:
        decoded, encoding = decode(data)
    except UnicodeDecodeError as exc:
        return ParsedDocument(
            document_id=document_id,
            content_hash=content_hash,
            parser_name=NAME,
            parser_version=VERSION,
            status=ParseStatus.UNREADABLE,
            diagnostics=(
                Diagnostic(
                    "UNDECODABLE_TEXT",
                    "byte sequence is not valid in any supported encoding",
                    {"encodings": list(ENCODINGS), "position": exc.start},
                ),
            ),
            media_type=media_type,
            filename=filename,
        )

    text = normalize_line_endings(decoded)
    diagnostics = [Diagnostic("TEXT_ENCODING", "decoded source encoding", {"encoding": encoding})]
    if "�" in text:
        diagnostics.append(
            Diagnostic("REPLACEMENT_CHARACTER", "source already contains U+FFFD", {})
        )

    blocks = tuple(
        Block(
            block_id=f"b{index:04d}",
            label=span.label,
            value_text=span.value_text,
            value_locator=TextRange(span.value_start, span.value_end),
            label_locator=TextRange(span.label_start, span.label_end),
            context={"line": span.line_index},
            order=index,
        )
        for index, span in enumerate(iter_label_spans(text))
    )

    return ParsedDocument(
        document_id=document_id,
        content_hash=content_hash,
        parser_name=NAME,
        parser_version=VERSION,
        status=ParseStatus.OK,
        text=text,
        blocks=blocks,
        diagnostics=tuple(diagnostics),
        media_type=media_type,
        filename=filename,
    )
