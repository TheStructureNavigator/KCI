"""Wave 3B: content-addressed ObservationContext manifest (H-01)."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sqlite3
from typing import Any

import pytest

from kci.contracts import (
    DatasetEnvelope,
    DatasetReference,
    ObservationContext,
    ObservationContextIntegrityError,
    ObservationContextManifest,
    ObserverRun,
    SnapshotIntegrityError,
    UnknownObservationContext,
)
from kci.observers.production import ProductionObserver
from kci.persistence import KciRepository, connect, initialize_database
from kci.runtime import run_observer
from tests.conftest import load_fixture

FIXTURE_CONTEXT_IDS = {
    "bad_oee.json": "context_sha256:efc6978bc88ef3ba97f3d24c965a06d3b19d82c0c7e6d87396852c611065b5c6",
    "many_short_stops.json": "context_sha256:809f6deddb143e82ab62b051aae205cd91971097be3079f20087ba936350b9ef",
    "mixed_problem.json": "context_sha256:345a482e22fea67cd4c2c4d9a8fac1d65de58f25218e5e1f782c8f75942740f3",
    "normal_shift.json": "context_sha256:5e588ecf4c39726e059f5b30ce77ff67908d55cc7b5ada9dde11a0c7e76f409c",
    "nothing_interesting.json": "context_sha256:552f02a3d8fd93e439284032072db1ca86243ed0105488167b9fe4b7de57702d",
    "unexplained_downtime.json": "context_sha256:4b1f11dfaed64161ade0ee846f427d86e91ea2fa479b43e875ed8eef74cb7763",
}
# Recorded from the pre-Wave-3B implementation: normal_shift + a renamed mixed_problem as the second dataset.
TWO_DATASET_CONTEXT_ID = "context_sha256:a089d6ce279ac53661a7a97a995b83f13b19856027cd7643cf624281fe64faea"


def make_repo(tmp_path, cls=KciRepository, name="kci.sqlite3"):
    connection = connect(tmp_path / name)
    initialize_database(connection)
    return cls(connection)


def variant(fixture: str, *, dataset=None, snapshot_id=None, dataset_version=None, rehash=True, mutate=None) -> DatasetEnvelope:
    payload = load_fixture(fixture).model_dump(mode="json")
    if dataset is not None:
        payload["dataset"] = dataset
    if snapshot_id is not None:
        payload["snapshot_id"] = snapshot_id
    if dataset_version is not None:
        payload["dataset_version"] = dataset_version
    if mutate is not None:
        mutate(payload)
    if rehash:
        payload["content_hash"] = DatasetEnvelope.model_validate(payload).computed_content_hash()
    return DatasetEnvelope.model_validate(payload)


def primary() -> DatasetEnvelope:
    return load_fixture("unexplained_downtime.json")


def extra(name: str, snapshot_id: str, version: int = 1) -> DatasetEnvelope:
    return variant("normal_shift.json", dataset=name, snapshot_id=snapshot_id, dataset_version=version)


def counts(repo) -> dict[str, int]:
    tables = ("observation_contexts", "observation_context_datasets", "observer_runs", "findings", "evidence")
    return {t: repo.connection.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}


class SpyObserver(ProductionObserver):
    def __init__(self) -> None:
        super().__init__()
        self.called = 0

    def observe(self, context):
        self.called += 1
        return super().observe(context)


# --- Part A: canonical identity ---------------------------------------------------------------


@pytest.mark.parametrize("fixture", sorted(FIXTURE_CONTEXT_IDS))
def test_context_id_is_byte_identical_to_the_pre_manifest_implementation(fixture) -> None:
    envelope = load_fixture(fixture)
    context = ObservationContext(datasets=(envelope,))

    independent = hashlib.sha256(
        json.dumps(
            [
                {
                    "content_hash": envelope.content_hash,
                    "dataset": envelope.dataset,
                    "dataset_version": envelope.dataset_version,
                    "snapshot_id": envelope.snapshot_id,
                }
            ],
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    assert context.context_id == FIXTURE_CONTEXT_IDS[fixture]  # golden value from the old implementation
    assert context.context_id == f"context_sha256:{independent}"  # independent re-computation
    assert context.manifest().context_id == context.context_id


def test_multi_dataset_context_id_is_byte_identical_to_the_pre_manifest_implementation() -> None:
    second = variant("mixed_problem.json", dataset="synthetic.production.shift.secondary")
    context = ObservationContext(datasets=(load_fixture("normal_shift.json"), second))

    assert context.context_id == TWO_DATASET_CONTEXT_ID
    assert ObservationContext(datasets=(second, load_fixture("normal_shift.json"))).context_id == TWO_DATASET_CONTEXT_ID


def test_manifest_and_reference_are_frozen_and_hold_identity_only() -> None:
    manifest = ObservationContext(datasets=(primary(), extra("synthetic.b", "b-1"))).manifest()

    assert set(DatasetReference.model_fields) == {"dataset", "dataset_version", "snapshot_id", "content_hash"}
    assert set(ObservationContextManifest.model_fields) == {"references"}
    with pytest.raises(ValueError):
        manifest.references = ()  # type: ignore[misc]
    with pytest.raises(ValueError):
        manifest.references[0].snapshot_id = "x"  # type: ignore[misc]
    dumped = manifest.model_dump_json()
    for payload_marker in ("downtime_events", "evidence_records", "event:unexplained", "oee"):
        assert payload_marker not in dumped


# --- Part B/F: reconstruction, ordering, dedup, verification ------------------------------------


def test_multi_dataset_manifest_is_reconstructed_from_the_database_alone(tmp_path) -> None:
    repo = make_repo(tmp_path)
    datasets = (primary(), extra("synthetic.maintenance.log", "maint-001", 3), extra("synthetic.quality.scrap", "scrap-777", 4))
    context = ObservationContext(datasets=datasets)

    result = run_observer(ProductionObserver(), context, repo)
    reconstructed = repo.get_observation_context_for_run(result.run.run_id)

    assert isinstance(reconstructed, ObservationContextManifest)
    assert reconstructed.context_id == result.run.context_id == context.context_id
    assert {(r.dataset, r.dataset_version, r.snapshot_id, r.content_hash) for r in reconstructed.references} == {
        (d.dataset, d.dataset_version, d.snapshot_id, d.content_hash) for d in datasets
    }
    assert [r.dataset for r in reconstructed.references] == sorted(d.dataset for d in datasets)


def test_contexts_differing_only_in_a_non_first_dataset_reconstruct_differently(tmp_path) -> None:
    repo = make_repo(tmp_path)
    a = run_observer(ProductionObserver(), ObservationContext(datasets=(primary(), extra("synthetic.a", "a-1"))), repo)
    b = run_observer(ProductionObserver(), ObservationContext(datasets=(primary(), extra("synthetic.b", "b-9", 4))), repo)

    manifest_a = repo.get_observation_context_for_run(a.run.run_id)
    manifest_b = repo.get_observation_context_for_run(b.run.run_id)

    assert manifest_a != manifest_b
    assert "synthetic.a" in {r.dataset for r in manifest_a.references}
    assert "synthetic.b" in {r.dataset for r in manifest_b.references}


def test_tuple_order_does_not_affect_manifest_identity_or_persisted_rows(tmp_path) -> None:
    repo = make_repo(tmp_path)
    one, two = primary(), extra("synthetic.second", "second-1")

    first = run_observer(ProductionObserver(), ObservationContext(datasets=(one, two)), repo)
    rows_after_first = repo.connection.execute("SELECT * FROM observation_context_datasets ORDER BY dataset").fetchall()
    second = run_observer(ProductionObserver(), ObservationContext(datasets=(two, one)), repo)
    rows_after_second = repo.connection.execute("SELECT * FROM observation_context_datasets ORDER BY dataset").fetchall()

    assert first.run.context_id == second.run.context_id
    assert ObservationContext(datasets=(two, one)).manifest() == ObservationContext(datasets=(one, two)).manifest()
    assert [tuple(r) for r in rows_after_first] == [tuple(r) for r in rows_after_second]
    assert repo.get_observation_context_for_run(first.run.run_id) == repo.get_observation_context_for_run(second.run.run_id)


def test_runs_sharing_a_context_share_one_manifest(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = ObservationContext(datasets=(primary(), extra("synthetic.second", "second-1")))

    for _ in range(3):
        run_observer(ProductionObserver(), context, repo)

    assert counts(repo)["observer_runs"] == 3
    assert counts(repo)["observation_contexts"] == 1
    assert counts(repo)["observation_context_datasets"] == 2


def test_saving_the_same_manifest_repeatedly_is_idempotent(tmp_path) -> None:
    repo = make_repo(tmp_path)
    manifest = ObservationContext(datasets=(primary(), extra("synthetic.second", "second-1"))).manifest()

    repo.save_observation_context(manifest)
    repo.save_observation_context(manifest)

    assert counts(repo)["observation_contexts"] == 1
    assert counts(repo)["observation_context_datasets"] == 2
    assert repo.get_observation_context(manifest.context_id) == manifest


def test_retrieval_recomputes_and_verifies_the_context_hash(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = ObservationContext(datasets=(primary(), extra("synthetic.second", "second-1")))
    run_observer(ProductionObserver(), context, repo)

    manifest = repo.get_observation_context(context.context_id)

    assert manifest.context_id == context.context_id
    assert manifest.context_id == ObservationContext(datasets=tuple(reversed(context.datasets))).context_id


@pytest.mark.parametrize(
    "corruption",
    [
        "UPDATE observation_context_datasets SET content_hash = 'sha256:forged' WHERE dataset = 'synthetic.second'",
        "UPDATE observation_context_datasets SET dataset_version = 99 WHERE dataset = 'synthetic.second'",
        "UPDATE observation_context_datasets SET snapshot_id = 'forged-1' WHERE dataset = 'synthetic.second'",
        "UPDATE observation_context_datasets SET dataset = 'synthetic.renamed' WHERE dataset = 'synthetic.second'",
        "DELETE FROM observation_context_datasets WHERE dataset = 'synthetic.second'",
        "DELETE FROM observation_context_datasets",
        "INSERT INTO observation_context_datasets SELECT context_id, 'synthetic.extra', 1, 'extra-1', 'sha256:x' FROM observation_contexts",
    ],
)
def test_corrupted_manifests_are_rejected_on_retrieval(tmp_path, corruption) -> None:
    repo = make_repo(tmp_path)
    context = ObservationContext(datasets=(primary(), extra("synthetic.second", "second-1")))
    run = run_observer(ProductionObserver(), context, repo)
    repo.connection.execute(corruption)
    repo.connection.commit()

    with pytest.raises(ObservationContextIntegrityError):
        repo.get_observation_context(context.context_id)
    with pytest.raises(ObservationContextIntegrityError):
        repo.get_observation_context_for_run(run.run.run_id)


def test_conflicting_membership_for_an_existing_context_id_is_never_silently_ignored(tmp_path) -> None:
    repo = make_repo(tmp_path)
    manifest = ObservationContext(datasets=(primary(), extra("synthetic.second", "second-1"))).manifest()
    repo.save_observation_context(manifest)
    repo.connection.execute("UPDATE observation_context_datasets SET content_hash = 'sha256:forged' WHERE dataset = 'synthetic.second'")
    repo.connection.commit()

    with pytest.raises(ObservationContextIntegrityError):
        repo.save_observation_context(manifest)


def test_run_must_match_its_manifest(tmp_path) -> None:
    repo = make_repo(tmp_path)
    manifest = ObservationContext(datasets=(primary(),)).manifest()
    run = ObserverRun.started("o", "1", "context_sha256:other", {}, "d", "s")

    with pytest.raises(ObservationContextIntegrityError):
        repo.record_observer_execution(run, manifest)
    assert counts(repo)["observer_runs"] == 0


# --- Part C: atomicity ------------------------------------------------------------------------


class FailingRepository(KciRepository):
    failure_point = ""

    def _insert_observation_context(self, manifest):
        super()._insert_observation_context(manifest)
        if self.failure_point == "after_manifest":
            raise RuntimeError("injected failure after manifest write")

    def _insert_observer_run(self, run):
        if self.failure_point == "run":
            raise RuntimeError("injected failure writing the run")
        super()._insert_observer_run(run)

    def _insert_finding(self, observer_run_id, finding):
        super()._insert_finding(observer_run_id, finding)
        if self.failure_point == "finding":
            raise RuntimeError("injected failure after a finding write")


@pytest.mark.parametrize("failure_point", ["after_manifest", "run", "finding"])
def test_a_failure_in_any_write_leaves_no_partially_recorded_execution(tmp_path, failure_point) -> None:
    repo = make_repo(tmp_path, FailingRepository)
    repo.failure_point = failure_point
    context = ObservationContext(datasets=(primary(), extra("synthetic.second", "second-1")))

    with pytest.raises(RuntimeError, match="injected"):
        run_observer(ProductionObserver(), context, repo)

    assert set(counts(repo).values()) == {0}
    assert not repo.connection.in_transaction
    repo.failure_point = ""
    run_observer(ProductionObserver(), context, repo)  # the repository remains usable
    assert counts(repo)["observer_runs"] == 1 and counts(repo)["observation_contexts"] == 1


def test_failure_does_not_disturb_previously_recorded_executions(tmp_path) -> None:
    repo = make_repo(tmp_path, FailingRepository)
    good = ObservationContext(datasets=(load_fixture("normal_shift.json"),))
    run_observer(ProductionObserver(), good, repo)
    before = counts(repo)
    repo.failure_point = "run"

    with pytest.raises(RuntimeError):
        run_observer(ProductionObserver(), ObservationContext(datasets=(primary(),)), repo)

    assert counts(repo) == before


# --- Part E / D7: requirements_failed ----------------------------------------------------------


def test_requirements_failed_run_for_a_missing_dataset_has_a_reconstructable_manifest(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = ObservationContext(datasets=(extra("synthetic.not.the.required.one", "other-1"),))

    result = run_observer(ProductionObserver(), context, repo)

    assert result.run.status == "requirements_failed"
    manifest = repo.get_observation_context_for_run(result.run.run_id)
    assert manifest == context.manifest() and manifest.context_id == result.run.context_id


def test_requirements_failed_run_for_an_unsupported_version_has_a_manifest(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = ObservationContext(datasets=(variant("unexplained_downtime.json", dataset_version=99),))

    result = run_observer(ProductionObserver(), context, repo)

    assert result.run.status == "requirements_failed"
    assert repo.get_observation_context_for_run(result.run.run_id) == context.manifest()


def test_requirements_failed_run_for_a_content_hash_mismatch_records_the_declared_identity(tmp_path) -> None:
    repo = make_repo(tmp_path)
    tampered = variant("unexplained_downtime.json", rehash=False, mutate=lambda p: p["data"]["summary"].update(oee=0.01))
    genuine = ObservationContext(datasets=(primary(),))

    result = run_observer(ProductionObserver(), ObservationContext(datasets=(tampered,)), repo)

    assert result.run.status == "requirements_failed"
    assert "content_hash mismatch" in result.run.error
    manifest = repo.get_observation_context_for_run(result.run.run_id)
    assert manifest.context_id == genuine.context_id  # the declared identity, as before (context_id semantics unchanged)
    assert manifest == genuine.manifest()


def test_execution_failure_and_zero_findings_runs_also_have_manifests(tmp_path) -> None:
    repo = make_repo(tmp_path)

    class Exploding(ProductionObserver):
        def observe(self, context):
            raise RuntimeError("observer exploded")

    failed = run_observer(Exploding(), ObservationContext(datasets=(primary(),)), repo)
    empty = run_observer(ProductionObserver(), ObservationContext(datasets=(load_fixture("normal_shift.json"),)), repo)

    assert failed.run.status == "failed" and empty.run.status == "succeeded"
    for result in (failed, empty):
        assert isinstance(repo.get_observation_context_for_run(result.run.run_id), ObservationContextManifest)


# --- D4/D5: legacy behavior ---------------------------------------------------------------------


def test_legacy_run_without_manifest_is_explicitly_unknown_and_never_backfilled(tmp_path) -> None:
    repo = make_repo(tmp_path)
    legacy = ObserverRun.started("production.unexplained_downtime", "1", "context_sha256:legacy", {}, "ds", "snap")
    legacy.status = "succeeded"
    repo.save_observer_run(legacy)  # the pre-manifest write path: run only

    result = repo.get_observation_context_for_run(legacy.run_id)

    assert isinstance(result, UnknownObservationContext)
    assert result.context_id == "context_sha256:legacy"
    assert "no observation manifest" in result.reason
    assert counts(repo)["observation_contexts"] == 0 and counts(repo)["observation_context_datasets"] == 0
    assert isinstance(repo.get_observation_context("context_sha256:never-seen"), UnknownObservationContext)
    with pytest.raises(LookupError):
        repo.get_observation_context_for_run("observer_run_missing")


def test_legacy_columns_are_preserved_but_are_not_canonical_provenance(tmp_path) -> None:
    repo = make_repo(tmp_path)
    one, two = primary(), extra("synthetic.zzz", "zzz-1")

    first = run_observer(ProductionObserver(), ObservationContext(datasets=(one, two)), repo)
    second = run_observer(ProductionObserver(), ObservationContext(datasets=(two, one)), repo)

    rows = {
        r["run_id"]: (r["dataset"], r["snapshot_id"])
        for r in repo.connection.execute("SELECT run_id, dataset, snapshot_id FROM observer_runs")
    }
    assert rows[first.run.run_id] == (one.dataset, one.snapshot_id)  # first as supplied
    assert rows[second.run.run_id] == (two.dataset, two.snapshot_id)  # differs with tuple order: non-authoritative
    assert repo.get_observation_context_for_run(first.run.run_id) == repo.get_observation_context_for_run(second.run.run_id)


def test_existing_database_is_extended_additively_without_touching_legacy_rows(tmp_path) -> None:
    repo = make_repo(tmp_path)
    legacy = ObserverRun.started("o", "1", "context_sha256:legacy", {"k": 1}, "ds", "snap")
    legacy.status = "succeeded"
    repo.save_observer_run(legacy)
    for statement in (
        "DROP INDEX idx_observation_context_datasets_snapshot",
        "DROP INDEX idx_observer_runs_context_id",
        "DROP TABLE observation_context_datasets",
        "DROP TABLE observation_contexts",
    ):
        repo.connection.execute(statement)
    repo.connection.commit()
    before = [tuple(r) for r in repo.connection.execute("SELECT * FROM observer_runs")]
    columns_before = [r["name"] for r in repo.connection.execute("PRAGMA table_info(observer_runs)")]

    initialize_database(repo.connection)
    initialize_database(repo.connection)  # idempotent

    assert [tuple(r) for r in repo.connection.execute("SELECT * FROM observer_runs")] == before
    assert [r["name"] for r in repo.connection.execute("PRAGMA table_info(observer_runs)")] == columns_before
    assert isinstance(repo.get_observation_context_for_run(legacy.run_id), UnknownObservationContext)
    new = run_observer(ProductionObserver(), ObservationContext(datasets=(primary(),)), repo)
    assert isinstance(repo.get_observation_context_for_run(new.run.run_id), ObservationContextManifest)


def test_schema_adds_exactly_the_two_tables_and_their_indexes(tmp_path) -> None:
    repo = make_repo(tmp_path)

    tables = {r["name"] for r in repo.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    indexes = {r["name"] for r in repo.connection.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'")}
    columns = [r["name"] for r in repo.connection.execute("PRAGMA table_info(observation_context_datasets)")]

    assert {"observation_contexts", "observation_context_datasets"} <= tables
    assert indexes == {"idx_observation_context_datasets_snapshot", "idx_observer_runs_context_id"}
    assert columns == ["context_id", "dataset", "dataset_version", "snapshot_id", "content_hash"]  # identity only


# --- Part D: snapshot integrity -----------------------------------------------------------------


def test_duplicate_snapshot_id_within_a_context_is_rejected() -> None:
    with pytest.raises(ValueError, match="same snapshot_id twice"):
        ObservationContext(datasets=(primary(), extra("synthetic.other", primary().snapshot_id)))
    with pytest.raises(ValueError, match="same snapshot_id twice"):
        ObservationContextManifest(
            references=(
                DatasetReference(dataset="a", dataset_version=1, snapshot_id="s", content_hash="sha256:1"),
                DatasetReference(dataset="b", dataset_version=1, snapshot_id="s", content_hash="sha256:2"),
            )
        )
    with pytest.raises(ValueError, match="one Snapshot per Dataset"):
        ObservationContextManifest(
            references=(
                DatasetReference(dataset="a", dataset_version=1, snapshot_id="s1", content_hash="sha256:1"),
                DatasetReference(dataset="a", dataset_version=1, snapshot_id="s2", content_hash="sha256:2"),
            )
        )


@pytest.mark.parametrize(
    "conflicting",
    [
        lambda: variant("unexplained_downtime.json", mutate=lambda p: p["data"]["summary"].update(oee=0.01)),  # same ids, new content hash
        lambda: variant("unexplained_downtime.json", dataset="synthetic.production.shift.renamed"),  # different dataset identity
        lambda: variant("unexplained_downtime.json", dataset_version=2),  # different dataset_version
    ],
    ids=["content_hash", "dataset", "dataset_version"],
)
def test_conflicting_reuse_of_a_recorded_snapshot_id_is_rejected_before_any_work(tmp_path, conflicting) -> None:
    repo = make_repo(tmp_path)
    run_observer(ProductionObserver(), ObservationContext(datasets=(primary(),)), repo)
    before = counts(repo)
    observer = SpyObserver()
    clash = conflicting()
    assert clash.snapshot_id == primary().snapshot_id

    with pytest.raises(SnapshotIntegrityError) as caught:
        run_observer(observer, ObservationContext(datasets=(clash,)), repo)

    assert observer.called == 0  # rejected before the Observer ran
    assert counts(repo) == before  # nothing recorded for the rejected execution
    message = str(caught.value)
    assert primary().snapshot_id in message
    for payload_marker in ("downtime_events", "evidence_records", "oee", "event:unexplained"):
        assert payload_marker not in message


def test_conflict_is_detected_for_a_non_first_dataset_in_a_larger_context(tmp_path) -> None:
    repo = make_repo(tmp_path)
    run_observer(ProductionObserver(), ObservationContext(datasets=(primary(), extra("synthetic.second", "second-1"))), repo)
    before = counts(repo)

    with pytest.raises(SnapshotIntegrityError):
        run_observer(
            ProductionObserver(),
            ObservationContext(datasets=(primary(), extra("synthetic.second", "second-1", version=7))),
            repo,
        )
    assert counts(repo) == before


def test_conflict_is_also_enforced_when_saving_a_manifest_directly(tmp_path) -> None:
    repo = make_repo(tmp_path)
    repo.save_observation_context(ObservationContext(datasets=(primary(),)).manifest())
    forged = ObservationContext(datasets=(variant("unexplained_downtime.json", dataset_version=5),)).manifest()

    with pytest.raises(SnapshotIntegrityError):
        repo.save_observation_context(forged)
    assert counts(repo)["observation_contexts"] == 1


def test_consistent_reuse_of_a_snapshot_in_another_context_is_allowed(tmp_path) -> None:
    repo = make_repo(tmp_path)
    run_observer(ProductionObserver(), ObservationContext(datasets=(primary(),)), repo)

    result = run_observer(ProductionObserver(), ObservationContext(datasets=(primary(), extra("synthetic.new", "new-1"))), repo)

    assert result.run.status == "succeeded"
    assert counts(repo)["observation_contexts"] == 2


def test_a_conflict_detected_at_write_time_rolls_back_everything(tmp_path) -> None:
    """The fail-fast pre-check is bypassed to prove the write itself is also guarded and atomic."""

    class SkipPreCheck(KciRepository):
        def ensure_snapshot_consistency(self, manifest):
            return None

    repo = make_repo(tmp_path, SkipPreCheck)
    run_observer(ProductionObserver(), ObservationContext(datasets=(primary(),)), repo)
    before = counts(repo)
    clash = variant("unexplained_downtime.json", dataset_version=2)

    with pytest.raises(SnapshotIntegrityError):
        run_observer(ProductionObserver(), ObservationContext(datasets=(clash,)), repo)

    assert counts(repo) == before


# --- Findings / provenance ---------------------------------------------------------------------


def test_every_finding_evidence_reference_belongs_to_its_runs_manifest(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = ObservationContext(datasets=(primary(), extra("synthetic.second", "second-1")))
    result = run_observer(ProductionObserver(), context, repo)
    assert result.findings, "fixture must produce a finding"

    manifest = repo.get_observation_context_for_run(result.run.run_id)
    members = {(r.dataset, r.snapshot_id) for r in manifest.references}
    rows = repo.connection.execute(
        """
        SELECT e.dataset, e.snapshot_id
        FROM evidence e JOIN findings f ON f.finding_id = e.finding_id
        WHERE f.observer_run_id = ?
        """,
        (result.run.run_id,),
    ).fetchall()
    assert rows and all((r["dataset"], r["snapshot_id"]) in members for r in rows)


def test_findings_are_persisted_with_their_run_in_the_same_transaction(tmp_path) -> None:
    repo = make_repo(tmp_path)

    result = run_observer(ProductionObserver(), ObservationContext(datasets=(primary(),)), repo)

    assert counts(repo)["findings"] == len(result.findings) == 1
    assert [f.finding_id for f in repo.list_findings()] == [f.finding_id for f in result.findings]


def test_runs_without_a_repository_still_work() -> None:
    result = run_observer(ProductionObserver(), ObservationContext(datasets=(primary(),)))

    assert result.run.status == "succeeded"


# --- Correction B: orphaned membership is corruption, not legacy ---------------------------------


def test_membership_rows_without_a_context_record_are_an_integrity_error(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = ObservationContext(datasets=(primary(), extra("synthetic.second", "second-1")))
    run = run_observer(ProductionObserver(), context, repo)
    repo.connection.execute("PRAGMA foreign_keys = OFF")
    repo.connection.execute("DELETE FROM observation_contexts WHERE context_id = ?", (context.context_id,))
    repo.connection.commit()

    with pytest.raises(ObservationContextIntegrityError, match="context record is missing"):
        repo.get_observation_context(context.context_id)
    with pytest.raises(ObservationContextIntegrityError):
        repo.get_observation_context_for_run(run.run.run_id)


def test_no_manifest_and_no_membership_is_still_unknown_and_valid_manifests_still_reconstruct(tmp_path) -> None:
    repo = make_repo(tmp_path)
    context = ObservationContext(datasets=(primary(), extra("synthetic.second", "second-1")))
    run_observer(ProductionObserver(), context, repo)

    assert isinstance(repo.get_observation_context("context_sha256:never-recorded"), UnknownObservationContext)
    assert repo.get_observation_context(context.context_id) == context.manifest()
    # Orphans of a different context do not turn unrelated lookups into errors.
    assert isinstance(repo.get_observation_context("context_sha256:other"), UnknownObservationContext)


# --- Correction C: CLI error boundary ------------------------------------------------------------


def _write_dataset(path, envelope: DatasetEnvelope) -> None:
    path.write_text(envelope.model_dump_json(), encoding="utf-8")


def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    from kci.cli import main

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


def test_cli_reports_a_snapshot_conflict_concisely_with_a_nonzero_exit_and_records_nothing(tmp_path) -> None:
    db = tmp_path / "cli.sqlite3"
    dataset_file = tmp_path / "dataset.json"
    _write_dataset(dataset_file, primary())
    assert _run_cli(["--dataset", str(dataset_file), "--db", str(db)])[0] == 0
    edited = variant("unexplained_downtime.json", mutate=lambda p: p["data"]["summary"].update(oee=0.5))
    _write_dataset(dataset_file, edited)

    exit_code, stdout, stderr = _run_cli(["--dataset", str(dataset_file), "--db", str(db)])

    assert exit_code == 2
    assert stdout == ""
    assert "Traceback" not in stderr
    assert stderr.count("\n") == 1  # one concise line
    assert "snapshot integrity conflict" in stderr and primary().snapshot_id in stderr
    for payload_marker in ("downtime_events", "evidence_records", "oee"):
        assert payload_marker not in stderr
    connection = connect(db)
    assert connection.execute("SELECT COUNT(*) FROM observer_runs").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM observation_contexts").fetchone()[0] == 1


def test_cli_does_not_swallow_unrelated_errors_and_keeps_normal_exit_codes(tmp_path) -> None:
    db = tmp_path / "cli.sqlite3"
    dataset_file = tmp_path / "dataset.json"
    _write_dataset(dataset_file, primary())

    assert _run_cli(["--dataset", str(dataset_file), "--db", str(db)])[0] == 0
    assert _run_cli(["--dataset", str(dataset_file), "--db", str(db)])[0] == 0  # identical re-run is not a conflict
    with pytest.raises(FileNotFoundError):
        _run_cli(["--dataset", str(tmp_path / "missing.json"), "--db", str(db)])
    wrong_dataset = tmp_path / "wrong.json"
    _write_dataset(wrong_dataset, extra("synthetic.not.required", "nr-1"))
    assert _run_cli(["--dataset", str(wrong_dataset), "--db", str(db)])[0] == 1  # requirements_failed, as before
