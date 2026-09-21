"""Model adapter: validation, budgets and the one case that genuinely needs it."""

import pytest

from backend.intelligence import ai as ai_module
from backend.intelligence.classification import build_view, classify, classify_rules
from backend.intelligence.config import AIConfig
from backend.intelligence.types import PermanentProcessingError, RetryableProcessingError

EMAIL_TEXT = ("DEMO-BK-00052 follow up\nDear Team,\n\nRegarding DEMO-BK-00052 - the paperwork "
              "you sent through yesterday against what the customer originally asked for. "
              "Something is off between the two and we would like your read before we go "
              "back to them.\n")


def test_response_must_use_one_of_the_five_categories():
    with pytest.raises(ai_module.ModelResponseInvalid):
        ai_module.validate_classification(
            {"category": "NEEDS_ATTENTION", "reason": "unclear"}, source_text=EMAIL_TEXT
        )


def test_a_fabricated_citation_is_rejected():
    with pytest.raises(ai_module.ModelResponseInvalid, match="does not occur"):
        ai_module.validate_classification(
            {"category": "SPAM", "reason": "r", "evidence_quotes": ["free bitcoin now"]},
            source_text=EMAIL_TEXT,
        )


def test_a_valid_response_keeps_confidence_advisory():
    proposal = ai_module.validate_classification(
        {"category": "BL_COMPARISON", "reason": "the sender asks for a read on two documents",
         "evidence_quotes": ["Something is off between the two"], "confidence": 0.42},
        source_text=EMAIL_TEXT,
    )
    assert proposal.category == "BL_COMPARISON"
    assert proposal.confidence == 0.42


def test_extraction_rejects_unrequested_fields_and_invented_locations():
    document_text = "Gross Weight (KG): 21600 KG"
    base = {"document_id": "doc_1", "candidates": [], "unresolved_fields": []}

    def candidate(**overrides):
        entry = {"field": "gross_weight_kg", "raw": "21600 KG", "derivation": "DIRECT",
                 "evidence": [{"locator": "page:1", "source_text": "Gross Weight (KG): 21600 KG"}]}
        entry.update(overrides)
        return dict(base, candidates=[entry])

    kwargs = dict(document_id="doc_1", allowed_fields=["gross_weight_kg"],
                  allowed_tokens=["page:1"], source_text=document_text)

    # A well-formed response is accepted.
    assert ai_module.validate_extraction(candidate(), **kwargs).candidates

    with pytest.raises(ai_module.ModelResponseInvalid, match="was not requested"):
        ai_module.validate_extraction(candidate(field="vessel_name"), **kwargs)

    with pytest.raises(ai_module.ModelResponseInvalid, match="was not offered"):
        ai_module.validate_extraction(
            candidate(evidence=[{"locator": "page:9", "source_text": "Gross Weight (KG): 21600 KG"}]),
            **kwargs,
        )

    with pytest.raises(ai_module.ModelResponseInvalid, match="does not occur"):
        ai_module.validate_extraction(
            candidate(evidence=[{"locator": "page:1", "source_text": "Gross Weight: 99999 KG"}]),
            **kwargs,
        )

    with pytest.raises(ai_module.ModelResponseInvalid, match="different document"):
        ai_module.validate_extraction(dict(candidate(), document_id="doc_other"), **kwargs)


def test_a_model_cannot_set_workflow_or_grounded_state():
    """Extra keys the model invents carry no meaning in the validated result."""
    payload = {
        "document_id": "doc_1", "unresolved_fields": [],
        "candidates": [{
            "field": "gross_weight_kg", "raw": "21600 KG", "derivation": "DIRECT",
            "grounded": True, "workflow_status": "COMPLETED", "result": "MATCH",
            "evidence": [{"locator": "page:1", "source_text": "21600 KG"}],
        }],
    }
    proposal = ai_module.validate_extraction(
        payload, document_id="doc_1", allowed_fields=["gross_weight_kg"],
        allowed_tokens=["page:1"], source_text="Gross Weight (KG): 21600 KG",
    )
    candidate = proposal.candidates[0]
    assert not hasattr(candidate, "grounded")
    assert not hasattr(candidate, "workflow_status")


def test_model_output_is_parsed_never_evaluated():
    assert ai_module.parse_json_response('```json\n{"category": "SPAM"}\n```') == {"category": "SPAM"}
    with pytest.raises(ai_module.ModelResponseInvalid):
        ai_module.parse_json_response("__import__('os').system('echo pwned')")


def test_an_oversized_response_is_refused():
    with pytest.raises(ai_module.ModelResponseInvalid, match="budget"):
        ai_module.parse_json_response("x" * (ai_module.MAX_RESPONSE_CHARS + 1))


def test_the_call_budget_is_shared_and_finite():
    budget = ai_module.CallBudget(limit=2)
    budget.spend()
    budget.spend()
    with pytest.raises(PermanentProcessingError, match="budget"):
        budget.spend()
    # A cached interpretation is not a new provider call.
    budget.note_cache_hit()
    assert budget.calls == 2 and budget.cache_hits == 1


def test_a_disabled_model_is_never_a_silent_mock():
    client = ai_module.build_model_client(AIConfig(enabled=False))
    assert isinstance(client, ai_module.DisabledModelClient)
    with pytest.raises(PermanentProcessingError, match="disabled"):
        client.classify(subject="s", current_message="m", quoted_history="", attachment_names=())


def test_enabling_ai_without_settings_fails_loudly():
    with pytest.raises(PermanentProcessingError, match="unset"):
        AIConfig(enabled=True, provider="azure").validate()


def test_removing_the_model_changes_what_this_case_can_do():
    """The configured model path is what decides this email, not decoration."""
    view = build_view("DEMO-BK-00052 follow up", EMAIL_TEXT)

    # No rule can decide it.
    assert classify_rules(view).category is None

    # Without a model, the conservative default applies and records its doubt.
    without = classify(view).result
    assert without.category == "GENERAL" and without.unresolved is True

    # With the model, the category is materially chosen by it.
    scripted = ai_module.ScriptedModelClient(classifications={
        "DEMO-BK-00052 follow up": {
            "category": "BL_COMPARISON",
            "reason": "the sender asks for a read on two documents that disagree",
            "evidence_quotes": ["Something is off between the two"],
            "confidence": 0.6,
        }
    })
    outcome = classify(view, model=scripted)
    assert outcome.result.category == "BL_COMPARISON"
    assert outcome.result.classified_by == "AI"
    assert outcome.ai_calls == 1
    assert scripted.calls == [("classify", "DEMO-BK-00052 follow up")]


def test_a_provider_failure_surfaces_as_a_retryable_error():
    scripted = ai_module.ScriptedModelClient(classifications={
        "DEMO-BK-00052 follow up": ai_module.ModelResponseInvalid("provider timed out"),
    })
    view = build_view("DEMO-BK-00052 follow up", EMAIL_TEXT)
    with pytest.raises(RetryableProcessingError):
        classify(view, model=scripted)


def test_http_client_maps_transport_failures_to_typed_errors():
    import httpx

    config = AIConfig(enabled=True, provider="azure", endpoint="https://example.invalid/chat",
                      model="gpt-test", api_key="secret", timeout_seconds=1)

    def timeout(_request):
        raise httpx.ConnectTimeout("simulated")

    client = ai_module.HttpModelClient(config, transport=httpx.MockTransport(timeout))
    with pytest.raises(RetryableProcessingError):
        client.classify(subject="s", current_message="m", quoted_history="", attachment_names=())

    def server_error(_request):
        return httpx.Response(500, json={"error": "boom"})

    client = ai_module.HttpModelClient(config, transport=httpx.MockTransport(server_error))
    with pytest.raises(RetryableProcessingError, match="500"):
        client.classify(subject="s", current_message="m", quoted_history="", attachment_names=())

    def rejected(_request):
        return httpx.Response(401, json={"error": "unauthorized"})

    client = ai_module.HttpModelClient(config, transport=httpx.MockTransport(rejected))
    with pytest.raises(PermanentProcessingError, match="401"):
        client.classify(subject="s", current_message="m", quoted_history="", attachment_names=())


def test_http_client_validates_a_real_looking_response():
    import httpx

    config = AIConfig(enabled=True, provider="azure", endpoint="https://example.invalid/chat",
                      model="gpt-test", api_key="secret")
    captured = {}

    def handler(request):
        captured["body"] = request.content.decode()
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"choices": [{"message": {"content": (
            '{"category": "SPAM", "reason": "credential harvesting", '
            '"evidence_quotes": ["verify your account"], "confidence": 0.9}'
        )}}]})

    client = ai_module.HttpModelClient(config, transport=httpx.MockTransport(handler))
    proposal = client.classify(subject="Mailbox full",
                               current_message="verify your account now",
                               quoted_history="", attachment_names=())
    assert proposal.category == "SPAM"
    # The prompt states that embedded instructions carry no authority.
    assert "no authority" in captured["body"] or "no\\nauthority" in captured["body"]
    assert captured["auth"] == "Bearer secret"


def test_the_api_key_never_appears_in_the_config_identity():
    config = AIConfig(enabled=True, provider="azure", endpoint="https://example.invalid",
                      model="gpt-test", api_key="super-secret-key")
    identity = config.identity()
    assert "super-secret-key" not in repr(identity)
    assert "super-secret-key" not in repr(config)
