"""Content-signature parser dispatch.

The extension is a hint; the signature decides. An arbitrary ZIP is not a Word
or Excel document, and nothing found inside a document is ever executed.
"""

from __future__ import annotations

import io
import zipfile

from ..config import IntelligenceConfig
from ..types import Diagnostic, ParsedDocument, ParseStatus
from . import docx as docx_parser
from . import pdf as pdf_parser
from . import text as text_parser
from . import xlsx as xlsx_parser

PDF_SIGNATURE = b"%PDF-"
ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")


class ParserUnavailable(RuntimeError):
    """No parser supports this content signature."""


def detect_format(data: bytes, filename: str = "") -> str:
    """Return one of ``pdf``, ``docx``, ``xlsx``, ``text`` or ``unsupported``."""
    if data.startswith(PDF_SIGNATURE):
        return "pdf"
    if data.startswith(ZIP_SIGNATURES):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = set(archive.namelist())
        except zipfile.BadZipFile:
            return "unsupported"
        if "word/document.xml" in names:
            return "docx"
        if "xl/workbook.xml" in names:
            return "xlsx"
        return "unsupported"
    # Not a recognized binary container: only accept it as text if it decodes.
    try:
        text_parser.decode(data)
    except UnicodeDecodeError:
        return "unsupported"
    if b"\x00" in data[:4096]:
        return "unsupported"
    return "text"


def parse_source(data: bytes, *, document_id: str, content_hash: str, filename: str,
                 media_type: str, config: IntelligenceConfig) -> ParsedDocument:
    """Dispatch on the real content signature and return an immutable artifact."""
    detected = detect_format(data, filename)

    if detected == "text":
        return text_parser.parse(data, document_id=document_id, content_hash=content_hash,
                                 filename=filename, media_type=media_type)
    if detected == "pdf":
        return pdf_parser.parse(data, document_id=document_id, content_hash=content_hash,
                                filename=filename, media_type=media_type,
                                max_pages=config.max_pdf_pages)
    if detected == "docx":
        return docx_parser.parse(data, document_id=document_id, content_hash=content_hash,
                                 filename=filename, media_type=media_type)
    if detected == "xlsx":
        return xlsx_parser.parse(data, document_id=document_id, content_hash=content_hash,
                                 filename=filename, media_type=media_type,
                                 max_cells=config.max_sheet_cells)

    return ParsedDocument(
        document_id=document_id,
        content_hash=content_hash,
        parser_name="router",
        parser_version="router-1.0.0",
        status=ParseStatus.UNSUPPORTED,
        diagnostics=(
            Diagnostic("UNSUPPORTED_FORMAT",
                       "no configured parser recognizes this content signature",
                       {"filename": filename, "declared_media_type": media_type}),
        ),
        media_type=media_type,
        filename=filename,
    )
