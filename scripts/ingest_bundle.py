#!/usr/bin/env python3
"""Batch-ingest participant bundle emails into shipping.db.

Reads emails from resources/sdoc-hackathon-bundle/inbox and processes them
through the document intelligence pipeline into SQLite so they appear in the
live frontend dashboard.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.database import SessionLocal, init_db
from backend import crud, worker, schemas, models

def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest hackathon bundle emails into database.")
    parser.add_argument("--source", type=Path, default=REPO_ROOT / "resources" / "sdoc-hackathon-bundle")
    parser.add_argument("--limit", type=int, default=0, help="Maximum emails to ingest (0 = all)")
    parser.add_argument("--clean-tests", action="store_true", help="Remove test_email_* rows before ingesting")
    parser.add_argument("--reprocess", action="store_true", help="Clear existing cases and reprocess from scratch")
    args = parser.parse_args()

    inbox_dir = args.source / "inbox"
    if not inbox_dir.exists():
        print(f"Inbox directory not found: {inbox_dir}", file=sys.stderr)
        return 1

    email_files = sorted(inbox_dir.glob("email_*.json"), key=lambda p: p.stem)
    if args.limit > 0:
        email_files = email_files[:args.limit]

    print(f"Found {len(email_files)} email records to process from {inbox_dir}")

    db = SessionLocal()
    try:
        if args.reprocess:
            print("Reprocessing requested: clearing existing cases and jobs...")
            db.query(models.JobModel).delete()
            db.query(models.RunSnapshotModel).delete()
            db.query(models.CaseModel).delete()
            db.commit()
            crud.reset_intelligence_cache()
        elif args.clean_tests:
            print("Cleaning up old test_email_* entries...")
            db.query(models.CaseModel).filter(models.CaseModel.case_id.like("test_email_%")).delete()
            db.query(models.JobModel).filter(models.JobModel.case_id.like("test_email_%")).delete()
            db.commit()

        existing_case_ids = set(r[0] for r in db.query(models.CaseModel.case_id).all())

        success_count = 0
        skip_count = 0
        fail_count = 0
        t0 = time.time()

        for idx, email_path in enumerate(email_files, 1):
            email_id = email_path.stem
            if email_id in existing_case_ids:
                # Check if already processed
                existing = crud.get_case(db, email_id)
                if existing and crud.map_db_to_schema(existing).machine_assessment is not None:
                    skip_count += 1
                    continue

            try:
                # Create case with job
                case = crud.create_case_with_job(
                    db, email_id, run_kind=schemas.RunKind.DEMO, public_caller=False
                )
                job = db.query(models.JobModel).filter_by(case_id=email_id, status="PENDING").first()
                if job:
                    worker.process_case(email_id, job.job_id, job.run_id)
                success_count += 1
                if idx % 25 == 0 or idx == len(email_files):
                    elapsed = time.time() - t0
                    print(f"Processed {idx}/{len(email_files)} ({success_count} new, {skip_count} cached, {fail_count} failed) in {elapsed:.1f}s")
            except Exception as e:
                fail_count += 1
                print(f"Failed {email_id}: {e}")

        total_elapsed = time.time() - t0
        print(f"\nCompleted: {success_count} ingested, {skip_count} skipped, {fail_count} failed in {total_elapsed:.1f}s")
        total_in_db = db.query(models.CaseModel).count()
        print(f"Total cases now in database: {total_in_db}")
        return 0
    finally:
        db.close()

if __name__ == "__main__":
    raise SystemExit(main())
