import json
import uuid
import pytest
from pathlib import Path
from backend.export import export_eval_cases
from backend import crud, schemas
from backend.database import SessionLocal


def test_export_eval_cases(tmp_path):
    output_file = tmp_path / "submission.json"
    manifest_file = tmp_path / "manifest.json"
    case_id = f"eval_exp_{uuid.uuid4().hex[:6]}"

    db = SessionLocal()
    try:
        # Create an EVAL case with finalized assessment
        case = crud.create_case_with_job(db, case_id, run_kind=schemas.RunKind.EVAL)
        db_case = crud.get_case(db, case_id)
        case.machine_assessment = schemas.MachineAssessment(
            status=schemas.MachineStatus.OK,
            review_reason=None,
            has_defect=False,
            defect_fields=[],
            assessed_at="2026-09-21T00:00:00Z"
        )
        case.email.category = schemas.EmailCategory.BL_COMPARISON
        crud.update_case(db, db_case, case)
    finally:
        db.close()

    submission, manifest = export_eval_cases(
        output_path=str(output_file),
        manifest_path=str(manifest_file),
        run_kind="EVAL"
    )

    assert case_id in submission
    entry = submission[case_id]
    assert entry["category"] == "BL_COMPARISON"
    assert entry["status"] == "OK"
    assert entry["has_defect"] is False
    assert entry["defect_fields"] == []

    assert manifest["schema_version"] == "2.1.1"
    assert manifest["run_kind"] == "EVAL"
    assert "sha256" in manifest
    assert manifest["total_cases"] >= 1
    assert output_file.exists()
    assert manifest_file.exists()
