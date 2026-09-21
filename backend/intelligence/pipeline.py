"""Composition of the Person A services (handoff §§7-8).

``analyze_case`` is the single stable callable Person B integrates against. It
performs no database work, opens no transaction, creates no review ID, sends no
notification and mutates no Case. Dependencies are passed explicitly and the
result is a plain value object that B validates and commits.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field as dc_field
from typing import Callable, Mapping, Optional, Sequence

from . import ai as ai_module
from .classification import build_view, classify
from .comparison import (
    Assessment,
    FieldComparisonResult,
    compare_all,
    roll_up,
)
from .config import (
    MAX_DISTINCT_REVIEW_FIELDS,
    IntelligenceConfig,
    PARSER_VERSIONS,
)
from .extraction import extract_side
from .grounding import ground_candidate
from .ingestion import InputSnapshot, SourceRef, SourceRegistry, read_source_bytes
from .parsers.router import parse_source
from .roles import RoleResolution, filename_hint, resolve_roles
from .types import (
    CANONICAL_FIELDS,
    ExtractionMethod,
    Derivation,
    Evidence,
    NormalizedValue,
    Candidate,
    Diagnostic,
    FieldOutcome,
    ParsedDocument,
    ParseStatus,
    PermanentProcessingError,
    RetryableProcessingError,
    SourceDataIssue,
    UncertaintyCause,
)

VERSION = "pipeline-2.1.0"

NONE_OF_THESE = "NONE_OF_THESE"


@dataclass(frozen=True)
class AnalysisContext:
    """Run identity, approved config and injected providers."""

    case_id: str
    run_id: str
    run_kind: str
    config: IntelligenceConfig
    now: Callable[[], str]
    next_id: Callable[[str], str]


@dataclass
class IntelligenceServices:
    """Everything the pipeline is allowed to reach outside itself."""

    registries: Mapping[str, SourceRegistry]
    model: Optional[object] = None
    budget: Optional[ai_module.CallBudget] = None


@dataclass(frozen=True)
class DocumentRefResult:
    """What Person B persists as a contract ``DocumentRef``."""

    document_id: str
    role: str
    filename: str
    media_type: str
    size_bytes: Optional[int]
    content_hash: str
    demo_safe: bool
    parse_status: str


@dataclass(frozen=True)
class ReviewOptionRequirement:
    option_id: str
    kind: str                       # DOCUMENT | VALUE | ESCAPE
    label: str
    document_id: Optional[str] = None
    value: Optional[Candidate] = None


@dataclass(frozen=True)
class ReviewRequirement:
    """A review *requirement*. Person B constructs and persists the Review."""

    scope: str                      # FIELD | DOCUMENT
    ui_mode: str                    # CHOICE | VALUE_INPUT | ACKNOWLEDGE
    reason: str
    question: str
    context_summary: str
    allowed_actions: tuple[str, ...]
    field: Optional[str] = None
    side: Optional[str] = None
    target_role: Optional[str] = None
    options: tuple[ReviewOptionRequirement, ...] = ()
    source_document_ids: tuple[str, ...] = ()
    blocks_externally: bool = False


@dataclass(frozen=True)
class AutomatedAnalysis:
    """The frozen result of one automated pass."""

    category: Optional[str]
    classified_by: Optional[str]
    classification_reason: str
    documents: tuple[DocumentRefResult, ...]
    comparisons: tuple[FieldComparisonResult, ...]
    assessment: Optional[Assessment]
    review: Optional[ReviewRequirement]
    unresolved_targets: tuple[tuple[str, str], ...]
    roles: Optional[RoleResolution]
    parsed: Mapping[str, ParsedDocument] = dc_field(default_factory=dict)
    si_fields: Mapping[str, FieldOutcome] = dc_field(default_factory=dict)
    bl_fields: Mapping[str, FieldOutcome] = dc_field(default_factory=dict)
    ai_calls: int = 0
    ai_assisted_fields: int = 0
    processing_ms: int = 0
    events: tuple[tuple[str, str], ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    input_version: str = ""
    config_version: str = ""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_snapshot(snapshot: InputSnapshot, context: AnalysisContext,
                   services: IntelligenceServices) -> tuple[dict, list[Diagnostic]]:
    """Parse every present source once, keyed by document id."""
    parsed: dict[str, ParsedDocument] = {}
    diagnostics: list[Diagnostic] = []

    for ref in snapshot.sources:
        if not ref.present:
            diagnostics.append(Diagnostic(
                ref.issue or "MISSING_FILE",
                ref.issue_detail or "the listed attachment is not available",
                {"filename": ref.filename, "declared_path": ref.declared_path},
            ))
            continue
        try:
            data = read_source_bytes(snapshot, ref.document_id, registries=services.registries)
        except SourceDataIssue as exc:
            diagnostics.append(Diagnostic("SOURCE_UNAVAILABLE", str(exc),
                                          {"document_id": ref.document_id}))
            continue
        except OSError as exc:
            # Storage trouble is a technical failure, not an unreadable document.
            raise RetryableProcessingError(
                f"could not read registered source {ref.filename!r}: {exc}"
            ) from exc

        document = parse_source(
            data, document_id=ref.document_id, content_hash=ref.content_hash or "",
            filename=ref.filename, media_type=ref.media_type, config=context.config,
        )
        parsed[ref.document_id] = document
        diagnostics.extend(document.diagnostics)

    return parsed, diagnostics


def _document_refs(snapshot: InputSnapshot, parsed: Mapping[str, ParsedDocument],
                   roles: Optional[RoleResolution]) -> tuple[DocumentRefResult, ...]:
    refs = []
    for ref in snapshot.sources:
        document = parsed.get(ref.document_id)
        role = roles.role_of(ref.document_id) if roles is not None else "UNKNOWN"
        if document is None:
            status = ParseStatus.NOT_PARSED.value
            role = "UNKNOWN"
        else:
            status = document.status.value
        refs.append(DocumentRefResult(
            document_id=ref.document_id,
            role=role,
            filename=ref.filename,
            media_type=ref.media_type,
            size_bytes=ref.size_bytes,
            # A missing file has no invented hash.
            content_hash=ref.content_hash or "",
            demo_safe=ref.demo_safe,
            parse_status=status,
        ))
    return tuple(refs)


# ---------------------------------------------------------------------------
# Grounding every machine candidate
# ---------------------------------------------------------------------------

def _ground_side(fields: Mapping[str, FieldOutcome], parsed: Mapping[str, ParsedDocument],
                 snapshot: InputSnapshot, policy: str,
                 fallback_convention: str = "") -> dict[str, FieldOutcome]:
    """Re-verify every extracted value. An ungrounded value is not comparable."""
    grounded: dict[str, FieldOutcome] = {}
    reference_values = {
        name: outcome.value.normalized
        for name, outcome in fields.items()
        if outcome.resolved and outcome.value is not None
    }
    for name, outcome in fields.items():
        if not outcome.resolved or outcome.value is None:
            grounded[name] = outcome
            continue
        document = parsed.get(outcome.value.document_id)
        ref = snapshot.source_by_id(outcome.value.document_id)
        if document is None:
            grounded[name] = FieldOutcome(
                field=name, side=outcome.side, cause=UncertaintyCause.DOCUMENT_LEVEL,
                detail="the candidate's document is not part of this run",
            )
            continue
        result = ground_candidate(
            outcome.value, document, policy=policy,
            fallback_convention=fallback_convention,
            expected_hash=ref.content_hash if ref else None,
            reference_values=reference_values,
        )
        if result.passed:
            grounded[name] = outcome
        else:
            grounded[name] = FieldOutcome(
                field=name, side=outcome.side, cause=UncertaintyCause.UNGROUNDED,
                detail=f"{result.gate} {result.reason}: {result.detail}",
                alternatives=outcome.alternatives,
            )
    return grounded


# ---------------------------------------------------------------------------
# Targeted AI extraction
# ---------------------------------------------------------------------------

# A location token the model may choose from, resolved back to a private block
# server-side. The model never supplies offsets, indices or coordinates.
def _location_tokens(document: ParsedDocument) -> dict[str, object]:
    return {f"block:{block.block_id}": block for block in document.blocks}


# The model may only help where the document already supports several readings
# the rules refused to choose between. It cannot be asked to supply a value that
# is absent, nor to relabel content: the alias policy remains the authority on
# what a label means, and G2 enforces that regardless of what the model asserts.
AI_ELIGIBLE_CAUSES = (
    UncertaintyCause.COMPETING_CANDIDATES,
    UncertaintyCause.SEMANTIC_UNCERTAIN,
)


def _eligible_for_ai(outcome: FieldOutcome) -> bool:
    """Only interpretable ambiguity between candidates the document really has.

    A missing value cannot be found by rereading, and a document-level problem
    is not fixed by asking a model to look again. Both are left alone so the
    honest uncertainty reaches a person instead of being papered over.
    """
    if outcome.resolved:
        return False
    return outcome.cause in AI_ELIGIBLE_CAUSES and len(outcome.alternatives) >= 2


def ai_extract_side(document: Optional[ParsedDocument], side: str,
                    fields: Mapping[str, FieldOutcome], *,
                    services: IntelligenceServices,
                    config: IntelligenceConfig,
                    snapshot: InputSnapshot,
                    fallback_convention: str = "") -> tuple[dict, int, int, list]:
    """Ask the approved model about unresolved fields, then verify every answer.

    Returns ``(fields, calls, assisted, events)``. A proposal only becomes a
    value if it maps to a real private block and then passes G1, G2 and G3 —
    the same gates deterministic extraction goes through. The model cannot set a
    normalized value, a grounded flag, a comparison result or workflow state.
    """
    events: list[tuple[str, str]] = []
    if document is None or document.status is not ParseStatus.OK:
        return dict(fields), 0, 0, events

    requested = [name for name, outcome in fields.items() if _eligible_for_ai(outcome)]
    if not requested:
        return dict(fields), 0, 0, events

    allowed, reason = model_permitted_for(snapshot, config, services)
    if not allowed:
        return dict(fields), 0, 0, events

    tokens = _location_tokens(document)
    if services.budget is not None:
        services.budget.spend()          # charged before the call, not after

    try:
        proposal = services.model.extract(
            document_id=document.document_id,
            document_text=document.text,
            location_tokens={token: {"label": block.label, "value": block.value_text,
                                     "context": dict(block.context), "order": block.order}
                             for token, block in tokens.items()},
            requested_fields=tuple(requested),
        )
    except RetryableProcessingError:
        # A provider failure leaves the deterministic result standing.
        events.append(("AI_EXTRACTION_USED",
                       f"Model extraction for the {side} was unavailable"))
        return dict(fields), 1, 0, events

    # Collect every validated proposal per field *before* touching any outcome.
    # Overwriting as they arrive would make the last entry win, which silently
    # resolves a conflict the document does not resolve.
    proposed_by_field: dict[str, list[Candidate]] = {}
    unresolved_claimed = set(proposal.unresolved_fields)
    if proposal.document_id != document.document_id:
        return dict(fields), 1, 0, [("AI_EXTRACTION_USED", "Model document identity was invalid")]

    for candidate_proposal in proposal.candidates:
        block = tokens.get(candidate_proposal.locator_token)
        if block is None:
            continue
        field = candidate_proposal.field
        if field not in requested:
            continue
        # Check injected clients as well as the HTTP adapter. Never replace a
        # contradictory model value with the value at its chosen token.
        if (candidate_proposal.raw != block.value_text
                or candidate_proposal.source_text != block.value_text):
            unresolved_claimed.add(field)
            events.append(("AI_EXTRACTION_USED",
                           f"Model evidence disagreed with its source block for {field} on {side}"))
            continue
        if field in unresolved_claimed:
            # The response says this field is unresolved and also proposes a
            # value for it. That is not a result we can act on.
            events.append(("AI_EXTRACTION_USED",
                           f"The model both proposed and disclaimed {field} on the "
                           f"{side}; the response was not used for it"))
            continue

        outcome = fields.get(field)
        if outcome is None:
            continue
        # The choice must be one of the readings the document already supports.
        chosen = next(
            (c for c in outcome.alternatives
             if c.block_id == block.block_id and c.normalized is not None),
            None,
        )
        if chosen is None:
            events.append(("AI_EXTRACTION_USED",
                           f"A model proposal for {field} on the {side} pointed outside "
                           "the document's own candidates and was discarded"))
            continue

        candidate = Candidate(
            field=field, side=side, document_id=document.document_id,
            raw=block.value_text, label_text=block.label,
            evidence=(Evidence(document.document_id, block.value_locator,
                               block.value_text),),
            derivation=(Derivation.TOTAL if candidate_proposal.derivation == "TOTAL"
                        else Derivation.DIRECT),
            method=ExtractionMethod.AI, normalized=chosen.normalized,
            flags=("AI_PROPOSED",), block_id=block.block_id,
        )
        ref = snapshot.source_by_id(document.document_id)
        result = ground_candidate(
            candidate, document, policy=config.numeric_locale_policy,
            fallback_convention=fallback_convention,
            expected_hash=ref.content_hash if ref else None,
        )
        if not result.passed:
            events.append(("AI_EXTRACTION_USED",
                           f"A model proposal for {field} on the {side} failed "
                           f"{result.gate} and was discarded"))
            continue
        proposed_by_field.setdefault(field, []).append(candidate)

    updated = dict(fields)
    assisted = 0

    for field, candidates in proposed_by_field.items():
        if field in unresolved_claimed:
            continue
        # Identical canonical interpretations are one answer, however many times
        # the model listed them.
        distinct: list[Candidate] = []
        for candidate in candidates:
            if not any(candidate.normalized.equals(seen.normalized) for seen in distinct):
                distinct.append(candidate)

        if len(distinct) > 1:
            # Several grounded but different readings. Each is genuinely in the
            # document; nothing here establishes which is the intended current
            # value, so the field stays uncertain for a person.
            events.append((
                "AI_EXTRACTION_USED",
                f"The model returned {len(distinct)} different grounded readings for "
                f"{field} on the {side}; the field remains uncertain",
            ))
            existing = fields[field]
            updated[field] = FieldOutcome(
                field=field, side=side,
                cause=UncertaintyCause.COMPETING_CANDIDATES,
                detail="the model did not resolve which of the document's readings applies",
                alternatives=existing.alternatives or tuple(distinct),
            )
            continue

        updated[field] = FieldOutcome(field=field, side=side, value=distinct[0])
        # Count fields actually resolved, not proposal entries.
        assisted += 1
        events.append(("AI_EXTRACTION_USED",
                       f"{field} on the {side} was resolved with model assistance"))

    return updated, 1, assisted, events


# ---------------------------------------------------------------------------
# Review requirements
# ---------------------------------------------------------------------------

_FIELD_LABELS = {
    "shipper": "shipper",
    "consignee": "consignee",
    "notify_party": "notify party",
    "port_of_loading": "port of loading",
    "port_of_discharge": "port of discharge",
    "container_count": "container count",
    "gross_weight_kg": "gross weight in kg",
}

_CAUSE_EXPLANATION = {
    UncertaintyCause.MISSING_VALUE: "the document has this field but no value was supplied",
    UncertaintyCause.MISSING_UNIT: "a number was found but the document does not state its unit",
    UncertaintyCause.AMBIGUOUS_SEPARATOR: (
        "the number uses a separator that could be a thousands or a decimal mark, "
        "and the document does not establish which"
    ),
    UncertaintyCause.COMPETING_CANDIDATES: "the document supports more than one value",
    UncertaintyCause.UNGROUNDED: "the located value could not be verified against its source",
    UncertaintyCause.INVALID_VALUE: "the located value is not a usable value for this field",
    UncertaintyCause.UNREADABLE_DOCUMENT: "the source document could not be read",
    UncertaintyCause.DOCUMENT_LEVEL: "no usable document is assigned to this side",
    UncertaintyCause.SEMANTIC_UNCERTAIN: "the value could not be interpreted with confidence",
}


def unresolved_field_targets(si_fields: Mapping[str, FieldOutcome],
                             bl_fields: Mapping[str, FieldOutcome]
                             ) -> tuple[tuple[str, str], ...]:
    """Unresolved (field, side) targets in canonical order, SI before BL."""
    targets = []
    for field in CANONICAL_FIELDS:
        for side, fields in (("SI", si_fields), ("BL", bl_fields)):
            outcome = fields.get(field)
            if outcome is not None and not outcome.resolved:
                targets.append((field, side))
    return tuple(targets)


def _confirmed_difference_note(comparisons: Sequence[FieldComparisonResult]) -> str:
    differing = [c.field for c in comparisons if c.result == "MISMATCH"]
    if not differing:
        return ""
    return (" A difference has already been confirmed in "
            + ", ".join(_FIELD_LABELS.get(f, f) for f in differing)
            + "; that is recorded and is not what this question is about.")


def build_review_requirement(assessment: Assessment, roles: Optional[RoleResolution],
                             si_fields: Mapping[str, FieldOutcome],
                             bl_fields: Mapping[str, FieldOutcome],
                             comparisons: Sequence[FieldComparisonResult],
                             parsed: Mapping[str, ParsedDocument],
                             *, prior_review_fields: Sequence[str] = (),
                             document_issues: Sequence[str] = ()
                             ) -> Optional[ReviewRequirement]:
    """Describe the one question worth asking, or the external block to record."""
    if assessment.status != "NEEDS_REVIEW":
        return None

    confirmed = _confirmed_difference_note(comparisons)

    # Document-role choice: plausible candidates exist for an unassigned role.
    if roles is not None:
        for target_role, chosen, alternatives in (
            ("SI", roles.si, roles.si_alternatives),
            ("BL", roles.bl, roles.bl_alternatives),
        ):
            if chosen is None and alternatives:
                options = [
                    ReviewOptionRequirement(
                        option_id=f"doc_{index}", kind="DOCUMENT",
                        label=parsed[document_id].filename if document_id in parsed else document_id,
                        document_id=document_id,
                    )
                    for index, document_id in enumerate(alternatives, start=1)
                ]
                options.append(ReviewOptionRequirement(
                    option_id=NONE_OF_THESE, kind="ESCAPE",
                    label="None of these is the right document",
                ))
                return ReviewRequirement(
                    scope="DOCUMENT", ui_mode="CHOICE", reason=assessment.review_reason or "wrong_doc_type",
                    field=None, side=None, target_role=target_role,
                    question=f"Which attachment is the {target_role} for this shipment?",
                    context_summary=(
                        f"The {target_role} could not be identified from the document contents."
                        + confirmed
                    ),
                    allowed_actions=("SELECT_OPTION",),
                    options=tuple(options),
                    source_document_ids=tuple(alternatives),
                )

    # A document-level problem is not a field question: no value a person types
    # can repair a missing, unreadable or wrong-type document. A role that is
    # merely unresolved was already offered as a CHOICE above.
    if document_issues:
        return ReviewRequirement(
            scope="DOCUMENT", ui_mode="ACKNOWLEDGE",
            reason=assessment.review_reason or "unreadable",
            field=None, side=None, target_role=None,
            question="This case needs action outside the system. Please acknowledge.",
            context_summary=_document_block_summary(assessment, roles, parsed) + confirmed,
            allowed_actions=("ACKNOWLEDGE",),
            source_document_ids=tuple(parsed),
            blocks_externally=True,
        )

    # Field-level uncertainty, within the lifetime two-field cap.
    targets = unresolved_field_targets(si_fields, bl_fields)
    document_level = {UncertaintyCause.DOCUMENT_LEVEL, UncertaintyCause.UNREADABLE_DOCUMENT}
    actionable = [
        (field, side) for field, side in targets
        if (si_fields if side == "SI" else bl_fields)[field].cause not in document_level
    ]

    distinct_fields = list(dict.fromkeys(list(prior_review_fields) + [f for f, _ in actionable]))
    if actionable and len(distinct_fields) <= MAX_DISTINCT_REVIEW_FIELDS:
        field, side = actionable[0]
        outcome = (si_fields if side == "SI" else bl_fields)[field]
        label = _FIELD_LABELS.get(field, field)
        explanation = _CAUSE_EXPLANATION.get(
            outcome.cause or UncertaintyCause.MISSING_VALUE, "the value could not be established"
        )
        document_ids = tuple(
            document_id for document_id in (
                (roles.si if side == "SI" else roles.bl) if roles else None,
            ) if document_id
        )

        distinct_values = _distinct_alternatives(outcome)
        if len(distinct_values) >= 2:
            options = [
                ReviewOptionRequirement(
                    option_id=f"val_{index}", kind="VALUE",
                    label=candidate.raw.strip()[:120], value=candidate,
                )
                for index, candidate in enumerate(distinct_values, start=1)
            ]
            options.append(ReviewOptionRequirement(
                option_id=NONE_OF_THESE, kind="ESCAPE", label="None of these is correct",
            ))
            return ReviewRequirement(
                scope="FIELD", ui_mode="CHOICE", reason=assessment.review_reason or "unreadable",
                field=field, side=side, target_role=None,
                question=f"Which value is the {label} on the {side}?",
                context_summary=(
                    f"The {side} document supports more than one {label}. {explanation}."
                    + confirmed
                ),
                allowed_actions=("SELECT_OPTION",),
                options=tuple(options),
                source_document_ids=document_ids,
            )

        return ReviewRequirement(
            scope="FIELD", ui_mode="VALUE_INPUT", reason=assessment.review_reason or "missing_value",
            field=field, side=side, target_role=None,
            question=f"What is the {label} on the {side} document?",
            context_summary=(
                f"{explanation.capitalize()}. {outcome.detail}".strip()
                + " If the document does not show it, acknowledge instead of guessing."
                + confirmed
            ),
            allowed_actions=("PROVIDE_VALUE", "ACKNOWLEDGE"),
            source_document_ids=document_ids,
        )

    # Everything else is an external block.
    if len(distinct_fields) > MAX_DISTINCT_REVIEW_FIELDS:
        summary = (
            f"{len(distinct_fields)} distinct fields need human input, which exceeds the "
            f"limit of {MAX_DISTINCT_REVIEW_FIELDS} for one run."
        )
    else:
        summary = _document_block_summary(assessment, roles, parsed)

    return ReviewRequirement(
        scope="DOCUMENT", ui_mode="ACKNOWLEDGE", reason=assessment.review_reason or "unreadable",
        field=None, side=None, target_role=None,
        question="This case needs action outside the system. Please acknowledge.",
        context_summary=summary + confirmed,
        allowed_actions=("ACKNOWLEDGE",),
        source_document_ids=tuple(parsed),
        blocks_externally=True,
    )


def _distinct_alternatives(outcome: FieldOutcome) -> tuple[Candidate, ...]:
    """Competing candidates with genuinely different canonical values."""
    distinct: list[Candidate] = []
    for candidate in outcome.alternatives:
        if candidate.normalized is None:
            continue
        if any(candidate.normalized.equals(existing.normalized) for existing in distinct):
            continue
        distinct.append(candidate)
    return tuple(distinct)


def _document_block_summary(assessment: Assessment, roles: Optional[RoleResolution],
                            parsed: Mapping[str, ParsedDocument]) -> str:
    reason = assessment.review_reason
    if reason == "missing_attachment":
        return "A document required for the comparison was not supplied with the email."
    if reason == "wrong_doc_type":
        return ("An attachment that should be a shipping instruction or a draft bill of "
                "lading is a different kind of document.")
    if reason == "unreadable":
        image_only = any(
            d.code in ("IMAGE_ONLY_PAGE", "IMAGE_ONLY_DOCUMENT")
            for document in parsed.values() for d in document.diagnostics
        )
        if image_only:
            return ("A required document has no text layer — it is a scan. Text recognition "
                    "is not enabled, so its contents were not read.")
        return "A required document could not be read."
    return assessment.detail or "The comparison could not be completed automatically."


# ---------------------------------------------------------------------------
# The entry point
# ---------------------------------------------------------------------------

def analyze_case(snapshot: InputSnapshot, context: AnalysisContext,
                 services: IntelligenceServices) -> AutomatedAnalysis:
    """Classify, parse, assign roles, extract, ground, normalize and compare.

    Raises a typed processing error for a technical failure. Genuine document
    problems are returned as an assessment, never as an exception.
    """
    started = time.monotonic()
    config = context.config
    policy = config.numeric_locale_policy
    events: list[tuple[str, str]] = []
    diagnostics_pre: list[Diagnostic] = []
    ai_calls = 0

    registry = services.registries.get(snapshot.registry_kind)
    fallback_convention = registry.numeric_convention() if registry is not None else ""

    # 1. Classification over the current message.
    view = build_view(snapshot.subject, snapshot.body)
    model_allowed, model_block_reason = model_permitted_for(snapshot, config, services)
    if not model_allowed and model_block_reason and services.model is not None:
        diagnostics_pre.append(Diagnostic(
            "MODEL_NOT_USED", model_block_reason,
            {"registry": snapshot.registry_kind},
        ))
    # Charge the attempt budget before the call. Spending afterwards would let a
    # provider that times out repeatedly escape the limit entirely.
    model_for_classification = services.model if model_allowed else None
    if model_for_classification is not None and services.budget is not None:
        from .classification import classify_rules

        if classify_rules(view).category is None:
            services.budget.spend()
    outcome = classify(
        view,
        attachment_names=tuple(ref.filename for ref in snapshot.sources),
        model=model_for_classification,
    )
    ai_calls += outcome.ai_calls
    classification = outcome.result
    events.append(("EMAIL_CLASSIFIED",
                   f"Email classified as {classification.category} "
                   f"({classification.rule_id or classification.classified_by})"))
    for event in outcome.events:
        events.append(("AI_EXTRACTION_USED", event))

    # 2. Parse every present source.
    parsed, diagnostics = parse_snapshot(snapshot, context, services)
    diagnostics = diagnostics_pre + list(diagnostics)
    for document in parsed.values():
        events.append(("DOCUMENT_PARSED",
                       f"Parsed {document.filename} with {document.parser_name} "
                       f"{document.parser_version} ({document.status.value})"))

    # Non-BL categories settle without comparison.
    if classification.category != "BL_COMPARISON":
        assessment = roll_up(classification.category or "GENERAL", (), ())
        return AutomatedAnalysis(
            category=classification.category,
            classified_by=classification.classified_by,
            classification_reason=classification.reason,
            documents=_document_refs(snapshot, parsed, None),
            comparisons=(), assessment=assessment, review=None,
            unresolved_targets=(), roles=None, parsed=parsed,
            ai_calls=ai_calls,
            processing_ms=int((time.monotonic() - started) * 1000),
            events=tuple(events), diagnostics=tuple(diagnostics),
            input_version=snapshot.input_version,
            config_version=config.config_identity(),
        )

    # 3. Content-backed roles.
    hints = {ref.document_id: filename_hint(ref.filename) for ref in snapshot.sources}
    roles = resolve_roles(list(parsed.values()), hints)
    document_issues = list(roles.issues)
    for ref in snapshot.missing_sources:
        document_issues.append("SOURCE_MISSING")
    if snapshot.missing_sources or not snapshot.sources:
        if "SI_MISSING" not in document_issues and "BL_MISSING" not in document_issues:
            document_issues.append("BL_MISSING")

    # 4. Extract, then 5. ground both sides.
    si_fields = extract_side(parsed.get(roles.si), "SI", policy=policy,
                             fallback_convention=fallback_convention)
    bl_fields = extract_side(parsed.get(roles.bl), "BL", policy=policy,
                             fallback_convention=fallback_convention)
    si_fields = _ground_side(si_fields, parsed, snapshot, policy, fallback_convention)
    bl_fields = _ground_side(bl_fields, parsed, snapshot, policy, fallback_convention)

    # 5b. Targeted model extraction for what the rules could not resolve. Every
    # proposal is re-verified through the same gates before it becomes a value.
    ai_assisted = 0
    for side, fields_map, document_id in (("SI", si_fields, roles.si),
                                          ("BL", bl_fields, roles.bl)):
        refreshed, calls, assisted, ai_events = ai_extract_side(
            parsed.get(document_id), side, fields_map,
            services=services, config=config, snapshot=snapshot,
            fallback_convention=fallback_convention,
        )
        ai_calls += calls
        ai_assisted += assisted
        events.extend(ai_events)
        if side == "SI":
            si_fields = refreshed
        else:
            bl_fields = refreshed

    # 6. Compare and roll up.
    comparisons = compare_all(si_fields, bl_fields)
    assessment = roll_up("BL_COMPARISON", comparisons, document_issues)
    events.append(("COMPARISON_COMPLETED",
                   f"Comparison completed: {assessment.status}"))

    review = build_review_requirement(
        assessment, roles, si_fields, bl_fields, comparisons, parsed,
        document_issues=tuple(document_issues),
    )
    targets = unresolved_field_targets(si_fields, bl_fields)

    return AutomatedAnalysis(
        category=classification.category,
        classified_by=classification.classified_by,
        classification_reason=classification.reason,
        documents=_document_refs(snapshot, parsed, roles),
        comparisons=comparisons,
        assessment=assessment,
        review=review,
        unresolved_targets=targets,
        roles=roles,
        parsed=parsed,
        si_fields=si_fields,
        bl_fields=bl_fields,
        ai_calls=ai_calls,
        ai_assisted_fields=ai_assisted,
        processing_ms=int((time.monotonic() - started) * 1000),
        events=tuple(events),
        diagnostics=tuple(diagnostics),
        input_version=snapshot.input_version,
        config_version=config.config_identity(),
    )


# Registry kinds whose content may be sent to an external provider only with
# explicit, source-specific consent.
CONSENT_REQUIRED_REGISTRIES = ("participant",)


class ParticipantContentNotAuthorized(PermanentProcessingError):
    """Sending this source's content to a provider is not authorized."""


def model_permitted_for(snapshot: InputSnapshot, config: IntelligenceConfig,
                        services: IntelligenceServices) -> tuple[bool, str]:
    """Whether this run's content may be sent to the configured provider.

    Two independent gates. ``INTELLIGENCE_AI_ENABLED`` says a provider exists;
    ``INTELLIGENCE_AI_ALLOW_PARTICIPANT_CONTENT`` says this *source's* content
    may leave the system. Read access to the corpus is not consent, so the
    second gate is checked even when the first is on.
    """
    if services.model is None:
        return False, "no model client is configured"
    if isinstance(services.model, ai_module.DisabledModelClient):
        return False, "the model is disabled"
    if snapshot.registry_kind in CONSENT_REQUIRED_REGISTRIES:
        if not config.ai.allow_participant_content:
            return False, (
                f"sending {snapshot.registry_kind} content to a provider is not "
                "authorized (INTELLIGENCE_AI_ALLOW_PARTICIPANT_CONTENT is off)"
            )
    return True, ""
