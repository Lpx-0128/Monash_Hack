"""Internal immutable DTOs for the Person A document-intelligence pipeline.

Nothing here is a public wire type. These objects may carry exact ``Decimal``
values, private diagnostics and source text. Only :mod:`backend.intelligence.pipeline`
converts a subset of them into the contract shapes defined in ``backend.schemas``.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field, replace
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping, Optional, Sequence, Union

# The seven canonical fields, in required review order (handoff §2).
CANONICAL_FIELDS = (
    "shipper",
    "consignee",
    "notify_party",
    "port_of_loading",
    "port_of_discharge",
    "container_count",
    "gross_weight_kg",
)

PARTY_FIELDS = frozenset({"shipper", "consignee", "notify_party"})
PORT_FIELDS = frozenset({"port_of_loading", "port_of_discharge"})
NUMERIC_FIELDS = frozenset({"container_count", "gross_weight_kg"})

SIDES = ("SI", "BL")

# JavaScript-safe integer bound; the wire ``normalized`` value is a JSON number.
MAX_SAFE_INTEGER = 2 ** 53 - 1


# ---------------------------------------------------------------------------
# Failure taxonomy (handoff §8). Internal names; they do not expand public enums.
# ---------------------------------------------------------------------------

class IntelligenceError(Exception):
    """Base class for every error raised inside the intelligence package."""


class SourceDataIssue(IntelligenceError):
    """The input itself is missing, corrupt or unreadable. Not a code defect."""


class AmbiguousValue(IntelligenceError):
    """A value was located but cannot be interpreted to a single canonical result."""


class RetryableProcessingError(IntelligenceError):
    """A transient technical failure: provider timeout, I/O error, locked resource."""


class PermanentProcessingError(IntelligenceError):
    """A technical failure that retrying cannot fix: missing package, bad config."""


class ContractViolation(IntelligenceError):
    """Produced output would break the shared contract. Never returned to a caller."""


# ---------------------------------------------------------------------------
# Locators — mirror the contract union exactly (handoff §11 "Shared locator conventions")
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TextRange:
    """Zero-based code-point offsets into the parser's persisted text, end exclusive."""

    start: int
    end: int
    kind: str = "text_range"

    def to_wire(self) -> dict:
        return {"kind": "text_range", "start": self.start, "end": self.end}


@dataclass(frozen=True)
class PdfPage:
    """One-based page number. The quote must occur on that page."""

    page: int
    kind: str = "pdf_page"

    def to_wire(self) -> dict:
        return {"kind": "pdf_page", "page": self.page}


@dataclass(frozen=True)
class DocxParagraph:
    """Zero-based index into the body paragraph sequence this parser persists."""

    index: int
    kind: str = "docx_paragraph"

    def to_wire(self) -> dict:
        return {"kind": "docx_paragraph", "index": self.index}


@dataclass(frozen=True)
class DocxTableCell:
    """Zero-based table/row/column with the parser's merged-cell origin convention."""

    table: int
    row: int
    column: int
    kind: str = "docx_table_cell"

    def to_wire(self) -> dict:
        return {
            "kind": "docx_table_cell",
            "table": self.table,
            "row": self.row,
            "column": self.column,
        }


@dataclass(frozen=True)
class SheetCell:
    """Exact sheet name and A1 coordinate."""

    sheet: str
    cell: str
    kind: str = "sheet_cell"

    def to_wire(self) -> dict:
        return {"kind": "sheet_cell", "sheet": self.sheet, "cell": self.cell}


Locator = Union[TextRange, PdfPage, DocxParagraph, DocxTableCell, SheetCell]


@dataclass(frozen=True)
class Evidence:
    """A reference to exact text at an exact location in one parsed document."""

    document_id: str
    locator: Locator
    source_text: str

    def to_wire(self) -> dict:
        return {
            "document_id": self.document_id,
            "locator": self.locator.to_wire(),
            "source_text": self.source_text,
        }


# ---------------------------------------------------------------------------
# Parsed documents
# ---------------------------------------------------------------------------

class ParseStatus(str, Enum):
    OK = "OK"
    UNREADABLE = "UNREADABLE"
    UNSUPPORTED = "UNSUPPORTED"
    NOT_PARSED = "NOT_PARSED"


@dataclass(frozen=True)
class Diagnostic:
    """A private source-quality observation. Never serialized onto the wire."""

    code: str
    message: str
    detail: Mapping[str, Any] = dc_field(default_factory=dict)


@dataclass(frozen=True)
class Block:
    """One structural label/value unit produced by a parser.

    ``value_locator`` addresses the complete value span, including continuation
    lines and adjacent contributing cells recorded in ``extra_value_locators``.
    """

    block_id: str
    label: Optional[str]
    value_text: str
    value_locator: Locator
    label_locator: Optional[Locator] = None
    extra_value_locators: tuple[Locator, ...] = ()
    context: Mapping[str, Any] = dc_field(default_factory=dict)
    order: int = 0


@dataclass(frozen=True)
class ParsedDocument:
    """Immutable parse artifact, cached by (document_hash, parser_version, config_version)."""

    document_id: str
    content_hash: str
    parser_name: str
    parser_version: str
    status: ParseStatus
    text: str = ""
    pages: tuple[str, ...] = ()
    blocks: tuple[Block, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    media_type: str = ""
    filename: str = ""

    # -- grounding support -------------------------------------------------
    def block_by_id(self, block_id: Optional[str]):
        """The private structural block with this id, or ``None``."""
        if block_id is None:
            return None
        for block in self.blocks:
            if block.block_id == block_id:
                return block
        return None

    def locator_texts(self, locator: Locator) -> tuple[str, ...]:
        """Every persisted text addressed by ``locator``.

        A locator may address more than one stored quote — a DOCX paragraph can
        hold several ``Label: value`` spans — so G1 checks membership rather
        than assuming a single answer.
        """
        if isinstance(locator, TextRange):
            if locator.start < 0 or locator.end > len(self.text) or locator.start > locator.end:
                return ()
            return (self.text[locator.start:locator.end],)
        if isinstance(locator, PdfPage):
            if locator.page < 1 or locator.page > len(self.pages):
                return ()
            return (self.pages[locator.page - 1],)
        found: list[str] = []
        for block in self.blocks:
            if block.value_locator == locator or locator in block.extra_value_locators:
                found.append(block.value_text)
            if block.label_locator == locator and block.label is not None:
                found.append(block.label)
        return tuple(found)

    @staticmethod
    def locator_is_exact(locator: Locator) -> bool:
        """True when the locator addresses the quote itself rather than a container.

        ``text_range`` is exact. Page, paragraph, table-cell and sheet-cell
        locators are containers, so G1 accepts a quote contained in them.
        """
        return isinstance(locator, TextRange)


# ---------------------------------------------------------------------------
# Normalized values
# ---------------------------------------------------------------------------

class ValueKind(str, Enum):
    TEXT = "TEXT"
    INTEGER = "INTEGER"
    DECIMAL = "DECIMAL"


@dataclass(frozen=True)
class NormalizedValue:
    """A canonical comparison value plus the wire conversion policy.

    Exact ``Decimal`` values stay private; :meth:`to_wire` performs the checked
    JSON-number conversion described in handoff §15.6.
    """

    kind: ValueKind
    text: Optional[str] = None
    number: Optional[Decimal] = None

    @staticmethod
    def of_text(value: str) -> "NormalizedValue":
        return NormalizedValue(kind=ValueKind.TEXT, text=value)

    @staticmethod
    def of_integer(value: Decimal) -> "NormalizedValue":
        return NormalizedValue(kind=ValueKind.INTEGER, number=value)

    @staticmethod
    def of_decimal(value: Decimal) -> "NormalizedValue":
        return NormalizedValue(kind=ValueKind.DECIMAL, number=value)

    def to_wire(self) -> Union[str, int, float]:
        """Convert to a JSON scalar, or raise ``ContractViolation`` rather than round."""
        if self.kind is ValueKind.TEXT:
            if self.text is None:
                raise ContractViolation("text normalized value carries no text")
            return self.text
        if self.number is None:
            raise ContractViolation("numeric normalized value carries no number")
        if not self.number.is_finite():
            raise ContractViolation(f"non-finite normalized value {self.number!r}")
        if self.kind is ValueKind.INTEGER:
            as_int = int(self.number)
            if Decimal(as_int) != self.number:
                raise ContractViolation(f"integer value {self.number!r} is not integral")
            if abs(as_int) > MAX_SAFE_INTEGER:
                raise ContractViolation(f"integer value {as_int} exceeds the safe-integer range")
            return as_int
        # DECIMAL: verify the canonical decimal round-trip through JSON's number type.
        if self.number == self.number.to_integral_value():
            as_int = int(self.number)
            if abs(as_int) <= MAX_SAFE_INTEGER:
                return as_int
        as_float = float(self.number)
        if Decimal(repr(as_float)) != self.number:
            raise ContractViolation(
                f"decimal value {self.number!r} cannot round-trip through a JSON number"
            )
        return as_float

    def equals(self, other: "NormalizedValue") -> bool:
        """Exact equality. No tolerance, no fuzzy text similarity."""
        if self.kind is ValueKind.TEXT or other.kind is ValueKind.TEXT:
            if self.kind is not other.kind:
                return False
            return self.text == other.text
        if self.number is None or other.number is None:
            return False
        return self.number == other.number


# ---------------------------------------------------------------------------
# Candidates and uncertainty
# ---------------------------------------------------------------------------

class Derivation(str, Enum):
    DIRECT = "DIRECT"
    SUM = "SUM"
    REFERENCE = "REFERENCE"
    TOTAL = "TOTAL"
    HUMAN_INPUT = "HUMAN_INPUT"


class ExtractionMethod(str, Enum):
    RULE = "RULE"
    AI = "AI"
    HUMAN = "HUMAN"


@dataclass(frozen=True)
class Candidate:
    """One interpretation of one canonical field on one side."""

    field: str
    side: str
    document_id: str
    raw: str
    label_text: Optional[str]
    evidence: tuple[Evidence, ...]
    derivation: Derivation = Derivation.DIRECT
    method: ExtractionMethod = ExtractionMethod.RULE
    normalized: Optional[NormalizedValue] = None
    reference_field: Optional[str] = None
    components: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()
    issues: tuple[str, ...] = ()
    unit_evidence: Optional[Evidence] = None
    # The private parser block this value was read from. Grounding resolves the
    # label and the source text through this block, never through the candidate's
    # own claims, so a page-level public locator cannot stand in as proof of a
    # label/value relationship.
    block_id: Optional[str] = None
    reference_block_id: Optional[str] = None

    def with_normalized(self, value: Optional[NormalizedValue], *,
                        flags: Sequence[str] = (), issues: Sequence[str] = ()) -> "Candidate":
        return replace(
            self,
            normalized=value,
            flags=tuple(dict.fromkeys((*self.flags, *flags))),
            issues=tuple(dict.fromkeys((*self.issues, *issues))),
        )


@dataclass(frozen=True)
class GroundingResult:
    """Outcome of running G1/G2/G3 over one candidate."""

    passed: bool
    gate: Optional[str] = None       # "G1", "G2" or "G3" when ``passed`` is False
    reason: Optional[str] = None     # private diagnostic code
    detail: str = ""

    @staticmethod
    def ok() -> "GroundingResult":
        return GroundingResult(passed=True)

    @staticmethod
    def fail(gate: str, reason: str, detail: str = "") -> "GroundingResult":
        return GroundingResult(passed=False, gate=gate, reason=reason, detail=detail)


class UncertaintyCause(str, Enum):
    """Private causes. ``comparison.py`` maps these to contract NotComparableCause."""

    MISSING_VALUE = "MISSING_VALUE"
    MISSING_UNIT = "MISSING_UNIT"
    AMBIGUOUS_SEPARATOR = "AMBIGUOUS_SEPARATOR"
    COMPETING_CANDIDATES = "COMPETING_CANDIDATES"
    UNGROUNDED = "UNGROUNDED"
    INVALID_VALUE = "INVALID_VALUE"
    UNREADABLE_DOCUMENT = "UNREADABLE_DOCUMENT"
    DOCUMENT_LEVEL = "DOCUMENT_LEVEL"
    SEMANTIC_UNCERTAIN = "SEMANTIC_UNCERTAIN"


@dataclass(frozen=True)
class FieldOutcome:
    """The resolved state of one (field, side) before comparison."""

    field: str
    side: str
    value: Optional[Candidate] = None
    cause: Optional[UncertaintyCause] = None
    detail: str = ""
    alternatives: tuple[Candidate, ...] = ()

    @property
    def resolved(self) -> bool:
        return self.value is not None and self.value.normalized is not None
