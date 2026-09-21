"""Page-based PDF parsing, with honest image-only detection.

OCR is not implemented. A page whose text layer is empty but which carries image
XObjects is recorded as a readability limitation — "no text layer" and "nothing
on the page" are different facts (handoff §6).
"""

from __future__ import annotations

import io

from ..config import PARSER_VERSIONS
from ..types import (
    Block,
    Diagnostic,
    ParsedDocument,
    ParseStatus,
    PdfPage,
    PermanentProcessingError,
)
from .base import iter_column_spans, iter_label_spans, normalize_line_endings

NAME = "pdf"
VERSION = PARSER_VERSIONS["pdf"]

IMAGE_ONLY_PAGE = "IMAGE_ONLY_PAGE"
IMAGE_ONLY_DOCUMENT = "IMAGE_ONLY_DOCUMENT"
CORRUPT_SOURCE = "CORRUPT_SOURCE"


def _page_has_images(page) -> bool:
    try:
        resources = page.get("/Resources")
        if resources is None:
            return False
        xobjects = resources.get_object().get("/XObject")
        if xobjects is None:
            return False
        for ref in xobjects.get_object().values():
            if ref.get_object().get("/Subtype") == "/Image":
                return True
    except Exception:  # a resource dictionary we cannot walk is not an image claim
        return False
    return False


def parse(data: bytes, *, document_id: str, content_hash: str,
          filename: str, media_type: str, max_pages: int = 200) -> ParsedDocument:
    try:
        import pypdf
        from pypdf.errors import (
            EmptyFileError,
            FileNotDecryptedError,
            ParseError,
            PdfReadError,
            PdfStreamError,
            WrongPasswordError,
        )
    except ImportError as exc:  # a missing package is a technical failure, not bad input
        raise PermanentProcessingError(f"the PDF parser dependency is unavailable: {exc}") from exc

    # Only these establish that the source itself is unusable. Every other pypdf
    # exception (a dependency error, an internal bug) stays a technical failure.
    SOURCE_CORRUPTION = (
        PdfReadError, PdfStreamError, EmptyFileError, ParseError,
        WrongPasswordError, FileNotDecryptedError,
    )

    def unreadable(code: str, message: str, detail: dict) -> ParsedDocument:
        return ParsedDocument(
            document_id=document_id, content_hash=content_hash, parser_name=NAME,
            parser_version=VERSION, status=ParseStatus.UNREADABLE,
            diagnostics=(Diagnostic(code, message, detail),),
            media_type=media_type, filename=filename,
        )

    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        raw_pages = list(reader.pages)
    except SOURCE_CORRUPTION as exc:
        # A known pypdf source error establishes that the source itself is unusable.
        return unreadable(CORRUPT_SOURCE, "the PDF could not be opened", {"error": str(exc)})
    except Exception as exc:
        # Anything else is a technical failure and must not masquerade as
        # an unreadable document (handoff §11.3, test A-18).
        raise PermanentProcessingError(f"unexpected PDF parser failure: {exc!r}") from exc

    if not raw_pages:
        return unreadable(CORRUPT_SOURCE, "the PDF contains no pages", {})

    diagnostics: list[Diagnostic] = []
    if len(raw_pages) > max_pages:
        diagnostics.append(
            Diagnostic("PAGE_LIMIT", "only the configured page budget was parsed",
                       {"pages": len(raw_pages), "limit": max_pages})
        )
        raw_pages = raw_pages[:max_pages]

    pages: list[str] = []
    blocks: list[Block] = []
    image_only_pages: list[int] = []
    order = 0

    for index, page in enumerate(raw_pages, start=1):
        try:
            extracted = page.extract_text(extraction_mode="layout") or ""
        except SOURCE_CORRUPTION as exc:
            diagnostics.append(
                Diagnostic("PAGE_UNREADABLE", "page text could not be extracted",
                           {"page": index, "error": str(exc)})
            )
            extracted = ""
        except Exception as exc:
            raise PermanentProcessingError(
                f"unexpected PDF text-extraction failure on page {index}: {exc!r}"
            ) from exc

        text = normalize_line_endings(extracted)
        pages.append(text)

        if not text.strip() and _page_has_images(page):
            image_only_pages.append(index)
            diagnostics.append(
                Diagnostic(IMAGE_ONLY_PAGE,
                           "page carries images but no text layer; OCR is disabled",
                           {"page": index})
            )

        colon_spans = list(iter_label_spans(text))
        consumed = set()
        for span in colon_spans:
            consumed.update(
                range(span.line_index, span.line_index + text[span.value_start:span.value_end].count("\n") + 1)
            )
        page_spans = colon_spans + list(iter_column_spans(text, frozenset(consumed)))
        for span in sorted(page_spans, key=lambda s: s.value_start):
            blocks.append(
                Block(
                    block_id=f"p{index:03d}b{order:04d}",
                    label=span.label,
                    value_text=span.value_text,
                    value_locator=PdfPage(index),
                    label_locator=PdfPage(index),
                    context={"page": index, "line": span.line_index},
                    order=order,
                )
            )
            order += 1

    any_text = any(page.strip() for page in pages)
    if not any_text:
        diagnostics.append(
            Diagnostic(IMAGE_ONLY_DOCUMENT,
                       "no page yielded a text layer; the document is not readable without OCR",
                       {"pages": len(pages), "image_only_pages": image_only_pages})
        )
        return ParsedDocument(
            document_id=document_id, content_hash=content_hash, parser_name=NAME,
            parser_version=VERSION, status=ParseStatus.UNREADABLE,
            pages=tuple(pages), diagnostics=tuple(diagnostics),
            media_type=media_type, filename=filename,
        )

    return ParsedDocument(
        document_id=document_id,
        content_hash=content_hash,
        parser_name=NAME,
        parser_version=VERSION,
        status=ParseStatus.OK,
        text="\n".join(pages),
        pages=tuple(pages),
        blocks=tuple(blocks),
        diagnostics=tuple(diagnostics),
        media_type=media_type,
        filename=filename,
    )
