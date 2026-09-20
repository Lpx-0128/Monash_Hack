"""Candidate extraction for the seven canonical fields (handoff §13).

Every interpretation a document supports becomes a candidate. A single canonical
value is produced only when no unresolved conflict remains; otherwise the cause
and the human-useful candidate information are returned.
"""

from __future__ import annotations

import re
from typing import Optional, Sequence

from .normalization import (
    detect_document_convention,
    is_missing_value,
    parse_container_count,
    parse_gross_weight,
    normalize_party,
    normalize_port,
    port_has_alternatives,
)
from .policies import aliases
from .types import (
    CANONICAL_FIELDS,
    Candidate,
    Derivation,
    Evidence,
    ExtractionMethod,
    FieldOutcome,
    NormalizedValue,
    ParsedDocument,
    ParseStatus,
    UncertaintyCause,
)

VERSION = "extraction-1.0.0"

# "Notify: SAME AS CONSIGNEE" and its variants.
_SAME_AS_CONSIGNEE = re.compile(
    r"^\s*(?:same\s+as\s+(?:the\s+)?consignee|as\s+per\s+consignee|"
    r"consignee\s+as\s+above|same\s+as\s+above)\s*[.]?\s*$",
    re.IGNORECASE,
)


def _evidence_for(document: ParsedDocument, block) -> tuple[Evidence, ...]:
    """The value span plus each additional contributing cell, as separate refs."""
    refs = [Evidence(document.document_id, block.value_locator, block.value_text)]
    extra_texts = block.context.get("extra_value_texts") or []
    for locator, text in zip(block.extra_value_locators, extra_texts):
        refs.append(Evidence(document.document_id, locator, text))
    return tuple(refs)


def _label_evidence(document: ParsedDocument, block) -> Optional[Evidence]:
    if block.label_locator is None or block.label is None:
        return None
    return Evidence(document.document_id, block.label_locator, block.label)


def collect_candidates(document: ParsedDocument, side: str, *,
                       policy: str = "auto",
                       fallback_convention: str = "") -> dict[str, list[Candidate]]:
    """Build every candidate interpretation this document supports, by field.

    ``fallback_convention`` is the registry-established separator convention,
    used only when this document supplies no evidence of its own.
    """
    by_field: dict[str, list[Candidate]] = {field: [] for field in CANONICAL_FIELDS}
    if document.status is not ParseStatus.OK:
        return by_field

    convention = detect_document_convention(document.text) or fallback_convention

    for block in document.blocks:
        field = aliases.match_field(block.label)
        if field is None:
            continue
        raw = block.value_text
        evidence = _evidence_for(document, block)
        flags: list[str] = []
        issues: list[str] = []
        derivation = Derivation.DIRECT
        normalized: Optional[NormalizedValue] = None
        reference_field: Optional[str] = None
        components: tuple[str, ...] = ()
        unit_evidence = None

        if is_missing_value(raw):
            issues.append(UncertaintyCause.MISSING_VALUE.value)
            by_field[field].append(Candidate(
                field=field, side=side, document_id=document.document_id, raw=raw,
                label_text=block.label, evidence=evidence, derivation=derivation,
                method=ExtractionMethod.RULE, normalized=None, issues=tuple(issues),
            ))
            continue

        if field in ("shipper", "consignee", "notify_party"):
            if field == "notify_party" and _SAME_AS_CONSIGNEE.match(raw.strip()):
                derivation = Derivation.REFERENCE
                reference_field = "consignee"
                flags.append("SAME_AS_CONSIGNEE")
            else:
                text = normalize_party(raw)
                normalized = NormalizedValue.of_text(text) if text else None
                if normalized is None:
                    issues.append(UncertaintyCause.MISSING_VALUE.value)

        elif field in ("port_of_loading", "port_of_discharge"):
            text = normalize_port(raw)
            normalized = NormalizedValue.of_text(text) if text else None
            if normalized is None:
                issues.append(UncertaintyCause.MISSING_VALUE.value)
            elif port_has_alternatives(raw):
                # Unresolved alternatives in the source; recorded, never collapsed.
                flags.append("PORT_ALTERNATIVES")

        elif field == "container_count":
            ambiguous_label = aliases.is_ambiguous_count_label(block.label)
            parsed = parse_container_count(raw, label_is_ambiguous=ambiguous_label)
            if parsed.ok:
                from decimal import Decimal
                normalized = NormalizedValue.of_integer(Decimal(parsed.value))
                components = parsed.terms
                if len(parsed.terms) > 1:
                    derivation = Derivation.SUM
                elif aliases.is_total_label(block.label):
                    derivation = Derivation.TOTAL
            elif parsed.ambiguous:
                issues.append(UncertaintyCause.COMPETING_CANDIDATES.value
                              if parsed.reason == "NO_CONTAINER_CONTEXT"
                              else UncertaintyCause.AMBIGUOUS_SEPARATOR.value)
                flags.append(parsed.reason)
            else:
                issues.append(UncertaintyCause.INVALID_VALUE.value)
                flags.append(parsed.reason)

        elif field == "gross_weight_kg":
            label_kg = aliases.label_declares_kg(block.label)
            label_tonnes = aliases.label_declares_tonnes(block.label)
            parsed = parse_gross_weight(
                raw, label=block.label, label_kg=label_kg, label_tonnes=label_tonnes,
                policy=policy, convention=convention,
            )
            if parsed.value is not None:
                normalized = NormalizedValue.of_decimal(parsed.value)
                if parsed.unit_from_label:
                    unit_evidence = _label_evidence(document, block)
                    flags.append("UNIT_FROM_LABEL")
                if aliases.is_total_label(block.label):
                    derivation = Derivation.TOTAL
            elif parsed.ambiguous:
                cause = {
                    "MISSING_UNIT": UncertaintyCause.MISSING_UNIT,
                    "AMBIGUOUS_UNIT": UncertaintyCause.MISSING_UNIT,
                    "UNKNOWN_UNIT": UncertaintyCause.MISSING_UNIT,
                    "LONE_SEPARATOR_AMBIGUOUS": UncertaintyCause.AMBIGUOUS_SEPARATOR,
                }.get(parsed.reason, UncertaintyCause.SEMANTIC_UNCERTAIN)
                issues.append(cause.value)
                flags.append(parsed.reason)
            else:
                issues.append(UncertaintyCause.INVALID_VALUE.value)
                flags.append(parsed.reason)

        by_field[field].append(Candidate(
            field=field, side=side, document_id=document.document_id, raw=raw,
            label_text=block.label, evidence=evidence, derivation=derivation,
            method=ExtractionMethod.RULE, normalized=normalized,
            reference_field=reference_field, components=components,
            flags=tuple(flags), issues=tuple(issues), unit_evidence=unit_evidence,
        ))

    return by_field


def resolve_references(by_field: dict[str, list[Candidate]]) -> dict[str, list[Candidate]]:
    """Resolve "same as consignee" against the *same side's* consignee.

    Both the reference wording and the consignee's own evidence are retained. An
    SI consignee never feeds a BL notify-party.
    """
    consignee = _preferred(by_field.get("consignee") or [])
    resolved: list[Candidate] = []
    for candidate in by_field.get("notify_party") or []:
        if candidate.derivation is not Derivation.REFERENCE:
            resolved.append(candidate)
            continue
        if consignee is None or consignee.normalized is None:
            resolved.append(candidate.with_normalized(
                None, issues=(UncertaintyCause.SEMANTIC_UNCERTAIN.value,),
                flags=("REFERENCE_TARGET_UNRESOLVED",),
            ))
            continue
        merged_evidence = tuple(dict.fromkeys(candidate.evidence + consignee.evidence))
        resolved.append(Candidate(
            field="notify_party", side=candidate.side, document_id=candidate.document_id,
            raw=candidate.raw, label_text=candidate.label_text, evidence=merged_evidence,
            derivation=Derivation.REFERENCE, method=candidate.method,
            normalized=consignee.normalized, reference_field="consignee",
            flags=candidate.flags, issues=candidate.issues,
        ))
    if "notify_party" in by_field:
        by_field["notify_party"] = resolved
    return by_field


def _preferred(candidates: Sequence[Candidate]) -> Optional[Candidate]:
    """The single usable candidate, or None when there is none or several differ."""
    usable = [c for c in candidates if c.normalized is not None]
    if not usable:
        return None
    if len(usable) == 1:
        return usable[0]
    totals = [c for c in usable if c.derivation is Derivation.TOTAL]
    if len(totals) == 1:
        return totals[0]
    first = usable[0]
    if all(c.normalized.equals(first.normalized) for c in usable[1:]):
        return first
    return None


def resolve_field(field: str, side: str, candidates: Sequence[Candidate],
                  document: Optional[ParsedDocument]) -> FieldOutcome:
    """Reduce this field's candidates to one canonical value, or to a cause.

    A trusted total wins over its components; components independently validate
    it. Conflicting interpretations stay unresolved rather than picking whichever
    answer is convenient.
    """
    if document is None:
        return FieldOutcome(field=field, side=side, cause=UncertaintyCause.DOCUMENT_LEVEL,
                            detail="no document is assigned to this side")
    if document.status is not ParseStatus.OK:
        return FieldOutcome(field=field, side=side, cause=UncertaintyCause.UNREADABLE_DOCUMENT,
                            detail=f"the source document is {document.status.value.lower()}")

    if not candidates:
        cause = (UncertaintyCause.UNREADABLE_DOCUMENT
                 if _has_image_only_pages(document) else UncertaintyCause.MISSING_VALUE)
        detail = ("the document has pages with no text layer, so the value may be present "
                  "but unreadable" if cause is UncertaintyCause.UNREADABLE_DOCUMENT
                  else "no labelled value for this field was found in the document")
        return FieldOutcome(field=field, side=side, cause=cause, detail=detail)

    usable = [c for c in candidates if c.normalized is not None]

    if not usable:
        # Every candidate was located but none could be interpreted.
        first = candidates[0]
        cause = UncertaintyCause.MISSING_VALUE
        for candidate in candidates:
            for issue in candidate.issues:
                try:
                    cause = UncertaintyCause(issue)
                except ValueError:
                    continue
                break
            else:
                continue
            break
        return FieldOutcome(
            field=field, side=side, cause=cause,
            detail=f"labelled {first.label_text!r} with raw value {first.raw.strip()!r}",
            alternatives=tuple(candidates),
        )

    totals = [c for c in usable if c.derivation is Derivation.TOTAL]
    if len(totals) == 1 and len(usable) > 1:
        total = totals[0]
        others = [c for c in usable if c is not total]
        conflicting = [c for c in others if not c.normalized.equals(total.normalized)]
        if conflicting:
            return FieldOutcome(
                field=field, side=side, cause=UncertaintyCause.COMPETING_CANDIDATES,
                detail="a declared total conflicts with another labelled value",
                alternatives=tuple(usable),
            )
        return FieldOutcome(field=field, side=side, value=total, alternatives=tuple(others))

    first = usable[0]
    differing = [c for c in usable[1:] if not c.normalized.equals(first.normalized)]
    if differing:
        return FieldOutcome(
            field=field, side=side, cause=UncertaintyCause.COMPETING_CANDIDATES,
            detail="the document supports more than one value for this field",
            alternatives=tuple(usable),
        )

    # Equivalent interpretations: keep one, retaining the other evidence.
    merged = Candidate(
        field=first.field, side=first.side, document_id=first.document_id, raw=first.raw,
        label_text=first.label_text,
        evidence=tuple(dict.fromkeys(e for c in usable for e in c.evidence)),
        derivation=first.derivation, method=first.method, normalized=first.normalized,
        reference_field=first.reference_field, components=first.components,
        flags=tuple(dict.fromkeys(f for c in usable for f in c.flags)),
        issues=first.issues, unit_evidence=first.unit_evidence,
    )
    return FieldOutcome(field=field, side=side, value=merged)


def _has_image_only_pages(document: ParsedDocument) -> bool:
    return any(d.code in ("IMAGE_ONLY_PAGE", "IMAGE_ONLY_DOCUMENT") for d in document.diagnostics)


def extract_side(document: Optional[ParsedDocument], side: str, *,
                 policy: str = "auto",
                 fallback_convention: str = "") -> dict[str, FieldOutcome]:
    """Extract all seven fields for one side of the comparison."""
    if document is None:
        return {
            field: FieldOutcome(field=field, side=side, cause=UncertaintyCause.DOCUMENT_LEVEL,
                                detail="no document is assigned to this side")
            for field in CANONICAL_FIELDS
        }
    by_field = resolve_references(collect_candidates(
        document, side, policy=policy, fallback_convention=fallback_convention))
    return {
        field: resolve_field(field, side, by_field.get(field) or [], document)
        for field in CANONICAL_FIELDS
    }
