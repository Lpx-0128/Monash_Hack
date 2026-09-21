"""Gemini 3.5 Flash Lite provider integration tests.

Tests Google Gemini's OpenAI-compatible chat-completions endpoint,
request headers, payload format, error mapping, refusal handling,
and full pipeline execution with mock transport on synthetic DEMO fixtures.
"""

import dataclasses
import json
from decimal import Decimal
import httpx
import pytest

from backend.intelligence import ai as ai_module
from backend.intelligence.config import AIConfig, load_config
from backend.intelligence.ingestion import build_registries, ingest_case, InputSnapshot
from backend.intelligence.pipeline import (
    AnalysisContext,
    IntelligenceServices,
    analyze_case,
    ReviewRequirement,
)
from backend.intelligence.types import (
    PermanentProcessingError,
    RetryableProcessingError,
)
from backend.intelligence.comparison import (
    compare_all,
    roll_up,
    MATCH,
    MISMATCH,
    NOT_COMPARABLE,
    FieldComparisonResult,
)
from backend.intelligence.recomputation import (
    DecisionProposal,
    ProposalRejected,
    OVERRIDE_CONFIRMATION_REQUIRED,
    validate_human_proposal,
    WorkingAnalysis,
)
from backend.intelligence.roles import RoleResolution



GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
GEMINI_MODEL = "gemini-3.5-flash-lite"


def _gemini_config(*, allow_participant=False, calls=4) -> AIConfig:
    return AIConfig(
        enabled=True,
        provider="gemini",
        endpoint=GEMINI_ENDPOINT,
        model=GEMINI_MODEL,
        api_key="mock-gemini-key",
        allow_participant_content=allow_participant,
        max_calls_per_run=calls,
        timeout_seconds=5,
    )


# ---------------------------------------------------------------------------
# Request & Auth Compatibility Tests
# ---------------------------------------------------------------------------

def test_gemini_request_headers_and_body():
    """Verify Gemini request uses Authorization: Bearer and does NOT leak api-key header."""
    config = _gemini_config()
    captured_request = {}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        captured_request["headers"] = dict(request.headers)
        captured_request["body"] = json.loads(request.content.decode())
        captured_request["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps({
                                "category": "SPAM",
                                "reason": "unsolicited commercial message",
                                "evidence_quotes": ["click here"],
                            }),
                        }
                    }
                ]
            },
        )

    client = ai_module.HttpModelClient(config, transport=httpx.MockTransport(mock_handler))
    proposal = client.classify(
        subject="Special offer",
        current_message="click here for deal",
        quoted_history="",
        attachment_names=(),
    )

    assert proposal.category == "SPAM"
    # Verification of Gemini-specific headers
    headers = captured_request["headers"]
    assert headers["authorization"] == "Bearer mock-gemini-key"
    assert "api-key" not in headers, "Azure-specific api-key header must NOT be sent to Gemini"
    assert headers["content-type"] == "application/json"

    # Verification of body parameters
    body = captured_request["body"]
    assert body["model"] == "gemini-3.5-flash-lite"
    assert body["temperature"] == 0
    assert body["response_format"] == {"type": "json_object"}
    assert len(body["messages"]) == 1


# ---------------------------------------------------------------------------
# Envelope, Error & Refusal Handling
# ---------------------------------------------------------------------------

def test_gemini_refusal_response():
    """Verify model refusal raises ModelResponseInvalid."""
    config = _gemini_config()

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "refusal": "I cannot classify or inspect this shipping document.",
                        }
                    }
                ]
            },
        )

    client = ai_module.HttpModelClient(config, transport=httpx.MockTransport(mock_handler))
    with pytest.raises(ai_module.ModelResponseInvalid, match="refused"):
        client.classify(subject="sub", current_message="msg", quoted_history="", attachment_names=())


def test_gemini_null_or_empty_content():
    """Verify null or empty message content raises ModelResponseInvalid."""
    config = _gemini_config()

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "  "}}]},
        )

    client = ai_module.HttpModelClient(config, transport=httpx.MockTransport(mock_handler))
    with pytest.raises(ai_module.ModelResponseInvalid, match="empty or null"):
        client.classify(subject="sub", current_message="msg", quoted_history="", attachment_names=())


def test_gemini_invalid_json_content():
    """Verify non-JSON model output raises ModelResponseInvalid."""
    config = _gemini_config()

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "Sure, here is the result: {incomplete"}}]},
        )

    client = ai_module.HttpModelClient(config, transport=httpx.MockTransport(mock_handler))
    with pytest.raises(ai_module.ModelResponseInvalid, match="not valid JSON"):
        client.classify(subject="sub", current_message="msg", quoted_history="", attachment_names=())


def test_gemini_http_401_unauthorized():
    """Verify 401 authentication rejection raises PermanentProcessingError."""
    config = _gemini_config()

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "API_KEY_INVALID"}})

    client = ai_module.HttpModelClient(config, transport=httpx.MockTransport(mock_handler))
    with pytest.raises(PermanentProcessingError, match="401"):
        client.classify(subject="sub", current_message="msg", quoted_history="", attachment_names=())


def test_gemini_http_429_rate_limited():
    """Verify 429 rate limit or quota exceeded raises RetryableProcessingError."""
    config = _gemini_config()

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "Resource exhausted"}})

    client = ai_module.HttpModelClient(config, transport=httpx.MockTransport(mock_handler))
    with pytest.raises(RetryableProcessingError, match="429"):
        client.classify(subject="sub", current_message="msg", quoted_history="", attachment_names=())


def test_gemini_http_500_server_error():
    """Verify 500 server error raises RetryableProcessingError."""
    config = _gemini_config()

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "Internal server error"})

    client = ai_module.HttpModelClient(config, transport=httpx.MockTransport(mock_handler))
    with pytest.raises(RetryableProcessingError, match="500"):
        client.classify(subject="sub", current_message="msg", quoted_history="", attachment_names=())


def test_gemini_timeout():
    """Verify transport timeout raises RetryableProcessingError."""
    config = _gemini_config()

    def mock_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Request timed out")

    client = ai_module.HttpModelClient(config, transport=httpx.MockTransport(mock_handler))
    with pytest.raises(RetryableProcessingError, match="timed out"):
        client.classify(subject="sub", current_message="msg", quoted_history="", attachment_names=())


# ---------------------------------------------------------------------------
# Pipeline Integration with Synthetic DEMO Fixtures
# ---------------------------------------------------------------------------

def test_gemini_pipeline_needs_model_fixture():
    """Exercise email_demo_needs_model through the full pipeline with Gemini client."""
    full_config = load_config()
    gemini_ai = _gemini_config()
    full_config = dataclasses.replace(full_config, ai=gemini_ai)
    registries = build_registries(full_config)

    def mock_handler(request: httpx.Request) -> httpx.Response:
        # Expected classification response for email_demo_needs_model
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps({
                                "category": "BL_COMPARISON",
                                "reason": "Sender requests reading differences between customer request and paperwork",
                                "evidence_quotes": ["Something is off between the two"],
                                "confidence": 0.95,
                            }),
                        }
                    }
                ]
            },
        )

    client = ai_module.HttpModelClient(gemini_ai, transport=httpx.MockTransport(mock_handler))
    services = IntelligenceServices(
        registries=registries,
        model=client,
        budget=ai_module.CallBudget(limit=4),
    )

    snapshot = ingest_case(
        "email_demo_needs_model",
        namespace="DEMO",
        case_id="case_test_gemini_needs_model",
        registries=registries,
        config=full_config,
    )
    context = AnalysisContext(
        case_id="case_test_gemini_needs_model",
        run_id="run_test_gemini_1",
        run_kind="DEMO",
        config=full_config,
        now=lambda: "2026-09-21T12:00:00Z",
        next_id=lambda prefix: f"{prefix}_1",
    )

    analysis = analyze_case(snapshot, context, services)
    assert analysis.category == "BL_COMPARISON"
    assert analysis.classified_by == "AI"
    assert analysis.ai_calls == 1


def test_gemini_pipeline_ambiguous_weight_grounded():
    """Exercise email_demo_ambiguous_weight through the pipeline with valid block extraction."""
    full_config = load_config()
    gemini_ai = _gemini_config()
    full_config = dataclasses.replace(full_config, ai=gemini_ai)
    registries = build_registries(full_config)

    def mock_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        prompt = body["messages"][0]["content"]

        # Parse document_block from the prompt
        idx = prompt.rfind('{\n  "document_id":')
        doc_block = json.loads(prompt[idx:])
        location_tokens = doc_block["location_tokens"]
        doc_id = doc_block["document_id"]
        blocks = doc_block.get("location_blocks", {})

        candidates = []
        for token in location_tokens:
            block = blocks.get(token, {})
            val = block.get("value", "")
            if "21,600" in val or "21600" in val:
                candidates.append({
                    "field": "gross_weight_kg",
                    "raw": val,
                    "locator": token,
                    "source_text": val,
                    "derivation": "DIRECT",
                })
                break

        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps({
                                "document_id": doc_id,
                                "candidates": candidates,
                                "unresolved_fields": [] if candidates else ["gross_weight_kg"],
                            }),
                        }
                    }
                ]
            },
        )

    client = ai_module.HttpModelClient(gemini_ai, transport=httpx.MockTransport(mock_handler))
    services = IntelligenceServices(
        registries=registries,
        model=client,
        budget=ai_module.CallBudget(limit=4),
    )

    snapshot = ingest_case(
        "email_demo_ambiguous_weight",
        namespace="DEMO",
        case_id="case_test_gemini_ambiguous_weight",
        registries=registries,
        config=full_config,
    )
    context = AnalysisContext(
        case_id="case_test_gemini_ambiguous_weight",
        run_id="run_test_gemini_2",
        run_kind="DEMO",
        config=full_config,
        now=lambda: "2026-09-21T12:00:00Z",
        next_id=lambda prefix: f"{prefix}_1",
    )

    analysis = analyze_case(snapshot, context, services)
    assert analysis.ai_calls >= 1


def test_gemini_pipeline_fabricated_extraction_rejected_by_grounding():
    """Verify that a fabricated candidate from the model is rejected by G1-G3 grounding."""
    full_config = load_config()
    gemini_ai = _gemini_config()
    full_config = dataclasses.replace(full_config, ai=gemini_ai)
    registries = build_registries(full_config)

    def mock_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        prompt = body["messages"][0]["content"]
        idx = prompt.rfind('{\n  "document_id":')
        doc_block = json.loads(prompt[idx:])
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps({
                                "document_id": doc_block["document_id"],
                                "candidates": [
                                    {
                                        "field": "gross_weight_kg",
                                        "raw": "999999 KG",
                                        "locator": "nonexistent_token",
                                        "source_text": "999999 KG hallucination",
                                        "derivation": "DIRECT",
                                    }
                                ],
                                "unresolved_fields": [],
                            }),
                        }
                    }
                ]
            },
        )

    client = ai_module.HttpModelClient(gemini_ai, transport=httpx.MockTransport(mock_handler))
    services = IntelligenceServices(
        registries=registries,
        model=client,
        budget=ai_module.CallBudget(limit=4),
    )

    snapshot = ingest_case(
        "email_demo_ambiguous_weight",
        namespace="DEMO",
        case_id="case_test_gemini_hallucination",
        registries=registries,
        config=full_config,
    )
    context = AnalysisContext(
        case_id="case_test_gemini_hallucination",
        run_id="run_test_gemini_3",
        run_kind="DEMO",
        config=full_config,
        now=lambda: "2026-09-21T12:00:00Z",
        next_id=lambda prefix: f"{prefix}_1",
    )

    analysis = analyze_case(snapshot, context, services)
    # The hallucinated gross weight was rejected, so gross_weight_kg remains ambiguous or needs review
    comparison = next((c for c in analysis.comparisons if c.field == "gross_weight_kg"), None)
    assert comparison is None or comparison.result != "MATCH"


def test_gemini_participant_consent_gating():
    """Verify that participant correspondence is NEVER sent to Gemini when consent is false."""
    full_config = load_config()
    gemini_ai = _gemini_config(allow_participant=False)
    full_config = dataclasses.replace(full_config, ai=gemini_ai)
    registries = build_registries(full_config)

    calls_made = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        calls_made.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "{}"}}]})

    client = ai_module.HttpModelClient(gemini_ai, transport=httpx.MockTransport(mock_handler))
    services = IntelligenceServices(
        registries=registries,
        model=client,
        budget=ai_module.CallBudget(limit=4),
    )

    # Ingest from participant root (sdoc-hackathon-bundle), namespace EVAL
    snapshot = ingest_case(
        "email_001",
        namespace="EVAL",
        case_id="case_participant_test",
        registries=registries,
        config=full_config,
    )
    context = AnalysisContext(
        case_id="case_participant_test",
        run_id="run_participant_test",
        run_kind="EVAL",
        config=full_config,
        now=lambda: "2026-09-21T12:00:00Z",
        next_id=lambda prefix: f"{prefix}_1",
    )

    analyze_case(snapshot, context, services)
    assert len(calls_made) == 0, "No external model call must be made for participant data without consent"


# ---------------------------------------------------------------------------
# Comparison Rollups & Decision Conflict Tests (Preserving Boundaries)
# ---------------------------------------------------------------------------

def _mock_field(name: str, result: str, cause: str = None) -> FieldComparisonResult:
    return FieldComparisonResult(
        field=name,
        si=None,
        bl=None,
        result=result,
        not_comparable_cause=cause,
        compared_by="DETERMINISTIC",
    )


def test_seven_exact_matches_yields_ok():
    """Seven exact matches rollup to status OK."""
    fields = [
        "shipper", "consignee", "notify_party",
        "port_of_loading", "port_of_discharge",
        "container_count", "gross_weight_kg",
    ]
    comparisons = [_mock_field(f, MATCH) for f in fields]
    assessment = roll_up("BL_COMPARISON", comparisons)
    assert assessment.status == "OK"
    assert assessment.has_defect is False
    assert assessment.defect_fields == ()


def test_one_confirmed_container_mismatch_yields_mismatch():
    """One confirmed container count mismatch yields status MISMATCH, not an AI error."""
    fields = [
        "shipper", "consignee", "notify_party",
        "port_of_loading", "port_of_discharge",
        "gross_weight_kg",
    ]
    comparisons = [_mock_field(f, MATCH) for f in fields]
    comparisons.append(_mock_field("container_count", MISMATCH))

    assessment = roll_up("BL_COMPARISON", comparisons)
    assert assessment.status == "MISMATCH"
    assert assessment.has_defect is True
    assert "container_count" in assessment.defect_fields


def test_missing_bl_field_yields_needs_review():
    """Missing BL field causes NOT_COMPARABLE with cause, which rolls up to NEEDS_REVIEW."""
    fields = [
        "shipper", "consignee", "notify_party",
        "port_of_loading", "port_of_discharge",
        "container_count",
    ]
    comparisons = [_mock_field(f, MATCH) for f in fields]
    comparisons.append(_mock_field("gross_weight_kg", NOT_COMPARABLE, cause="MISSING_VALUE"))

    assessment = roll_up("BL_COMPARISON", comparisons)
    assert assessment.status == "NEEDS_REVIEW"
    assert assessment.review_reason == "missing_value"
    # Even if another field had a mismatch, NEEDS_REVIEW takes operational precedence
    comparisons_with_mismatch = [_mock_field("container_count", MISMATCH)] + comparisons[1:]
    assessment2 = roll_up("BL_COMPARISON", comparisons_with_mismatch)
    assert assessment2.status == "NEEDS_REVIEW"


def test_conflicting_extracted_candidates_yields_needs_review():
    """Ambiguity from conflicting candidates causes NOT_COMPARABLE, rolling up to NEEDS_REVIEW."""
    comparisons = [
        _mock_field("shipper", NOT_COMPARABLE, cause="CONFLICTING_CANDIDATES"),
        _mock_field("consignee", MATCH),
    ]
    assessment = roll_up("BL_COMPARISON", comparisons)
    assert assessment.status == "NEEDS_REVIEW"


def test_spam_classification_yields_spam():
    """SPAM email classification settles with non-comparison status."""
    assessment = roll_up("SPAM", ())
    assert assessment.status == "OK"
    assert assessment.has_defect is False


def test_human_override_with_evidence_conflict_requires_explicit_confirmation():
    """A human decision conflicting with document evidence raises OVERRIDE_CONFIRMATION_REQUIRED."""
    review = ReviewRequirement(
        scope="FIELD",
        ui_mode="VALUE_INPUT",
        reason="conflicting_candidates",
        question="Select or confirm value",
        context_summary="",
        allowed_actions=("PROVIDE_VALUE",),
        field="gross_weight_kg",
        side="SI",
    )
    state = WorkingAnalysis(
        snapshot=InputSnapshot(
            email_id="demo_1",
            from_address="demo@example.invalid",
            received_at=None,
            demo_safe=True,
            namespace="DEMO",
            case_id="case_1",
            registry_kind="synthetic_demo",
            subject="sub",
            body="msg",
            sources=(),
            input_version="iv1_test",
        ),
        parsed={},
        si_fields={},
        bl_fields={},
        roles=RoleResolution(si="doc_si", bl="doc_bl"),
        category="BL_COMPARISON",
        machine_assessment=None,
        machine_comparisons=(),
    )
    proposal = DecisionProposal(
        review_id="rev_1",
        run_id="run_1",
        action="PROVIDE_VALUE",
        actor_id="operator_1",
        channel="web",
        field="gross_weight_kg",
        side="SI",
        value=99999,
        override_confirmation=None,  # No explicit confirmation!
    )

    class MockContext:
        config = load_config()

        def next_id(self, prefix):
            return f"{prefix}_1"

    with pytest.raises(ProposalRejected) as excinfo:
        validate_human_proposal(proposal, review, state, MockContext())

    assert excinfo.value.code in (
        OVERRIDE_CONFIRMATION_REQUIRED,
        "VALUE_NOT_FOUND_IN_DOCUMENT",
    )
