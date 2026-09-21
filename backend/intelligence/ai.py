"""One model-client protocol and one validated adapter (handoff §17).

The model is a bounded dependency of classification and extraction. It never
chooses workflow state, authorizes an actor, confirms an override, sets a
grounded flag or decides numeric equality. Every response is validated against a
strict schema and then re-verified against the source by G1-G3.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Any, Mapping, Optional, Protocol, Sequence

from .config import PROMPTS_DIR, AIConfig
from .types import PermanentProcessingError, RetryableProcessingError

VERSION = "ai-1.1.0"

LocationTokens = Sequence[str] | Mapping[str, Mapping[str, Any]]

CATEGORIES = ("BL_COMPARISON", "SI_REQUEST", "INVOICE_QUERY", "GENERAL", "SPAM")
DERIVATIONS = ("DIRECT", "TOTAL")

MAX_PROMPT_CHARS = 24_000
MAX_RESPONSE_CHARS = 16_000


class ModelResponseInvalid(RetryableProcessingError):
    """The provider replied, but not with a valid structured result."""


@dataclass(frozen=True)
class ClassificationProposal:
    category: str
    reason: str
    evidence_quotes: tuple[str, ...] = ()
    confidence: Optional[float] = None


@dataclass(frozen=True)
class ExtractionCandidateProposal:
    field: str
    raw: str
    locator_token: str
    source_text: str
    derivation: str = "DIRECT"


@dataclass(frozen=True)
class ExtractionProposal:
    document_id: str
    candidates: tuple[ExtractionCandidateProposal, ...] = ()
    unresolved_fields: tuple[str, ...] = ()


class ModelClient(Protocol):
    """The only model surface the pipeline depends on."""

    name: str

    def classify(self, *, subject: str, current_message: str, quoted_history: str,
                 attachment_names: Sequence[str]) -> ClassificationProposal:
        ...

    def extract(self, *, document_id: str, document_text: str,
                location_tokens: LocationTokens,
                requested_fields: Sequence[str]) -> ExtractionProposal:
        ...


# ---------------------------------------------------------------------------
# Response validation
# ---------------------------------------------------------------------------

def _require_object(payload) -> dict:
    if not isinstance(payload, dict):
        raise ModelResponseInvalid("the model response is not a JSON object")
    return payload


def validate_classification(payload, *, source_text: str) -> ClassificationProposal:
    """Validate the category and check every cited quote against the real email."""
    data = _require_object(payload)
    category = data.get("category")
    if category not in CATEGORIES:
        raise ModelResponseInvalid(f"category {category!r} is not one of the five categories")

    reason = data.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ModelResponseInvalid("the model gave no explanation")

    raw_quotes = data.get("evidence_quotes") or []
    if not isinstance(raw_quotes, list):
        raise ModelResponseInvalid("evidence_quotes is not a list")
    quotes: list[str] = []
    for quote in raw_quotes:
        if not isinstance(quote, str):
            raise ModelResponseInvalid("an evidence quote is not a string")
        if quote.strip() and quote.strip() not in source_text:
            # A quote that is not in the email is a fabricated citation.
            raise ModelResponseInvalid("an evidence quote does not occur in the email")
        quotes.append(quote)

    confidence = data.get("confidence")
    if confidence is not None:
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            raise ModelResponseInvalid("confidence is not a number")
        confidence = float(confidence)

    return ClassificationProposal(
        category=category, reason=reason.strip(),
        evidence_quotes=tuple(quotes), confidence=confidence,
    )


def validate_extraction(payload, *, document_id: str, allowed_fields: Sequence[str],
                        allowed_tokens: LocationTokens, source_text: str) -> ExtractionProposal:
    """Validate fields, document identity, location tokens and quote existence.

    Extra fields, unknown documents and invented locations are rejected outright;
    surviving candidates still have to pass G1-G3.
    """
    data = _require_object(payload)
    if data.get("document_id") != document_id:
        raise ModelResponseInvalid("the response names a different document")

    allowed_field_set = set(allowed_fields)
    allowed_token_set = set(allowed_tokens)

    raw_candidates = data.get("candidates") or []
    if not isinstance(raw_candidates, list):
        raise ModelResponseInvalid("candidates is not a list")

    candidates: list[ExtractionCandidateProposal] = []
    for entry in raw_candidates:
        entry = _require_object(entry)
        field = entry.get("field")
        if field not in allowed_field_set:
            raise ModelResponseInvalid(f"field {field!r} was not requested")
        raw = entry.get("raw")
        if not isinstance(raw, str) or not raw.strip():
            raise ModelResponseInvalid(f"candidate for {field!r} has no raw value")
        evidence = entry.get("evidence") or []
        if not isinstance(evidence, list) or not evidence:
            raise ModelResponseInvalid(f"candidate for {field!r} has no evidence")
        reference = _require_object(evidence[0])
        token = reference.get("locator")
        if token not in allowed_token_set:
            raise ModelResponseInvalid(f"locator {token!r} was not offered for this document")
        quote = reference.get("source_text")
        if not isinstance(quote, str) or not quote.strip() or quote not in source_text:
            raise ModelResponseInvalid(f"the quote for {field!r} does not occur in the document")
        if isinstance(allowed_tokens, Mapping):
            value = allowed_tokens[token]["value"]
            if raw != value or quote != value:
                raise ModelResponseInvalid(f"the raw value or quote for {field!r} disagrees with its block")
        derivation = entry.get("derivation", "DIRECT")
        if derivation not in DERIVATIONS:
            raise ModelResponseInvalid(f"derivation {derivation!r} is not supported")
        candidates.append(ExtractionCandidateProposal(
            field=field, raw=raw, locator_token=token, source_text=quote, derivation=derivation,
        ))

    unresolved = data.get("unresolved_fields") or []
    if not isinstance(unresolved, list) or any(f not in allowed_field_set for f in unresolved):
        raise ModelResponseInvalid("unresolved_fields contains a field that was not requested")

    return ExtractionProposal(
        document_id=document_id, candidates=tuple(candidates),
        unresolved_fields=tuple(unresolved),
    )


def parse_json_response(text: str) -> dict:
    """Parse a JSON object from a model reply, without ever evaluating it."""
    if not isinstance(text, str):
        raise ModelResponseInvalid("the provider returned a non-text body")
    if len(text) > MAX_RESPONSE_CHARS:
        raise ModelResponseInvalid("the provider response exceeds the response budget")
    stripped = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, re.DOTALL)
    if fence:
        stripped = fence.group(1)
    try:
        return json.loads(stripped)
    except ValueError as exc:
        raise ModelResponseInvalid(f"the provider response is not valid JSON: {exc}") from exc


def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / name
    if not path.is_file():
        raise PermanentProcessingError(f"prompt file {name!r} is missing")
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Call accounting
# ---------------------------------------------------------------------------

@dataclass
class CallBudget:
    """A shared attempt budget, so no hidden SDK retry multiplies the call count."""

    limit: int
    calls: int = 0
    cache_hits: int = 0

    def spend(self) -> None:
        if self.calls >= self.limit:
            raise PermanentProcessingError(
                f"the configured model-call budget of {self.limit} for this run is exhausted"
            )
        self.calls += 1

    def note_cache_hit(self) -> None:
        # A cached interpretation is not a new provider call.
        self.cache_hits += 1


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------

class DisabledModelClient:
    """Used when AI is switched off. Asking it to work is an explicit failure."""

    name = "disabled"

    def classify(self, **_kwargs) -> ClassificationProposal:
        raise PermanentProcessingError("the model is disabled; no classification can be requested")

    def extract(self, **_kwargs) -> ExtractionProposal:
        raise PermanentProcessingError("the model is disabled; no extraction can be requested")


@dataclass
class ScriptedModelClient:
    """Test double. Responses are supplied explicitly; nothing is ever inferred.

    Offline tests use this. It is never installed on the real path: the pipeline
    only accepts a client the configuration asked for.
    """

    classifications: dict = dc_field(default_factory=dict)
    extractions: dict = dc_field(default_factory=dict)
    name: str = "scripted"
    calls: list = dc_field(default_factory=list)

    def classify(self, *, subject: str, current_message: str, quoted_history: str,
                 attachment_names: Sequence[str]) -> ClassificationProposal:
        self.calls.append(("classify", subject))
        key = subject.strip()
        if key not in self.classifications:
            raise ModelResponseInvalid(f"no scripted classification for subject {key!r}")
        payload = self.classifications[key]
        if isinstance(payload, Exception):
            raise payload
        return validate_classification(payload, source_text=f"{subject}\n{current_message}\n{quoted_history}")

    def extract(self, *, document_id: str, document_text: str,
                location_tokens: LocationTokens,
                requested_fields: Sequence[str]) -> ExtractionProposal:
        self.calls.append(("extract", document_id))
        payload = self.extractions.get(document_id)
        if payload is None:
            raise ModelResponseInvalid(f"no scripted extraction for document {document_id!r}")
        if isinstance(payload, Exception):
            raise payload
        return validate_extraction(payload, document_id=document_id,
                                   allowed_fields=requested_fields,
                                   allowed_tokens=location_tokens,
                                   source_text=document_text)


class HttpModelClient:
    """One HTTP adapter for the team's approved chat-completions service.

    The endpoint, deployment, API version and model are configured explicitly;
    none of them is inferred. SDK-level automatic retries are not used, so the
    run's shared :class:`CallBudget` is the only retry authority.
    """

    name = "http"

    def __init__(self, config: AIConfig, *, transport=None):
        config.validate()
        self.config = config
        self._transport = transport

    def _post(self, prompt: str, payload_name: str) -> dict:
        import httpx

        if len(prompt) > MAX_PROMPT_CHARS:
            raise PermanentProcessingError(
                f"the {payload_name} prompt exceeds the configured request budget"
            )
        body = {
            "model": self.config.deployment or self.config.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {self.config.api_key}",
            "api-key": self.config.api_key,
        }
        params = {"api-version": self.config.api_version} if self.config.api_version else None
        try:
            with httpx.Client(timeout=self.config.timeout_seconds,
                              transport=self._transport) as client:
                response = client.post(self.config.endpoint, json=body,
                                       headers=headers, params=params)
        except httpx.TimeoutException as exc:
            raise RetryableProcessingError(f"the model provider timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise RetryableProcessingError(f"the model provider is unreachable: {exc}") from exc

        if response.status_code in (408, 429) or response.status_code >= 500:
            raise RetryableProcessingError(
                f"the model provider returned {response.status_code}"
            )
        if response.status_code >= 400:
            raise PermanentProcessingError(
                f"the model request was rejected with {response.status_code}"
            )
        try:
            envelope = response.json()
            content = envelope["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ModelResponseInvalid(f"unexpected provider envelope: {exc}") from exc
        return parse_json_response(content)

    def classify(self, *, subject: str, current_message: str, quoted_history: str,
                 attachment_names: Sequence[str]) -> ClassificationProposal:
        email_block = json.dumps(
            {
                "subject": subject,
                "current_message": current_message,
                "quoted_history": quoted_history[:4000],
                "attachment_names": list(attachment_names),
            },
            ensure_ascii=False, indent=2,
        )
        payload = self._post(load_prompt("classification.md") + "\n" + email_block, "classification")
        return validate_classification(
            payload, source_text=f"{subject}\n{current_message}\n{quoted_history}"
        )

    def extract(self, *, document_id: str, document_text: str,
                location_tokens: LocationTokens,
                requested_fields: Sequence[str]) -> ExtractionProposal:
        document_block = json.dumps(
            {
                "document_id": document_id,
                "requested_fields": list(requested_fields),
                "location_tokens": list(location_tokens),
                "location_blocks": dict(location_tokens) if isinstance(location_tokens, Mapping) else {},
                "text": document_text[:12_000],
            },
            ensure_ascii=False, indent=2,
        )
        payload = self._post(load_prompt("extraction.md") + "\n" + document_block, "extraction")
        return validate_extraction(payload, document_id=document_id,
                                   allowed_fields=requested_fields,
                                   allowed_tokens=location_tokens,
                                   source_text=document_text)


def build_model_client(config: AIConfig, *, transport=None) -> ModelClient:
    """The configured client, or the disabled one. Never a silent mock."""
    if not config.enabled:
        return DisabledModelClient()
    return HttpModelClient(config, transport=transport)
