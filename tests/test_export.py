"""Export of finalized automated EVAL assessments."""

import pytest

from backend import crud, schemas
from backend.database import SessionLocal
from backend.export import export_eval_cases
from tests.conftest import DEMO_MATCH, DEMO_MISMATCH, DEMO_MISSING_WEIGHT


def _finalize(email_id: str, worker_run=True) -> None:
    """Create an EVAL case and let the real worker produce its assessment."""
    from backend import worker

    db = SessionLocal()
    try:
        case = crud.create_case_with_job(db, email_id, run_kind=schemas.RunKind.EVAL)
    finally:
        db.close()
    if worker_run:
        worker.process_case(email_id, job_id="job_export", job_run_id=case.run.run_id)


def test_export_contains_real_assessments(tmp_path):
    """The exported values come from the pipeline, not from a hand-built fixture."""
    _finalize(DEMO_MATCH)
    _finalize(DEMO_MISMATCH)

    output = tmp_path / "submission.json"
    manifest_path = tmp_path / "manifest.json"
    submission, manifest = export_eval_cases(
        output_path=str(output), manifest_path=str(manifest_path), run_kind="EVAL"
    )

    assert DEMO_MATCH in submission
    assert submission[DEMO_MATCH]["category"] == "BL_COMPARISON"
    assert submission[DEMO_MATCH]["status"] == "OK"
    assert submission[DEMO_MATCH]["has_defect"] is False
    assert submission[DEMO_MATCH]["defect_fields"] == []
    assert submission[DEMO_MATCH]["review_reason"] is None

    assert submission[DEMO_MISMATCH]["status"] == "MISMATCH"
    assert submission[DEMO_MISMATCH]["has_defect"] is True
    assert submission[DEMO_MISMATCH]["defect_fields"] == ["consignee"]

    assert manifest["schema_version"] == "2.1.1"
    assert manifest["run_kind"] == "EVAL"
    assert "sha256" in manifest
    assert manifest["total_cases"] >= 2
    assert output.exists() and manifest_path.exists()


def test_a_frozen_needs_review_assessment_is_still_exportable(tmp_path):
    """Export eligibility follows the automated assessment, not human progress."""
    _finalize(DEMO_MISSING_WEIGHT)

    submission, _manifest = export_eval_cases(
        output_path=str(tmp_path / "s.json"), manifest_path=str(tmp_path / "m.json"),
        run_kind="EVAL",
    )
    entry = submission[DEMO_MISSING_WEIGHT]
    assert entry["status"] == "NEEDS_REVIEW"
    assert entry["review_reason"] == "missing_value"
    # NEEDS_REVIEW always exports with no defects.
    assert entry["has_defect"] is False
    assert entry["defect_fields"] == []


def test_a_case_without_a_finalized_assessment_fails_the_export_closed(tmp_path):
    """An unfinished case never becomes a fabricated organizer answer."""
    _finalize(DEMO_MATCH, worker_run=False)

    output = tmp_path / "s.json"
    with pytest.raises(RuntimeError, match="FAIL CLOSED") as failure:
        export_eval_cases(output_path=str(output), manifest_path=str(tmp_path / "m.json"),
                          run_kind="EVAL")
    # The failure names the offending id rather than emitting a guessed result.
    assert DEMO_MATCH in str(failure.value)
    assert not output.exists()


def test_demo_results_never_leak_into_an_eval_export(tmp_path):
    """Working demo results are not organizer answers."""
    from backend import worker

    db = SessionLocal()
    try:
        demo_case = crud.create_case_with_job(db, DEMO_MATCH, run_kind=schemas.RunKind.DEMO)
    finally:
        db.close()
    worker.process_case(DEMO_MATCH, job_id="job_demo", job_run_id=demo_case.run.run_id)

    submission, _manifest = export_eval_cases(
        output_path=str(tmp_path / "s.json"), manifest_path=str(tmp_path / "m.json"),
        run_kind="EVAL",
    )
    assert DEMO_MATCH not in submission
