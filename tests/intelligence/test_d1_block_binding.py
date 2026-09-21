"""Real HTTP adapter -> analysis regressions; no provider/network access."""
import dataclasses
import json

import httpx
import pytest

from backend.intelligence.ai import HttpModelClient, ExtractionCandidateProposal, ExtractionProposal
from tests.intelligence.test_r6_ai_extraction_path import _config, _run


@pytest.mark.parametrize("selected", [0, 1])
@pytest.mark.parametrize("mode", ["correct", "wrong_quote", "wrong_raw", "both_wrong", "empty_quote", "conflict"])
def test_http_candidate_is_bound_to_its_own_block(selected, mode):
    baseline, _ = _run(None)
    candidates = baseline.bl_fields["gross_weight_kg"].alternatives
    chosen, other = candidates[selected], candidates[1 - selected]
    seen = []

    def handler(request):
        prompt = json.loads(request.content)["messages"][0]["content"]
        data = json.loads(prompt.split("## DOCUMENT", 1)[1])
        token = "block:" + chosen.block_id
        assert data["location_blocks"][token]["value"] == chosen.raw
        assert data["location_blocks"][token]["label"]
        seen.append(data)
        raw = other.raw if mode in ("wrong_raw", "both_wrong") else chosen.raw
        quote = other.raw if mode in ("wrong_quote", "both_wrong") else chosen.raw
        if mode == "empty_quote":
            quote = ""
        entries = [{"field": "gross_weight_kg", "raw": raw,
                    "evidence": [{"locator": token, "source_text": quote}]}]
        if mode == "conflict":
            entries.append({"field": "gross_weight_kg", "raw": other.raw,
                            "evidence": [{"locator": "block:" + other.block_id,
                                          "source_text": other.raw}]})
        response = {"document_id": data["document_id"], "candidates": entries}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(response)}}]})

    config = _config()
    model = HttpModelClient(config.ai, transport=httpx.MockTransport(handler))
    analysis, _ = _run(model, config=config)
    assert len(seen) == 1
    outcome = analysis.bl_fields["gross_weight_kg"]
    if mode == "correct":
        assert outcome.resolved
        assert outcome.value.raw == chosen.raw
        assert outcome.value.normalized.equals(chosen.normalized)
        assert analysis.ai_assisted_fields == 1
    else:
        assert not outcome.resolved
        assert analysis.assessment.status == "NEEDS_REVIEW"
        assert analysis.ai_assisted_fields == 0


@pytest.mark.parametrize("reverse", [False, True])
def test_injected_client_cannot_mix_a_valid_and_contradictory_claim(reverse):
    baseline, _ = _run(None)
    a, b = baseline.bl_fields["gross_weight_kg"].alternatives[:2]

    class Mixed:
        def extract(self, *, document_id, **kwargs):
            good = ExtractionCandidateProposal("gross_weight_kg", a.raw, "block:" + a.block_id, a.raw)
            bad = dataclasses.replace(good, raw=b.raw, source_text=b.raw)
            return ExtractionProposal(document_id, (bad, good) if reverse else (good, bad))

    analysis, _ = _run(Mixed())
    assert not analysis.bl_fields["gross_weight_kg"].resolved
    assert analysis.assessment.status == "NEEDS_REVIEW"
    assert analysis.ai_assisted_fields == 0
