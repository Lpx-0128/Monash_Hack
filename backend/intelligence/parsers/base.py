"""Parser protocol and the shared line-oriented label scanner.

Documented parser conventions, relied upon by G1:

* Decoded text is stored with line endings normalized to ``\\n`` at parser
  creation. Every ``text_range`` offset refers to that persisted sequence.
* A **boundary label line** starts at column 0 and has the shape ``Label: value``.
  An *indented* ``label:`` line is address continuation content, not a new field
  (the corpus writes ``  NEW NO : 23, L-BLOCK...`` inside a consignee block).
* A value span runs from just after the label's separator to the end of the last
  continuation line: any following line that is not blank, not a rule of
  ``=``/``-``/``_``/``*``, and not itself a boundary label line.
* An absent value yields an empty span. It never borrows the next label's value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator, Optional, Protocol

from ..types import ParsedDocument

# A label at column 0. The label may not contain a colon or a newline.
_BOUNDARY_LABEL = re.compile(r"^(?P<label>[^\s:][^:\n]{0,79}?)[ \t]*:(?P<sep>[ \t]*)(?P<value>.*)$")
_RULE_LINE = re.compile(r"^[=\-_*~]{3,}\s*$")


@dataclass(frozen=True)
class LabelSpan:
    """A label and the exact offsets of its complete value span."""

    label: str
    label_start: int
    label_end: int
    value_start: int
    value_end: int
    value_text: str
    line_index: int


def normalize_line_endings(text: str) -> str:
    """Canonicalize to LF. Offsets always refer to the result."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def is_boundary_label_line(line: str) -> bool:
    return _BOUNDARY_LABEL.match(line) is not None


def iter_label_spans(text: str) -> Iterator[LabelSpan]:
    """Yield every ``Label: value`` block in ``text`` with exact offsets.

    ``text`` must already be line-ending normalized. For every span,
    ``text[value_start:value_end] == value_text`` holds exactly, which is what
    gate G1 asserts.
    """
    lines: list[tuple[int, str]] = []
    offset = 0
    for line in text.split("\n"):
        lines.append((offset, line))
        offset += len(line) + 1  # the split consumed one '\n'

    for index, (line_start, line) in enumerate(lines):
        match = _BOUNDARY_LABEL.match(line)
        if match is None:
            continue
        label = match.group("label").strip()
        if not label:
            continue
        value_start = line_start + match.start("value")
        value_end = line_start + match.end("value")

        # Extend through continuation lines.
        cursor = index + 1
        while cursor < len(lines):
            next_start, next_line = lines[cursor]
            stripped = next_line.strip()
            if not stripped or _RULE_LINE.match(next_line) or _BOUNDARY_LABEL.match(next_line):
                break
            value_end = next_start + len(next_line)
            cursor += 1

        yield LabelSpan(
            label=label,
            label_start=line_start + match.start("label"),
            label_end=line_start + match.end("label"),
            value_start=value_start,
            value_end=value_end,
            value_text=text[value_start:value_end],
            line_index=index,
        )


# A two-column layout line: ``Label<3+ spaces>value``. Layout-mode PDF extraction
# produces these instead of colons.
_COLUMN_LABEL = re.compile(r"^(?P<label>\S(?:[^:\n]*\S)?)[ \t]{3,}(?P<value>\S.*)$")


def iter_column_spans(text: str, skip_lines: frozenset[int] = frozenset()) -> Iterator[LabelSpan]:
    """Yield ``Label    value`` blocks from a two-column layout.

    A continuation line is one indented to at least the value column, which is
    how a multi-line address is laid out under its party label. Lines in
    ``skip_lines`` are already accounted for by :func:`iter_label_spans`.
    """
    lines: list[tuple[int, str]] = []
    offset = 0
    for line in text.split("\n"):
        lines.append((offset, line))
        offset += len(line) + 1

    consumed: set[int] = set(skip_lines)
    for index, (line_start, line) in enumerate(lines):
        if index in consumed:
            continue
        match = _COLUMN_LABEL.match(line)
        if match is None:
            continue
        label = match.group("label").strip()
        if not label:
            continue
        value_column = match.start("value")
        value_start = line_start + value_column
        value_end = line_start + len(line.rstrip())
        consumed.add(index)

        cursor = index + 1
        while cursor < len(lines):
            next_start, next_line = lines[cursor]
            if not next_line.strip() or _RULE_LINE.match(next_line):
                break
            indent = len(next_line) - len(next_line.lstrip())
            if indent < value_column or cursor in consumed:
                break
            value_end = next_start + len(next_line.rstrip())
            consumed.add(cursor)
            cursor += 1

        yield LabelSpan(
            label=label,
            label_start=line_start + match.start("label"),
            label_end=line_start + match.end("label"),
            value_start=value_start,
            value_end=value_end,
            value_text=text[value_start:value_end],
            line_index=index,
        )


def heading_text(text: str, *, max_lines: int = 6) -> str:
    """The first few non-empty, non-rule lines — used for content-backed roles."""
    collected: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or _RULE_LINE.match(line):
            continue
        collected.append(stripped)
        if len(collected) >= max_lines:
            break
    return "\n".join(collected)


class Parser(Protocol):
    """Every parser turns immutable bytes into an immutable artifact."""

    name: str
    version: str

    def parse(self, data: bytes, *, document_id: str, content_hash: str,
              filename: str, media_type: str) -> ParsedDocument:
        ...
