"""Startup schema migration for the supported SQLite deployment.

Additive only: legacy interpretations remain NULL, never reconstructed. The
worker's existing snapshot checks refuse them and require explicit reprocessing.
Run this before starting workers (database.init_db does so at application import).
"""

from sqlalchemy import Column, MetaData, String, Table, inspect, select, text

MIGRATION_ID = "0001_run_snapshot_interpretation"
_metadata = MetaData()
_versions = Table("schema_migrations", _metadata,
                  Column("version", String, primary_key=True))


def initialize_schema(engine, application_metadata):
    """Create fresh tables or upgrade an existing database without losing rows.

    SQLite's immediate transaction serializes simultaneous application startups.
    DDL and the version record commit together. Unsupported existing deployments
    fail before any application tables are modified, rather than starting a worker
    against an incompatible schema.
    """
    with engine.connect() as connection:
        try:
            if engine.dialect.name == "sqlite":
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            inspector = inspect(connection)
            existing = inspector.has_table("run_snapshots")
            columns = {c["name"] for c in inspector.get_columns("run_snapshots")} if existing else set()
            missing = {"machine_state", "config_manifest"} - columns if existing else set()
            if missing and engine.dialect.name != "sqlite":
                raise RuntimeError(
                    "Existing run_snapshots requires migration 0001; automatic "
                    "upgrade supports SQLite only. Apply the equivalent nullable "
                    "JSON columns using your database migration process before startup."
                )
            application_metadata.create_all(bind=connection)
            _metadata.create_all(bind=connection)
            # Repair partially upgraded schemas too; a version row alone is
            # never proof that both required columns exist.
            for column in sorted(missing):
                connection.execute(text(f"ALTER TABLE run_snapshots ADD COLUMN {column} JSON"))
            recorded = connection.execute(select(_versions.c.version).where(
                _versions.c.version == MIGRATION_ID)).first()
            if recorded is None:
                connection.execute(_versions.insert().values(version=MIGRATION_ID))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
