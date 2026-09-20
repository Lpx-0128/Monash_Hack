"""Human proposal validation and dependency recomputation (handoff §§19-20).

Person B owns HTTP, authentication and the durable commit. This module supplies
the deterministic half: whether a proposal is supported by the source, what the
accepted decision means, and what the operational state becomes once exactly one
accepted decision is applied.

The frozen machine assessment is never touched here.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field, replace
from decimal import Decimal, InvalidOperation
from typing import Mapping, Optional, Sequence

from .comparison import Assessment, FieldComparisonResult, compare_all, roll_up
from .config import (
    MAX_ACCEPTED_DECISIONS_PER_FIELD,
    MAX_ACCEPTED_DECISIONS_PER_FIELD_SIDE,
    MAX_DOCUMENT_CHOICES_PER_ROLE,
    MAX_DOCUMENT_CHOICES_PER_RUN,
)
from .extraction import extract_side
from .grounding import ground_candidate
from .ingestion import InputSnapshot
from .normalization import (
    detect_document_convention,
    normalize_party,
    normalize_port,
    parse_container_count,
    parse_gross_weight,
    parse_number,
)
from .pipeline import (
    AnalysisContext,
    ReviewRequirement,
    build_review_requirement,
    unresolved_field_targets,
)
from .policies import aliases
from .roles import resolve_roles, filename_hint
from .types import (
    CANONICAL_FIELDS,
    MAX_SAFE_INTEGER,
    NUMERIC_FIELDS,
    PARTY_FIELDS,
    PORT_FIELDS,
    Candidate,
    Derivation,
    Evidence,
    ExtractionMethod,
    FieldOutcome,
    NormalizedValue,
    ParsedDocument,
    UncertaintyCause,
)

VERSION = "recomputation-1.0.0"

# Contract error codes this module can require.
INVALID_VALUE = "INVALID_VALUE"
ACTION_NOT_ALLOWED = "ACTION_NOT_ALLOWED"
OPTION_NOT_FOUND = "OPTION_NOT_FOUND"
VALUE_NOT_FOUND_IN_DOCUMENT = "VALUE_NOT_FOUND_IN_DOCUMENT"
OVERRIDE_CONFIRMATION_REQUIRED = "OVERRIDE_CONFIRMATION_REQUIRED"
INVALID_CONFIRMATION = "INVALID_CONFIRMATION"

DOCUMENT_CONFIRMED = "DOCUMENT_CONFIRMED"
MANUAL_OVERRIDE = "MANUAL_OVERRIDE"


class ProposalRejected(Exception):
    """A typed rejection carrying the contract error code. No state is mutated."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class OverrideConfirmation:
    review_id: str
    run_id: str
    field: str
    side: str
    proposed_value: object
    confirmed: bool


@dataclass(frozen=True)
class DecisionProposal:
    """The structured request, after Person B has authenticated the caller."""

    review_id: str
    run_id: str
    action: str                   # SELECT_OPTION | PROVIDE_VALUE | ACKNOWLEDGE
    actor_id: str
    channel: str
    field: Optional[str] = None
    side: Optional[str] = None
    value: object = None
    option_id: Optional[str] = None
    user_message: Optional[str] = None
    override_confirmation: Optional[OverrideConfirmation] = None


@dataclass(frozen=True)
class ValidatedDecision:
    """An evidence-backed or explicitly overridden proposal, ready to persist."""

    decision_id: str
    review_id: str
    run_id: str
    action: str
    actor_id: str
    channel: str
    target_field: Optional[str] = None
    target_side: Optional[str] = None
    target_role: Optional[str] = None
    selected_document_id: Optional[str] = None
    canonical: Optional[Candidate] = None
    value_origin: Optional[str] = None
    grounded: bool = False
    escape: bool = False
    option_id: Optional[str] = None
    user_message: Optional[str] = None
    override_confirmation: Optional[OverrideConfirmation] = None
    input_version: str = ""
    config_version: str = ""


@dataclass
class WorkingAnalysis:
    """Current working state for one run. The machine snapshot stays separate."""

    snapshot: InputSnapshot
    parsed: Mapping[str, ParsedDocument]
    si_fields: dict[str, FieldOutcome]
    bl_fields: dict[str, FieldOutcome]
    roles: object
    category: str
    machine_assessment: Assessment
    machine_comparisons: tuple[FieldComparisonResult, ...]
    document_issues: tuple[str, ...] = ()
    accepted_decisions: tuple[ValidatedDecision, ...] = ()
    review_field_history: tuple[str, ...] = ()
    fallback_convention: str = ""

    def side_fields(self, side: str) -> dict[str, FieldOutcome]:
        return self.si_fields if side == "SI" else self.bl_fields


@dataclass(frozen=True)
class OperationalAnalysis:
    """The applied result. It never replaces the machine assessment."""

    comparisons: tuple[FieldComparisonResult, ...]
    outcome: Assessment
    workflow: str                     # COMPLETED | AWAITING_HUMAN | BLOCKED_EXTERNAL
    follow_up: str                    # NONE | CORRECTION_REQUIRED | AWAIT_EXTERNAL
    final_status: str
    final_defect_fields: tuple[str, ...]
    review: Optional[ReviewRequirement]
    unresolved_targets: tuple[tuple[str, str], ...]
    state: Optional[WorkingAnalysis] = None
    events: tuple[tuple[str, str], ...] = ()


# ---------------------------------------------------------------------------
# Typed user input
# ---------------------------------------------------------------------------

def parse_user_value(field: str, value: object) -> NormalizedValue:
    """Parse a typed human value as canonical user input.

    Numeric weight is kilograms in unambiguous dot-decimal notation. A bool, list
    or object masquerading as a scalar is rejected, as is a non-finite,
    non-positive or out-of-range number.
    """
    if isinstance(value, bool) or isinstance(value, (list, dict, tuple, set)):
        raise ProposalRejected(INVALID_VALUE, "the submitted value is not a scalar")
    if value is None:
        raise ProposalRejected(INVALID_VALUE, "no value was submitted")

    if field in PARTY_FIELDS or field in PORT_FIELDS:
        if not isinstance(value, str) or not value.strip():
            raise ProposalRejected(INVALID_VALUE, "a text value is required for this field")
        text = normalize_party(value) if field in PARTY_FIELDS else normalize_port(value)
        if not text:
            raise ProposalRejected(INVALID_VALUE, "the submitted text normalizes to nothing")
        return NormalizedValue.of_text(text)

    if field == "container_count":
        number = _decimal_from_user(value)
        if number != number.to_integral_value():
            raise ProposalRejected(INVALID_VALUE, "a container count must be a whole number")
        count = int(number)
        if count <= 0:
            raise ProposalRejected(INVALID_VALUE, "a container count must be positive")
        if count > MAX_SAFE_INTEGER:
            raise ProposalRejected(INVALID_VALUE, "the container count is out of range")
        return NormalizedValue.of_integer(Decimal(count))

    if field == "gross_weight_kg":
        number = _decimal_from_user(value)
        if number <= 0:
            raise ProposalRejected(INVALID_VALUE, "a gross weight must be positive")
        if number > Decimal(MAX_SAFE_INTEGER):
            raise ProposalRejected(INVALID_VALUE, "the gross weight is out of range")
        candidate = NormalizedValue.of_decimal(number)
        try:
            candidate.to_wire()
        except Exception as exc:  # unsupported precision is refused, never rounded
            raise ProposalRejected(INVALID_VALUE, str(exc)) from exc
        return candidate

    raise ProposalRejected(INVALID_VALUE, f"{field!r} is not a canonical field")


def _decimal_from_user(value: object) -> Decimal:
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        # A float has already lost exactness; require its shortest repr to be exact.
        return Decimal(repr(value))
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ProposalRejected(INVALID_VALUE, "no value was submitted")
        # Typed input uses unambiguous dot-decimal notation.
        parsed = parse_number(text, policy="en")
        if parsed.ambiguous or not parsed.ok:
            raise ProposalRejected(
                INVALID_VALUE,
                "enter the number using a dot as the decimal mark and no thousands separators",
            )
        return parsed.value
    raise ProposalRejected(INVALID_VALUE, "the submitted value is not a number")


# ---------------------------------------------------------------------------
# Finding source support for a human proposal
# ---------------------------------------------------------------------------

def admissible_interpretations(field: str, raw: str, label: Optional[str],
                               convention: str) -> list[NormalizedValue]:
    """Every reading of a source value the document genuinely admits.

    For a lone separator, both the grouping and the decimal reading are
    admissible: the automated pass refuses to choose, but a person selecting one
    of them is confirming a reading the document really supports.
    """
    readings: list[NormalizedValue] = []

    if field in PARTY_FIELDS:
        text = normalize_party(raw)
        if text:
            readings.append(NormalizedValue.of_text(text))
        return readings

    if field in PORT_FIELDS:
        text = normalize_port(raw)
        if text:
            readings.append(NormalizedValue.of_text(text))
        return readings

    if field == "container_count":
        for ambiguous in (aliases.is_ambiguous_count_label(label), False):
            parsed = parse_container_count(raw, label_is_ambiguous=ambiguous)
            if parsed.ok:
                readings.append(NormalizedValue.of_integer(Decimal(parsed.value)))
        return _dedupe(readings)

    if field == "gross_weight_kg":
        label_kg = aliases.label_declares_kg(label)
        label_tonnes = aliases.label_declares_tonnes(label)
        for policy in ("auto", "en", "eu"):
            parsed = parse_gross_weight(
                raw, label=label, label_kg=label_kg, label_tonnes=label_tonnes,
                policy=policy, convention=convention,
            )
            if parsed.value is not None:
                readings.append(NormalizedValue.of_decimal(parsed.value))
        if not readings:
            # No unit anywhere: the digits are still in the document, and the
            # person supplies the unit. Both kg and tonne readings are admissible.
            for policy in ("en", "eu"):
                parsed = parse_gross_weight(raw, label=label, label_kg=True,
                                            policy=policy, convention=convention)
                if parsed.value is not None:
                    readings.append(NormalizedValue.of_decimal(parsed.value))
                    readings.append(NormalizedValue.of_decimal(parsed.value * 1000))
        return _dedupe(readings)

    return readings


def _dedupe(values: Sequence[NormalizedValue]) -> list[NormalizedValue]:
    unique: list[NormalizedValue] = []
    for value in values:
        if not any(value.equals(existing) for existing in unique):
            unique.append(value)
    return unique


def find_document_support(field: str, side: str, document: ParsedDocument,
                          proposed: NormalizedValue, *, policy: str,
                          convention: str) -> Optional[Candidate]:
    """Locate evidence in the target document that supports the proposed value.

    Returns a candidate that has passed G1-G3, or ``None``. A selectable option
    never bypasses these checks.
    """
    document_convention = detect_document_convention(document.text) or convention
    for block in document.blocks:
        if aliases.match_field(block.label) != field:
            continue
        readings = admissible_interpretations(field, block.value_text, block.label,
                                              document_convention)
        if not any(proposed.equals(reading) for reading in readings):
            continue
        flags = ["HUMAN_CONFIRMED_READING"]
        unit_evidence = None
        if field == "gross_weight_kg" and aliases.label_declares_kg(block.label):
            unit_evidence = Evidence(document.document_id, block.label_locator, block.label) \
                if block.label_locator else None
            flags.append("UNIT_FROM_LABEL")
        candidate = Candidate(
            field=field, side=side, document_id=document.document_id,
            raw=block.value_text, label_text=block.label,
            evidence=(Evidence(document.document_id, block.value_locator, block.value_text),),
            derivation=Derivation.DIRECT, method=ExtractionMethod.HUMAN,
            normalized=proposed, flags=tuple(flags), unit_evidence=unit_evidence,
        )
        # G1 and G2 must still pass. G3 is satisfied by construction here — the
        # proposal equals one of the document's own admissible readings — so it
        # is checked separately rather than through the automated derivation.
        from .grounding import check_g1, check_g2
        if check_g1(candidate, document).passed and check_g2(candidate, document).passed:
            return candidate
    return None


# ---------------------------------------------------------------------------
# Budget ledger
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BudgetState:
    """What the lifetime ledger permits next. Person B persists the ledger."""

    distinct_review_fields: tuple[str, ...] = ()
    accepted_per_field: Mapping[str, int] = dc_field(default_factory=dict)
    accepted_per_field_side: Mapping[tuple, int] = dc_field(default_factory=dict)
    document_choices_per_role: Mapping[str, int] = dc_field(default_factory=dict)

    @staticmethod
    def from_decisions(decisions: Sequence[ValidatedDecision],
                       review_fields: Sequence[str] = ()) -> "BudgetState":
        per_field: dict[str, int] = {}
        per_field_side: dict[tuple, int] = {}
        per_role: dict[str, int] = {}
        for decision in decisions:
            if decision.target_field:
                per_field[decision.target_field] = per_field.get(decision.target_field, 0) + 1
                key = (decision.target_field, decision.target_side)
                per_field_side[key] = per_field_side.get(key, 0) + 1
            if decision.target_role:
                per_role[decision.target_role] = per_role.get(decision.target_role, 0) + 1
        return BudgetState(
            distinct_review_fields=tuple(dict.fromkeys(review_fields)),
            accepted_per_field=per_field,
            accepted_per_field_side=per_field_side,
            document_choices_per_role=per_role,
        )

    def allows_field(self, field: str, side: str) -> bool:
        if self.accepted_per_field.get(field, 0) >= MAX_ACCEPTED_DECISIONS_PER_FIELD:
            return False
        if self.accepted_per_field_side.get((field, side), 0) >= MAX_ACCEPTED_DECISIONS_PER_FIELD_SIDE:
            return False
        return True

    def allows_document_choice(self, role: str) -> bool:
        if self.document_choices_per_role.get(role, 0) >= MAX_DOCUMENT_CHOICES_PER_ROLE:
            return False
        if sum(self.document_choices_per_role.values()) >= MAX_DOCUMENT_CHOICES_PER_RUN:
            return False
        return True


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_human_proposal(proposal: DecisionProposal, review: ReviewRequirement,
                            state: WorkingAnalysis, context: AnalysisContext,
                            *, decision_id: Optional[str] = None) -> ValidatedDecision:
    """Return an evidence-backed or explicitly overridden decision, or raise.

    Raising never mutates state and never consumes an accepted-decision budget.
    """
    if proposal.action not in review.allowed_actions:
        raise ProposalRejected(ACTION_NOT_ALLOWED,
                               f"{proposal.action} is not allowed for this review")

    identity = dict(
        decision_id=decision_id or context.next_id("dec"),
        review_id=proposal.review_id, run_id=proposal.run_id, action=proposal.action,
        actor_id=proposal.actor_id, channel=proposal.channel,
        user_message=proposal.user_message,
        input_version=state.snapshot.input_version,
        config_version=context.config.config_identity(),
    )

    if proposal.action == "ACKNOWLEDGE":
        return ValidatedDecision(escape=True, **identity)

    if proposal.action == "SELECT_OPTION":
        return _validate_option(proposal, review, state, context, identity)

    return _validate_value(proposal, review, state, context, identity)


def _validate_option(proposal, review, state, context, identity) -> ValidatedDecision:
    if not proposal.option_id:
        raise ProposalRejected(OPTION_NOT_FOUND, "no option was selected")
    option = next((o for o in review.options if o.option_id == proposal.option_id), None)
    if option is None:
        raise ProposalRejected(OPTION_NOT_FOUND,
                               f"option {proposal.option_id!r} does not belong to this review")
    if option.kind == "ESCAPE":
        return ValidatedDecision(escape=True, option_id=option.option_id, **identity)

    if option.kind == "DOCUMENT":
        role = review.target_role
        if role not in ("SI", "BL"):
            raise ProposalRejected(ACTION_NOT_ALLOWED,
                                   "this review does not target a document role")
        other = state.roles.bl if role == "SI" else state.roles.si
        if option.document_id == other:
            raise ProposalRejected(
                ACTION_NOT_ALLOWED,
                "that document already occupies the opposite role",
            )
        return ValidatedDecision(target_role=role, selected_document_id=option.document_id,
                                 option_id=option.option_id, **identity)

    # A VALUE option is a server-owned candidate; it still passes the gates.
    if review.field is None or review.side is None:
        raise ProposalRejected(ACTION_NOT_ALLOWED, "this review does not target a field")
    candidate = option.value
    if candidate is None or candidate.normalized is None:
        raise ProposalRejected(OPTION_NOT_FOUND, "the selected option carries no value")
    return _finalize_field_decision(
        proposal, review, state, context, identity,
        proposed=candidate.normalized, option_id=option.option_id,
    )


def _validate_value(proposal, review, state, context, identity) -> ValidatedDecision:
    if review.field is None or review.side is None:
        raise ProposalRejected(ACTION_NOT_ALLOWED, "this review does not accept a typed value")
    if proposal.field != review.field or proposal.side != review.side:
        raise ProposalRejected(
            ACTION_NOT_ALLOWED,
            "the submitted field and side must match the review exactly",
        )
    proposed = parse_user_value(review.field, proposal.value)
    return _finalize_field_decision(proposal, review, state, context, identity,
                                    proposed=proposed)


def _finalize_field_decision(proposal, review, state, context, identity, *,
                             proposed: NormalizedValue,
                             option_id: Optional[str] = None) -> ValidatedDecision:
    field, side = review.field, review.side
    document_id = state.roles.si if side == "SI" else state.roles.bl
    document = state.parsed.get(document_id) if document_id else None

    supported = None
    if document is not None:
        supported = find_document_support(
            field, side, document, proposed,
            policy=context.config.numeric_locale_policy,
            convention=state.fallback_convention,
        )

    confirmation = proposal.override_confirmation
    if supported is not None and confirmation is None:
        return ValidatedDecision(
            target_field=field, target_side=side, canonical=supported,
            value_origin=DOCUMENT_CONFIRMED, grounded=True, option_id=option_id,
            **identity,
        )

    # Unsupported, or an override was explicitly requested.
    if confirmation is None:
        raise ProposalRejected(
            VALUE_NOT_FOUND_IN_DOCUMENT,
            "that value is not supported by the source document. The review stays open; "
            "resubmit with an explicit override confirmation to record it anyway.",
        )

    _check_confirmation(confirmation, proposal, review, proposed)

    override = Candidate(
        field=field, side=side, document_id=document_id or "",
        raw=str(proposal.value if proposal.value is not None else ""),
        label_text=None,
        # Evidence may record conflicting source context, but must not claim to
        # support the overridden value, so an override carries none.
        evidence=(),
        derivation=Derivation.HUMAN_INPUT, method=ExtractionMethod.HUMAN,
        normalized=proposed, flags=("MANUAL_OVERRIDE",),
    )
    return ValidatedDecision(
        target_field=field, target_side=side, canonical=override,
        value_origin=MANUAL_OVERRIDE, grounded=False, option_id=option_id,
        override_confirmation=confirmation, **identity,
    )


def _check_confirmation(confirmation: OverrideConfirmation, proposal: DecisionProposal,
                        review: ReviewRequirement, proposed: NormalizedValue) -> None:
    """The confirmation must bind the exact review, run, target and canonical value."""
    if confirmation.confirmed is not True:
        raise ProposalRejected(INVALID_CONFIRMATION, "the override was not confirmed")
    if confirmation.review_id != proposal.review_id or confirmation.run_id != proposal.run_id:
        raise ProposalRejected(INVALID_CONFIRMATION,
                               "the confirmation is bound to a different review or run")
    if confirmation.field != review.field or confirmation.side != review.side:
        raise ProposalRejected(INVALID_CONFIRMATION,
                               "the confirmation is bound to a different field or side")
    try:
        confirmed_value = parse_user_value(review.field, confirmation.proposed_value)
    except ProposalRejected as exc:
        raise ProposalRejected(INVALID_CONFIRMATION,
                               f"the confirmed value is not usable: {exc.message}") from exc
    if not confirmed_value.equals(proposed):
        # Changing the value invalidates the confirmation.
        raise ProposalRejected(INVALID_CONFIRMATION,
                               "the confirmation names a different value than the one submitted")


# ---------------------------------------------------------------------------
# Application and dependency recomputation
# ---------------------------------------------------------------------------

def apply_validated_decision(decision: ValidatedDecision, state: WorkingAnalysis,
                             context: AnalysisContext) -> OperationalAnalysis:
    """Apply exactly one accepted decision and recompute what depends on it."""
    events: list[tuple[str, str]] = []
    si_fields = dict(state.si_fields)
    bl_fields = dict(state.bl_fields)
    roles = state.roles
    document_issues = tuple(state.document_issues)
    review_field_history = list(state.review_field_history)

    if decision.escape:
        events.append(("DECISION_APPLIED",
                       "Acknowledged; the case is blocked pending external action"))
        comparisons = compare_all(si_fields, bl_fields)
        return OperationalAnalysis(
            comparisons=comparisons,
            outcome=Assessment("NEEDS_REVIEW", state.machine_assessment.review_reason,
                               False, ()),
            workflow="BLOCKED_EXTERNAL", follow_up="AWAIT_EXTERNAL",
            final_status="NEEDS_REVIEW", final_defect_fields=(),
            review=None,
            unresolved_targets=unresolved_field_targets(si_fields, bl_fields),
            state=replace(state, accepted_decisions=state.accepted_decisions + (decision,)),
            events=tuple(events),
        )

    if decision.target_role and decision.selected_document_id:
        si_id = decision.selected_document_id if decision.target_role == "SI" else roles.si
        bl_id = decision.selected_document_id if decision.target_role == "BL" else roles.bl
        roles = replace(roles, si=si_id, bl=bl_id)
        # Every value on the changed side is invalidated and re-derived.
        side = decision.target_role
        refreshed = extract_side(
            state.parsed.get(decision.selected_document_id), side,
            policy=context.config.numeric_locale_policy,
            fallback_convention=state.fallback_convention,
        )
        if side == "SI":
            si_fields = dict(refreshed)
        else:
            bl_fields = dict(refreshed)
        document_issues = tuple(
            issue for issue in document_issues if not issue.startswith(f"{side}_")
        )
        events.append(("DECISION_APPLIED",
                       f"{side} document reassigned; all {side} values re-derived"))

    elif decision.target_field and decision.canonical is not None:
        field, side = decision.target_field, decision.target_side
        fields = si_fields if side == "SI" else bl_fields
        fields[field] = FieldOutcome(field=field, side=side, value=decision.canonical)
        review_field_history.append(field)
        events.append(("DECISION_APPLIED",
                       f"{field} on the {side} set from the accepted decision"))
        # Same-as-consignee: a consignee correction invalidates that side's
        # derived notify party, and only that side's.
        if field == "consignee":
            recomputed = _recompute_notify_party(fields, decision, side)
            if recomputed is not None:
                fields["notify_party"] = recomputed
                events.append(("DECISION_APPLIED",
                               f"{side} notify party recomputed from its consignee reference"))

    comparisons = compare_all(si_fields, bl_fields)
    outcome = roll_up(state.category, comparisons, document_issues)

    budget = BudgetState.from_decisions(
        state.accepted_decisions + (decision,), review_field_history
    )
    next_review = _next_review(outcome, roles, si_fields, bl_fields, comparisons,
                               state.parsed, document_issues, review_field_history, budget)

    new_state = replace(
        state, si_fields=si_fields, bl_fields=bl_fields, roles=roles,
        document_issues=document_issues,
        accepted_decisions=state.accepted_decisions + (decision,),
        review_field_history=tuple(review_field_history),
    )
    targets = unresolved_field_targets(si_fields, bl_fields)

    if next_review is not None and not next_review.blocks_externally:
        return OperationalAnalysis(
            comparisons=comparisons, outcome=outcome, workflow="AWAITING_HUMAN",
            follow_up="NONE", final_status="NEEDS_REVIEW", final_defect_fields=(),
            review=next_review, unresolved_targets=targets, state=new_state,
            events=tuple(events),
        )
    if next_review is not None:
        return OperationalAnalysis(
            comparisons=comparisons, outcome=outcome, workflow="BLOCKED_EXTERNAL",
            follow_up="AWAIT_EXTERNAL", final_status="NEEDS_REVIEW",
            final_defect_fields=(), review=next_review, unresolved_targets=targets,
            state=new_state, events=tuple(events),
        )

    final_status = outcome.status
    defects = outcome.defect_fields
    events.append(("CASE_COMPLETED", f"Case completed with {final_status}"))
    return OperationalAnalysis(
        comparisons=comparisons, outcome=outcome, workflow="COMPLETED",
        follow_up="CORRECTION_REQUIRED" if final_status == "MISMATCH" else "NONE",
        final_status=final_status, final_defect_fields=defects, review=None,
        unresolved_targets=targets, state=new_state, events=tuple(events),
    )


def _recompute_notify_party(fields: dict, decision: ValidatedDecision,
                            side: str) -> Optional[FieldOutcome]:
    """Re-derive a "same as consignee" notify party from the corrected consignee.

    The deterministic derivation method is recorded, while the override's
    ungrounded lineage and its inherited confirmation are retained. No new
    confirmation is invented for the dependent field.
    """
    current = fields.get("notify_party")
    if current is None or current.value is None:
        return None
    if current.value.derivation is not Derivation.REFERENCE:
        return None
    consignee = fields["consignee"].value
    if consignee is None or consignee.normalized is None:
        return None

    inherits_override = decision.value_origin == MANUAL_OVERRIDE
    derived = Candidate(
        field="notify_party", side=side, document_id=current.value.document_id,
        raw=current.value.raw, label_text=current.value.label_text,
        evidence=current.value.evidence if not inherits_override else (),
        derivation=Derivation.REFERENCE,
        method=ExtractionMethod.RULE,   # the derivation itself stays deterministic
        normalized=consignee.normalized, reference_field="consignee",
        flags=tuple(dict.fromkeys(
            current.value.flags + (("INHERITED_MANUAL_OVERRIDE",) if inherits_override else ())
        )),
    )
    return FieldOutcome(field="notify_party", side=side, value=derived)


def _next_review(outcome: Assessment, roles, si_fields, bl_fields, comparisons,
                 parsed, document_issues, review_field_history,
                 budget: BudgetState) -> Optional[ReviewRequirement]:
    """The next allowed question, or an external block when the budget is spent."""
    requirement = build_review_requirement(
        outcome, roles, si_fields, bl_fields, comparisons, parsed,
        prior_review_fields=review_field_history,
        document_issues=document_issues,
    )
    if requirement is None or requirement.blocks_externally:
        return requirement
    if requirement.scope == "FIELD":
        if not budget.allows_field(requirement.field, requirement.side):
            return _external_block(requirement, "the review budget for this field is exhausted")
    if requirement.scope == "DOCUMENT" and requirement.target_role:
        if not budget.allows_document_choice(requirement.target_role):
            return _external_block(requirement,
                                   "the document-choice budget for this run is exhausted")
    return requirement


def _external_block(requirement: ReviewRequirement, why: str) -> ReviewRequirement:
    return ReviewRequirement(
        scope="DOCUMENT", ui_mode="ACKNOWLEDGE", reason=requirement.reason,
        field=None, side=None, target_role=None,
        question="This case needs action outside the system. Please acknowledge.",
        context_summary=f"{why}. {requirement.context_summary}",
        allowed_actions=("ACKNOWLEDGE",),
        source_document_ids=requirement.source_document_ids,
        blocks_externally=True,
    )


def working_state_from_analysis(analysis, snapshot: InputSnapshot,
                                fallback_convention: str = "") -> WorkingAnalysis:
    """Build the mutable working state that follows a frozen automated pass."""
    return WorkingAnalysis(
        snapshot=snapshot,
        parsed=analysis.parsed,
        si_fields=dict(analysis.si_fields),
        bl_fields=dict(analysis.bl_fields),
        roles=analysis.roles,
        category=analysis.category or "GENERAL",
        machine_assessment=analysis.assessment,
        machine_comparisons=analysis.comparisons,
        document_issues=tuple(analysis.roles.issues) if analysis.roles else (),
        fallback_convention=fallback_convention,
    )
