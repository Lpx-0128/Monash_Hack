"""Email intent classification (handoff §10).

Ordered, explicit rules over the current message plus its subject, with a bounded
model fallback when the rules cannot support an intent. The category is never
decided by sender identity, filename suffix, email number, attachment count or a
single keyword.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from typing import Optional, Sequence

VERSION = "classification-1.0.0"

CATEGORIES = ("BL_COMPARISON", "SI_REQUEST", "INVOICE_QUERY", "GENERAL", "SPAM")

# A quoted-thread boundary. Recognized conservatively: an aggressive regex here
# would delete the only substantive request in the message.
_QUOTE_BOUNDARY = re.compile(
    r"^\s*(?:"
    r"-{2,}\s*original message\s*-{2,}"
    r"|from:\s.+"
    r"|on .{0,80}\bwrote:\s*$"
    r"|_{5,}\s*$"
    r"|>{1,}\s"
    r")",
    re.IGNORECASE | re.MULTILINE,
)

# External-sender banners carry no intent.
_BANNER = re.compile(
    r"^\s*(?:\[?\s*(?:external|caution|warning)\b.{0,160})$",
    re.IGNORECASE | re.MULTILINE,
)

_SIGNATURE = re.compile(
    r"^\s*(?:best regards|kind regards|regards|thanks(?: and regards)?|sincerely|br)\s*[,.]?\s*$",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True)
class ClassificationView:
    """The text a classifier may reason over, with quoted history kept separate."""

    current_message: str
    quoted_history: str
    subject: str

    @property
    def intent_text(self) -> str:
        return f"{self.subject}\n{self.current_message}"


@dataclass(frozen=True)
class ClassificationResult:
    category: Optional[str]
    classified_by: Optional[str]          # DETERMINISTIC | AI
    reason: str = ""
    rule_id: str = ""
    confidence: Optional[float] = None    # advisory only; never proof
    unresolved: bool = False
    detail: str = ""
    evidence_quotes: tuple[str, ...] = ()


def build_view(subject: str, body: str) -> ClassificationView:
    """Split the latest request from quoted history and strip banners/signatures."""
    text = (body or "").replace("\r\n", "\n").replace("\r", "\n")

    boundary = _QUOTE_BOUNDARY.search(text)
    if boundary is not None and boundary.start() > 0:
        current, quoted = text[:boundary.start()], text[boundary.start():]
    elif boundary is not None:
        # The message opens with quoted material; keep everything as current text
        # rather than discarding the only content available.
        current, quoted = text, ""
    else:
        current, quoted = text, ""

    cleaned = _BANNER.sub("", current)
    signature = _SIGNATURE.search(cleaned)
    if signature is not None and cleaned[:signature.start()].strip():
        cleaned = cleaned[:signature.start()]

    if not cleaned.strip():
        cleaned = current

    return ClassificationView(
        current_message=cleaned.strip(),
        quoted_history=quoted.strip(),
        subject=(subject or "").strip(),
    )


# --- rule vocabulary -------------------------------------------------------

_COMPARE_REQUEST = re.compile(
    r"\b(?:"
    r"compare\s+(?:the\s+)?(?:si|s\.i\.|shipping\s+instructions?)"
    r"|(?:check|verify|confirm|review|cross[- ]?check)\s+(?:the\s+)?(?:attached\s+)?"
    r"(?:draft\s+)?(?:b/?l|bill\s+of\s+lading)\s+(?:against|vs\.?|versus|with|to)\s+"
    r"(?:the\s+)?(?:si|shipping\s+instructions?)"
    r"|compare\s+(?:the\s+)?(?:attached\s+)?(?:documents?|si\s+and\s+(?:the\s+)?(?:draft\s+)?b/?l)"
    r"|(?:si|shipping\s+instructions?)\s+(?:and|vs\.?|versus|against)\s+"
    r"(?:the\s+)?(?:draft\s+)?(?:b/?l|bill\s+of\s+lading)"
    r"|verify\s+(?:the\s+)?(?:shipment\s+)?details\s+(?:agree|match)"
    r"|confirm\s+(?:the\s+)?(?:b/?l|bill\s+of\s+lading)\s+is\s+in\s+order"
    r")",
    re.IGNORECASE,
)
_CHECK_AND_CONFIRM = re.compile(
    r"\b(?:check|verify|confirm)\b.{0,60}\b(?:details?|discrepanc\w+|figures?|particulars?)\b",
    re.IGNORECASE,
)
_SI_REQUEST = re.compile(
    r"\b(?:"
    r"please\s+(?:find|see)\s+(?:the\s+|our\s+|attached\s+)*(?:new\s+|revised\s+|updated\s+)?"
    r"shipping\s+instructions?\b"
    r"|(?:new|revised|updated)\s+shipping\s+instructions?\s+(?:for|below|attached|follow)\b"
    r"|(?:issue|prepare|draw\s+up|raise|send)\s+(?:the\s+|a\s+)?(?:draft\s+)?"
    r"(?:b/?l|bill\s+of\s+lading)\s+(?:based\s+on|per|from|using)\b"
    r"|kindly\s+prepare\s+the\s+draft\b"
    r"|below\s+are\s+the\s+shipping\s+instructions?\b"
    r")",
    re.IGNORECASE,
)

# "Please assist to send the draft BL ... for checking": the sender is asking for
# a draft to be produced, and no BL exists yet. Organizer mapping for this shape
# is unresolved, so the conservative selected policy is recorded with the result.
_DRAFT_BL_REQUESTED = re.compile(
    r"\b(?:please\s+)?(?:assist\s+to\s+)?(?:send|issue|share|provide|forward)\s+"
    r"(?:me\s+|us\s+)?(?:the\s+|a\s+)?draft\s+(?:b/?l|bill\s+of\s+lading)\b",
    re.IGNORECASE,
)

# An inline shipment block supplied in the message body, e.g. "POL: ... POD: ...".
_INLINE_SHIPMENT_BLOCK = re.compile(
    r"^\s*(?:pol|port\s+of\s+loading|pod|port\s+of\s+discharge|shipper|consignee|notify)\s*:",
    re.IGNORECASE | re.MULTILINE,
)
_INVOICE_QUERY = re.compile(
    r"\b(?:"
    r"invoice\s+(?:amount|total|number|query|discrepanc\w+|question)"
    r"|(?:query|question|clarif\w+|dispute)\s+(?:on|about|regarding)\s+(?:the\s+)?invoice"
    r"|(?:freight|charge|billing|payment)\s+(?:breakdown|clarification|query|discrepanc\w+)"
    r"|overcharg\w+|double[- ]?bill\w*|remittance\s+advice"
    r"|why\s+(?:were|was|are|is)\s+(?:we|i)\s+(?:charged|billed)"
    r"|\bd\s*&\s*d\b|detention\s+charges?|demurrage"
    r"|confirm\s+the\s+amount\s+before\s+(?:we\s+)?release\s+payment"
    r"|(?:missing|outstanding)\s+gr\b.{0,60}\binvoice\b"
    r"|\binvoice\b.{0,60}(?:missing|outstanding)\s+gr\b"
    r"|proceed\s+with\s+billing|arrange\s+to\s+post\s+the\s+gr"
    r")",
    re.IGNORECASE,
)
# Scam and promotional markers. Each is a phrase, not a bare keyword, so an
# ordinary operational mail mentioning "payment" or "offer" is not caught.
_SPAM = re.compile(
    r"(?:"
    r"\bunsubscribe\b|click\s+here\s+to\s+(?:claim|win|verify)"
    # advance-fee fraud
    r"|business\s+proposal\s+involving\s+(?:usd|eur|gbp|\$)"
    r"|reply\s+with\s+your\s+bank\s+details"
    r"|next\s+of\s+kin|transfer\s+of\s+funds\s+to\s+your\s+account"
    # credential phishing
    r"|verify\s+your\s+(?:account|password|credentials|mailbox)"
    r"|mailbox\s+has\s+exceeded\s+its\s+storage\s+limit"
    r"|to\s+avoid\s+(?:deactivation|suspension|account\s+closure)"
    # parcel / customs fee scam
    r"|could\s+not\s+be\s+delivered\s+due\s+to\s+unpaid"
    r"|confirm\s+payment\s+within\s+\d+\s+hours"
    # prize bait
    r"|you(?:'ve|\s+have)\s+won\b|congratulations[,!]?\s+you(?:'ve| have)\s+won"
    # promotional bait
    r"|limited[- ]time\s+offer|act\s+now\b|risk[- ]free\s+trial"
    r"|guaranteed\s+\d+\s*%\s+returns?|(?:bitcoin|crypto)\s+investment"
    r"|\d{2,3}\s*%\s+off\b|this\s+week\s+only|one\s+weird\s+trick"
    r"|seo\s+services|boost\s+your\s+(?:sales|ranking|revenue)"
    r")",
    re.IGNORECASE,
)

# Operational traffic: status reports, reminders, notifications and announcements
# that request no comparison. Matched positively so they do not reach the default.
_GENERAL_OPERATIONAL = re.compile(
    r"(?:"
    r"berthing\s+report|update\s+summary|outstanding\s+(?:bl|list|items)"
    r"|list\s+of\s+outstanding\b|pending\s+items\b"
    r"|this\s+is\s+an\s+automated\s+notification|no\s+action\s+required"
    r"|has\s+completed\s+successfully"
    r"|\breminder\s*:|kindly\s+(?:action|note)\b"
    r"|office\s+(?:resumes|will\s+be\s+closed)|happy\s+and\s+prosperous"
    r"|public\s+holiday|out\s+of\s+office"
    r"|(?:vessel|schedule)\s+(?:update|change|delay|omission)"
    r")",
    re.IGNORECASE,
)

# Mentions that are context, not a requested action.
_BL_MENTION = re.compile(r"\b(?:b/?l|bill\s+of\s+lading)\b", re.IGNORECASE)
_SI_MENTION = re.compile(r"\b(?:s\.?i\.?|shipping\s+instructions?)\b", re.IGNORECASE)
_INVOICE_MENTION = re.compile(r"\binvoices?\b", re.IGNORECASE)


def _quote(text: str, match: re.Match) -> str:
    start = max(0, match.start() - 40)
    end = min(len(text), match.end() + 40)
    return text[start:end].strip()


def classify_rules(view: ClassificationView) -> ClassificationResult:
    """Ordered deterministic rules. Returns an unresolved result when none fires."""
    text = view.intent_text

    spam = _SPAM.search(text)
    if spam:
        return ClassificationResult("SPAM", "DETERMINISTIC", "unsolicited or credential-harvesting content",
                                    rule_id="R-SPAM-1", evidence_quotes=(_quote(text, spam),))

    # A comparison request wins over a misleading subject such as "REQUEST BL DRAFT".
    compare = _COMPARE_REQUEST.search(text)
    if compare:
        return ClassificationResult("BL_COMPARISON", "DETERMINISTIC",
                                    "the message asks for the draft BL to be checked against the SI",
                                    rule_id="R-CMP-1", evidence_quotes=(_quote(text, compare),))

    both_documents = bool(_SI_MENTION.search(text)) and bool(_BL_MENTION.search(text))
    check = _CHECK_AND_CONFIRM.search(text)
    if both_documents and check:
        return ClassificationResult("BL_COMPARISON", "DETERMINISTIC",
                                    "both documents are named and the message asks for the details to be checked",
                                    rule_id="R-CMP-2", evidence_quotes=(_quote(text, check),))

    si_request = _SI_REQUEST.search(text)
    if si_request:
        return ClassificationResult("SI_REQUEST", "DETERMINISTIC",
                                    "the message supplies or requests shipping instructions for a new draft",
                                    rule_id="R-SI-1", evidence_quotes=(_quote(text, si_request),))

    inline_block = _INLINE_SHIPMENT_BLOCK.search(view.current_message)
    if inline_block and _SI_MENTION.search(text):
        return ClassificationResult("SI_REQUEST", "DETERMINISTIC",
                                    "the message carries an inline shipment block for a new instruction",
                                    rule_id="R-SI-2",
                                    evidence_quotes=(_quote(view.current_message, inline_block),))

    draft_requested = _DRAFT_BL_REQUESTED.search(text)
    if draft_requested:
        # Conservative selected policy; see docs/person-a-implementation.md.
        return ClassificationResult(
            "SI_REQUEST", "DETERMINISTIC",
            "the message asks for a draft BL to be produced; no draft is supplied to compare",
            rule_id="R-SI-3", unresolved=True,
            detail="conservative policy for 'send the draft BL for checking'; "
                   "organizer mapping for this shape is unresolved",
            evidence_quotes=(_quote(text, draft_requested),))

    invoice = _INVOICE_QUERY.search(text)
    if invoice:
        return ClassificationResult("INVOICE_QUERY", "DETERMINISTIC",
                                    "the message raises a billing or invoice question",
                                    rule_id="R-INV-1", evidence_quotes=(_quote(text, invoice),))

    operational = _GENERAL_OPERATIONAL.search(text)
    if operational:
        return ClassificationResult("GENERAL", "DETERMINISTIC",
                                    "an operational update or report with no comparison task requested",
                                    rule_id="R-GEN-1",
                                    evidence_quotes=(_quote(text, operational),))

    return ClassificationResult(None, None, unresolved=True,
                                detail="no intent rule matched the current message")


@dataclass
class ClassificationOutcome:
    """The classification plus what it cost and how it was reached."""

    result: ClassificationResult
    ai_calls: int = 0
    events: list[str] = dc_field(default_factory=list)


def classify(view: ClassificationView, *, attachment_names: Sequence[str] = (),
             model=None) -> ClassificationOutcome:
    """Rules first, then one bounded structured model call when they cannot decide.

    ``classified_by`` is ``AI`` only when the model materially chose the final
    category. A provider failure leaves the category null and is reported as a
    technical failure by the caller — it never becomes a silent ``GENERAL``.
    """
    rule_result = classify_rules(view)
    if rule_result.category is not None:
        # A rule decided. ``unresolved`` may still be set to record that the
        # organizer mapping for this shape is an open question.
        return ClassificationOutcome(rule_result)

    if model is None:
        # Documented conservative policy: an email with no recognizable requested
        # action is an operational update, recorded with its uncertainty.
        return ClassificationOutcome(
            ClassificationResult(
                "GENERAL", "DETERMINISTIC",
                "no explicit comparison, instruction, or billing request was found",
                rule_id="R-GEN-DEFAULT", unresolved=True,
                detail="conservative default applied without a model",
            )
        )

    proposal = model.classify(
        subject=view.subject,
        current_message=view.current_message,
        quoted_history=view.quoted_history,
        attachment_names=tuple(attachment_names),
    )
    # The adapter has already validated the structured response shape.
    return ClassificationOutcome(
        ClassificationResult(
            category=proposal.category,
            classified_by="AI",
            reason=proposal.reason,
            rule_id="",
            confidence=proposal.confidence,
            evidence_quotes=proposal.evidence_quotes,
        ),
        ai_calls=1,
        events=["AI_CLASSIFICATION_USED"],
    )
