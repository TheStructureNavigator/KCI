from __future__ import annotations

import sqlite3

import pytest

from kci.observers.production import ProductionObserver
from kci.persistence import KciRepository, connect, initialize_database
from kci.runtime import run_observer
from tests.conftest import load_context


def test_findings_and_evidence_persist_in_sqlite(tmp_path) -> None:
    connection = connect(tmp_path / "kci.sqlite3")
    initialize_database(connection)
    repository = KciRepository(connection)
    context = load_context("unexplained_downtime.json")

    result = run_observer(ProductionObserver(), context, repository)
    stored = repository.list_findings()

    assert result.run.status == "succeeded"
    row = connection.execute("SELECT context_id FROM observer_runs WHERE run_id = ?", (result.run.run_id,)).fetchone()
    assert row["context_id"] == context.context_id
    config_row = connection.execute(
        "SELECT effective_configuration_json, candidates_count FROM observer_runs WHERE run_id = ?",
        (result.run.run_id,),
    ).fetchone()
    assert config_row["effective_configuration_json"] == '{"threshold_minutes":30}'
    assert config_row["candidates_count"] == 1
    assert len(stored) == 1
    assert stored[0].observer_run_id == result.run.run_id
    assert stored[0].finding_id == result.findings[0].finding_id
    assert [e.ref for e in stored[0].evidence] == [
        "event:unexplained:stop-001",
        "event:unexplained:stop-002",
    ]


def test_foreign_keys_are_enabled_and_enforced(tmp_path) -> None:
    connection = connect(tmp_path / "kci.sqlite3")
    initialize_database(connection)

    enabled = connection.execute("PRAGMA foreign_keys").fetchone()[0]
    assert enabled == 1

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO evidence (finding_id, dataset, snapshot_id, ref)
            VALUES (?, ?, ?, ?)
            """,
            ("missing", "dataset", "snapshot", "ref"),
        )
