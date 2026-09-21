"""Upgrade populated pre-C1 snapshots without losing cases or decisions."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from backend.database import Base, init_db
from backend.models import CaseModel, RunSnapshotModel, AcceptedDecisionModel
from backend import crud, database, worker


def _legacy_database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}", connect_args={"timeout": 10})
    with engine.begin() as connection:
        # Exact columns present at 675f0d3, before machine_state/config_manifest.
        connection.execute(text('''CREATE TABLE run_snapshots (
            run_id VARCHAR PRIMARY KEY, case_id VARCHAR NOT NULL REFERENCES cases(case_id),
            input_version VARCHAR NOT NULL, config_version VARCHAR NOT NULL,
            source_manifest JSON NOT NULL, classification JSON, created_at VARCHAR NOT NULL)'''))
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(CaseModel(case_id="legacy", workflow_status="AWAITING_HUMAN",
                         follow_up="NONE", created_at="t", updated_at="t",
                         run={"run_id": "old"}, email={}, metrics={}))
        db.flush()
        db.execute(text('''INSERT INTO run_snapshots VALUES
            ('old', 'legacy', 'input', 'old-policy', '{}', '{"category":"BL_COMPARISON"}', 't')'''))
        db.add(AcceptedDecisionModel(decision_id="pending", case_id="legacy", run_id="old",
                                    review_id="review", payload={"action": "ACKNOWLEDGE"},
                                    created_at="t"))
        db.commit()
    return engine


def test_upgrade_preserves_rows_and_allows_new_snapshots(tmp_path):
    engine = _legacy_database(tmp_path)
    try:
        init_db(engine)
        init_db(engine)
        with Session(engine) as db:
            old = db.get(RunSnapshotModel, "old")
            assert old.classification == {"category": "BL_COMPARISON"}
            assert old.config_version == "old-policy"
            assert old.machine_state is None and old.config_manifest is None
            assert db.get(CaseModel, "legacy").workflow_status == "AWAITING_HUMAN"
            pending = db.get(AcceptedDecisionModel, "pending")
            assert pending.applied_at is None
            assert pending.payload == {"action": "ACKNOWLEDGE"}
            db.add(RunSnapshotModel(run_id="new", case_id="legacy", input_version="i",
                                    config_version="new-policy", source_manifest={},
                                    machine_state={"new": True}, config_manifest={"v": 2}, created_at="t"))
            db.commit()
            assert db.get(RunSnapshotModel, "new").machine_state == {"new": True}
            assert db.execute(text("SELECT count(*) FROM schema_migrations")).scalar_one() == 1
    finally:
        engine.dispose()


def test_concurrent_upgrade_is_serialized(tmp_path):
    engine = _legacy_database(tmp_path)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: init_db(engine), range(2)))
        assert {"machine_state", "config_manifest"} <= {
            c["name"] for c in inspect(engine).get_columns("run_snapshots")}
    finally:
        engine.dispose()


def test_fresh_install_is_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    try:
        init_db(engine)
        init_db(engine)
        with Session(engine) as db:
            assert db.query(RunSnapshotModel).all() == []
    finally:
        engine.dispose()


def test_legacy_interpretation_has_controlled_refusal(tmp_path, monkeypatch):
    engine = _legacy_database(tmp_path)
    try:
        init_db(engine)
        monkeypatch.setattr(crud, "load_input_snapshot", lambda *a: SimpleNamespace(input_version="input"))
        monkeypatch.setattr(crud, "intelligence_config", lambda: SimpleNamespace(config_identity=lambda: "old-policy"))
        case = SimpleNamespace(case_id="legacy", email=SimpleNamespace(email_id="legacy"),
                               run=SimpleNamespace(kind="DEMO"))
        with Session(engine) as db:
            with pytest.raises(worker.RunStateUnavailable, match="recorded no machine state"):
                worker.load_working_state(db, case, "old")
            assert db.get(AcceptedDecisionModel, "pending").applied_at is None
    finally:
        engine.dispose()


def test_real_worker_processes_new_run_after_upgrade(tmp_path, monkeypatch):
    engine = _legacy_database(tmp_path)
    try:
        init_db(engine)
        factory = sessionmaker(bind=engine)
        monkeypatch.setattr(database, "SessionLocal", factory)
        email_id = "email_demo_match"
        with factory() as db:
            case = crud.create_case_with_job(db, email_id)
        worker.process_case(email_id, job_id="job_initial", job_run_id=case.run.run_id)
        with factory() as db:
            stored = db.get(RunSnapshotModel, case.run.run_id)
            assert stored.machine_state
            assert stored.config_manifest
            result = crud.map_db_to_schema(db.get(CaseModel, email_id))
            assert result.machine_assessment.status == "OK"
    finally:
        engine.dispose()


def test_partial_upgrade_adds_only_missing_column(tmp_path):
    engine = _legacy_database(tmp_path)
    try:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE run_snapshots ADD COLUMN machine_state JSON"))
            connection.execute(text("UPDATE run_snapshots SET machine_state = :state"),
                               {"state": '{"preserve":true}'})
        init_db(engine)
        with Session(engine) as db:
            assert db.get(RunSnapshotModel, "old").machine_state == {"preserve": True}
            assert db.get(RunSnapshotModel, "old").config_manifest is None
    finally:
        engine.dispose()
