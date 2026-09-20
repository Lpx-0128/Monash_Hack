import json
import hashlib
import sys
import os
import argparse
from pathlib import Path
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from .database import SessionLocal
from . import models, crud, schemas


def export_eval_cases(
    output_path: str = "submission.json",
    manifest_path: str = "manifest.json",
    required_ids_file: str = None,
    run_kind: str = "EVAL"
):
    """Export finalized automated EVAL machine assessments in organizer submission shape.

    Contract §11:
    - Pure export of successfully finalized automated EVAL machine assessments.
    - Fails closed if any required case lacks a valid finalized assessment.
    - Generates companion release manifest with SHA-256 hash.
    """
    db: Session = SessionLocal()
    try:
        cases = db.query(models.CaseModel).all()
        eval_cases = []
        for c in cases:
            schema_case = crud.map_db_to_schema(c)
            if schema_case.run.kind.value == run_kind:
                eval_cases.append(schema_case)

        # Optional required IDs check
        required_ids = None
        if required_ids_file and os.path.exists(required_ids_file):
            with open(required_ids_file, "r", encoding="utf-8") as f:
                required_ids = set(line.strip() for line in f if line.strip())

        submission = {}
        missing_assessments = []
        selected_runs = {}

        for case in eval_cases:
            case_id = case.case_id
            if case.machine_assessment is None or case.email.category is None:
                missing_assessments.append(case_id)
                continue

            submission[case_id] = {
                "category": case.email.category.value,
                "status": case.machine_assessment.status.value,
                "review_reason": case.machine_assessment.review_reason.value if case.machine_assessment.review_reason else None,
                "has_defect": case.machine_assessment.has_defect,
                "defect_fields": [f.value for f in case.machine_assessment.defect_fields],
            }
            selected_runs[case_id] = case.run.run_id

        # Check for missing required IDs
        if required_ids:
            missing_required = required_ids - set(submission.keys())
            if missing_required:
                raise RuntimeError(f"FAIL CLOSED: {len(missing_required)} required email IDs missing from export: {sorted(missing_required)[:10]}")

        # Check for missing assessments in existing cases
        if missing_assessments:
            raise RuntimeError(f"FAIL CLOSED: {len(missing_assessments)} cases lack finalized machine assessment: {missing_assessments[:10]}")

        # Write formatted submission JSON
        out_path = Path(output_path)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(submission, f, indent=2, sort_keys=True)

        # Calculate SHA-256
        with open(out_path, "rb") as f:
            sha256_hash = hashlib.sha256(f.read()).hexdigest()

        # Write release manifest
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        manifest = {
            "schema_version": "2.1.1",
            "run_kind": run_kind,
            "input_version": "v1",
            "config_version": "v1",
            "created_at": now,
            "total_cases": len(submission),
            "sha256": sha256_hash,
            "selected_run_ids": selected_runs
        }

        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, sort_keys=True)

        print(f"Exported {len(submission)} cases to {output_path} (SHA-256: {sha256_hash})")
        print(f"Release manifest written to {manifest_path}")
        return submission, manifest
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export finalized EVAL cases per Contract §11")
    parser.add_argument("--output", type=str, default="submission.json", help="Output file path")
    parser.add_argument("--manifest", type=str, default="manifest.json", help="Manifest file path")
    parser.add_argument("--required-ids", type=str, default=None, help="File containing required email IDs")
    parser.add_argument("--run-kind", type=str, default="EVAL", choices=["DEMO", "EVAL"])
    args = parser.parse_args()

    try:
        export_eval_cases(
            output_path=args.output,
            manifest_path=args.manifest,
            required_ids_file=args.required_ids,
            run_kind=args.run_kind
        )
    except RuntimeError as e:
        sys.stderr.write(f"{e}\n")
        sys.exit(1)
