"""R8 and R9 regressions: public roles and run identity.

On 58f2a7e a document a person chose kept the public role ``OTHER``, and a
reprocessed run persisted the placeholder identities ``v1``/``v1``.
"""

from backend import crud, models, worker
from backend.database import SessionLocal
from tests.conftest import DEMO_DOCUMENT_CHOICE, DEMO_MATCH, DEMO_MISSING_WEIGHT
from tests.helpers import create_and_wait, poll_case


# --------------------------------------------------------------------------
# R8
# --------------------------------------------------------------------------

def test_r8_a_chosen_document_takes_the_role_publicly(client):
    """The review's exact scenario: the selected BL must be shown as the BL."""
    case = create_and_wait(client, DEMO_DOCUMENT_CHOICE, "AWAITING_HUMAN")
    review = case["review"]
    option = next(o for o in review["options"] if o["kind"] == "DOCUMENT")

    response = client.post(
        f"/api/v1/reviews/{review['review_id']}/decision",
        json={"review_id": review["review_id"], "run_id": review["run_id"],
              "channel": "DASHBOARD", "actor_id": "op",
              "action": "SELECT_OPTION", "option_id": option["option_id"]},
    )
    assert response.status_code == 202
    settled = poll_case(client, case["case_id"], "COMPLETED")

    roles = {d["document_id"]: d["role"] for d in settled["documents"]}
    assert roles[option["document_id"]] == "BL", (
        f"the chosen document is still shown as {roles[option['document_id']]!r}"
    )


def test_r8_exactly_one_document_occupies_the_role(client):
    case = create_and_wait(client, DEMO_DOCUMENT_CHOICE, "AWAITING_HUMAN")
    review = case["review"]
    option = next(o for o in review["options"] if o["kind"] == "DOCUMENT")
    client.post(f"/api/v1/reviews/{review['review_id']}/decision",
                json={"review_id": review["review_id"], "run_id": review["run_id"],
                      "channel": "DASHBOARD", "actor_id": "op",
                      "action": "SELECT_OPTION", "option_id": option["option_id"]})
    settled = poll_case(client, case["case_id"], "COMPLETED")

    roles = [d["role"] for d in settled["documents"]]
    assert roles.count("BL") == 1
    assert roles.count("SI") == 1


def test_r8_the_opposite_side_is_untouched(client):
    case = create_and_wait(client, DEMO_DOCUMENT_CHOICE, "AWAITING_HUMAN")
    before = {d["document_id"]: d["role"] for d in case["documents"]}
    si_id = next(k for k, v in before.items() if v == "SI")

    review = case["review"]
    option = next(o for o in review["options"] if o["kind"] == "DOCUMENT")
    client.post(f"/api/v1/reviews/{review['review_id']}/decision",
                json={"review_id": review["review_id"], "run_id": review["run_id"],
                      "channel": "DASHBOARD", "actor_id": "op",
                      "action": "SELECT_OPTION", "option_id": option["option_id"]})
    settled = poll_case(client, case["case_id"], "COMPLETED")

    after = {d["document_id"]: d["role"] for d in settled["documents"]}
    assert after[si_id] == "SI"


def test_r8_the_machine_interpretation_survives_for_audit(client):
    """Operational relabelling does not rewrite what the automated pass decided."""
    case = create_and_wait(client, DEMO_DOCUMENT_CHOICE, "AWAITING_HUMAN")
    review = case["review"]
    option = next(o for o in review["options"] if o["kind"] == "DOCUMENT")
    client.post(f"/api/v1/reviews/{review['review_id']}/decision",
                json={"review_id": review["review_id"], "run_id": review["run_id"],
                      "channel": "DASHBOARD", "actor_id": "op",
                      "action": "SELECT_OPTION", "option_id": option["option_id"]})
    settled = poll_case(client, case["case_id"], "COMPLETED")

    db = SessionLocal()
    try:
        stored = worker.load_run_snapshot(db, settled["run"]["run_id"])
    finally:
        db.close()
    assert stored is not None
    assert stored.source_manifest
    # The frozen machine assessment is unchanged by the human choice.
    assert settled["machine_assessment"]["status"] == "NEEDS_REVIEW"


# --------------------------------------------------------------------------
# R9
# --------------------------------------------------------------------------

def _identities(case: dict) -> tuple[str, str]:
    return case["run"]["input_version"], case["run"]["config_version"]


def test_r9_the_initial_run_persists_real_identities(client):
    case = create_and_wait(client, DEMO_MATCH, "COMPLETED")
    input_version, config_version = _identities(case)
    assert input_version.startswith("iv1_")
    assert config_version.startswith("person-a-v1+")


def test_r9_a_reprocessed_run_persists_real_identities(client):
    """The review's exact scenario: both reverted to 'v1' after reprocess."""
    case = create_and_wait(client, DEMO_MISSING_WEIGHT, "AWAITING_HUMAN")
    first = _identities(case)

    assert client.post(f"/api/v1/cases/{case['case_id']}/reprocess").status_code == 202
    reprocessed = poll_case(client, case["case_id"], "AWAITING_HUMAN")

    input_version, config_version = _identities(reprocessed)
    assert input_version != "v1", "the reprocessed run kept a placeholder input_version"
    assert config_version != "v1", "the reprocessed run kept a placeholder config_version"
    assert input_version.startswith("iv1_")
    assert config_version.startswith("person-a-v1+")
    # Same sources and same configuration, so the identities match the first run.
    assert (input_version, config_version) == first


def test_r9_the_reprocess_response_itself_is_not_a_placeholder(client):
    case = create_and_wait(client, DEMO_MISSING_WEIGHT, "AWAITING_HUMAN")
    response = client.post(f"/api/v1/cases/{case['case_id']}/reprocess")
    assert response.status_code == 202
    accepted = response.json()
    assert accepted["run"]["input_version"] != "v1"
    assert accepted["run"]["config_version"] != "v1"


def test_r9_identities_match_the_pinned_manifest(client):
    """The persisted values are the real manifest digest, not a constant."""
    case = create_and_wait(client, DEMO_MATCH, "COMPLETED")
    expected_config = crud.intelligence_config().config_identity()
    expected_input = crud.load_input_snapshot(
        DEMO_MATCH, crud.schemas.RunKind.DEMO
    ).input_version

    assert case["run"]["config_version"] == expected_config
    assert case["run"]["input_version"] == expected_input


def test_r9_the_run_snapshot_agrees_with_the_persisted_case(client):
    case = create_and_wait(client, DEMO_MISSING_WEIGHT, "AWAITING_HUMAN")
    client.post(f"/api/v1/cases/{case['case_id']}/reprocess")
    reprocessed = poll_case(client, case["case_id"], "AWAITING_HUMAN")

    db = SessionLocal()
    try:
        stored = worker.load_run_snapshot(db, reprocessed["run"]["run_id"])
    finally:
        db.close()
    assert stored.input_version == reprocessed["run"]["input_version"]
    assert stored.config_version == reprocessed["run"]["config_version"]
