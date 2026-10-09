from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone

from kci.contracts import (
    DatasetReference,
    EntityReference,
    EvidenceReference,
    Finding,
    Insight,
    IntelligenceContext,
    IntelligenceRun,
    ModelRun,
    ObservationContextIntegrityError,
    ObservationContextManifest,
    ObserverRun,
    SnapshotIntegrityError,
    UnknownObservationContext,
)


def canonical_json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


class KciRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    @contextmanager
    def _atomic(self) -> Iterator[None]:
        """One all-or-nothing write transaction (BEGIN IMMEDIATE takes the write lock up front).

        If the caller already opened a transaction it is joined and finished by this block.
        """
        if not self.connection.in_transaction:
            self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.connection.rollback()
            raise
        self.connection.commit()

    def save_observer_run(self, run: ObserverRun) -> None:
        self._insert_observer_run(run)
        self.connection.commit()

    def _insert_observer_run(self, run: ObserverRun) -> None:
        self.connection.execute(
            """
            INSERT INTO observer_runs (
                run_id, observer_id, observer_version, context_id, effective_configuration_json,
                dataset, snapshot_id, started_at, finished_at, duration_ms, status, failure_category,
                candidates_count, findings_count, validation_failures_count, model_runs_count, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.run_id,
                run.observer_id,
                run.observer_version,
                run.context_id,
                canonical_json(run.effective_configuration),
                run.dataset,
                run.snapshot_id,
                run.started_at.isoformat(),
                run.finished_at.isoformat() if run.finished_at else None,
                run.duration_ms,
                run.status,
                run.failure_category,
                run.candidates_count,
                run.findings_count,
                run.validation_failures_count,
                run.model_runs_count,
                run.error,
            ),
        )

    def save_model_run(self, model_run: ModelRun) -> None:
        self.connection.execute(
                """
                INSERT INTO model_runs (
                run_id, observer_run_id, intelligence_run_id, provider, model, model_artifact_hash, quantization,
                inference_parameters_json, prompt_version, context_size, input_tokens, output_tokens,
                model_load_ms, prompt_eval_ms, generation_ms, total_ms, started_at, finished_at,
                prompt_tokens_per_second, generation_tokens_per_second, peak_memory_mb, status, error, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                model_run.run_id,
                model_run.observer_run_id,
                model_run.intelligence_run_id,
                model_run.provider,
                model_run.model,
                model_run.model_artifact_hash,
                model_run.quantization,
                canonical_json(model_run.inference_parameters),
                model_run.prompt_version,
                model_run.context_size,
                model_run.input_tokens,
                model_run.output_tokens,
                model_run.model_load_ms,
                model_run.prompt_eval_ms,
                model_run.generation_ms,
                model_run.total_ms,
                model_run.started_at.isoformat() if model_run.started_at else None,
                model_run.finished_at.isoformat() if model_run.finished_at else None,
                model_run.prompt_tokens_per_second,
                model_run.generation_tokens_per_second,
                model_run.peak_memory_mb,
                model_run.status,
                model_run.error,
                model_run.created_at.isoformat(),
            ),
        )
        self.connection.commit()

    def save_intelligence_run(self, run: IntelligenceRun) -> None:
        self.connection.execute(
            """
            INSERT INTO intelligence_runs (
                run_id, operation_id, operation_version, deterministic, intelligence_context_id,
                effective_configuration_json, started_at, finished_at, duration_ms, status,
                failure_category, candidates_count, promoted_count, rejected_count, model_runs_count, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.run_id,
                run.operation_id,
                run.operation_version,
                1 if run.deterministic else 0,
                run.intelligence_context_id,
                canonical_json(run.effective_configuration),
                run.started_at.isoformat(),
                run.finished_at.isoformat() if run.finished_at else None,
                run.duration_ms,
                run.status,
                run.failure_category,
                run.candidates_count,
                run.promoted_count,
                run.rejected_count,
                run.model_runs_count,
                run.error,
            ),
        )
        self.connection.commit()

    def update_intelligence_run(self, run: IntelligenceRun) -> None:
        self.connection.execute(
            """
            UPDATE intelligence_runs
            SET finished_at = ?, duration_ms = ?, status = ?, failure_category = ?,
                candidates_count = ?, promoted_count = ?, rejected_count = ?,
                model_runs_count = ?, error = ?
            WHERE run_id = ?
            """,
            (
                run.finished_at.isoformat() if run.finished_at else None,
                run.duration_ms,
                run.status,
                run.failure_category,
                run.candidates_count,
                run.promoted_count,
                run.rejected_count,
                run.model_runs_count,
                run.error,
                run.run_id,
            ),
        )
        self.connection.commit()

    def save_intelligence_candidate_rejection(
        self,
        intelligence_run_id: str,
        candidate_index: int,
        failure_category: str,
        detail: str,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO intelligence_candidate_rejections (
                intelligence_run_id, candidate_index, failure_category, detail
            ) VALUES (?, ?, ?, ?)
            """,
            (intelligence_run_id, candidate_index, failure_category, detail),
        )
        self.connection.commit()

    def save_finding(self, observer_run_id: str, finding: Finding) -> None:
        with self.connection:
            self._insert_finding(observer_run_id, finding)

    def _insert_finding(self, observer_run_id: str, finding: Finding) -> None:
        if finding.observer_run_id != observer_run_id:
            raise ValueError("finding observer_run_id does not match target ObserverRun")
        self.connection.execute(
            """
            INSERT INTO findings (
                finding_id, observer_run_id, observer_id, observer_version, category, severity,
                title, observation, created_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                finding.finding_id,
                finding.observer_run_id,
                finding.observer_id,
                finding.observer_version,
                finding.category,
                finding.severity,
                finding.title,
                finding.observation,
                finding.created_at.isoformat(),
                json.dumps(finding.metadata, sort_keys=True),
            ),
        )
        for subject in finding.subjects:
            self.connection.execute(
                """
                INSERT INTO finding_subjects (finding_id, entity_type, entity_id)
                VALUES (?, ?, ?)
                """,
                (finding.finding_id, subject.entity_type, subject.entity_id),
            )
        for evidence in finding.evidence:
            self.connection.execute(
                """
                INSERT INTO evidence (finding_id, dataset, snapshot_id, ref)
                VALUES (?, ?, ?, ?)
                """,
                (finding.finding_id, evidence.dataset, evidence.snapshot_id, evidence.ref),
            )

    # --- observation context manifests (Contract 002.2 / 002.8 / 002.9) -------------------------

    def ensure_snapshot_consistency(self, manifest: ObservationContextManifest) -> None:
        """Read-only fail-fast check; raises if recording this manifest would be inconsistent."""
        self._check_manifest(manifest)

    def save_observation_context(self, manifest: ObservationContextManifest) -> None:
        """Idempotently record a manifest. Conflicting membership is never silently ignored."""
        with self._atomic():
            self._insert_observation_context(manifest)

    def get_observation_context(self, context_id: str) -> ObservationContextManifest | UnknownObservationContext:
        """Reconstruct the recorded dataset reference set and verify it against ``context_id``.

        A missing manifest (for example a legacy ObserverRun) is reported explicitly as
        ``UnknownObservationContext``; nothing is guessed or backfilled.
        """
        recorded = self.connection.execute(
            "SELECT 1 FROM observation_contexts WHERE context_id = ?", (context_id,)
        ).fetchone()
        if recorded is None:
            orphaned = self.connection.execute(
                "SELECT 1 FROM observation_context_datasets WHERE context_id = ? LIMIT 1", (context_id,)
            ).fetchone()
            if orphaned is not None:
                # Membership without its context row is corruption, not a legacy run.
                raise ObservationContextIntegrityError(
                    f"membership rows exist for {context_id} but its context record is missing"
                )
            return UnknownObservationContext(context_id)
        try:
            manifest = ObservationContextManifest(references=self._recorded_references(context_id))
        except ValueError:
            raise ObservationContextIntegrityError(
                f"recorded manifest for {context_id} is not a valid dataset reference set"
            ) from None
        if manifest.context_id != context_id:
            raise ObservationContextIntegrityError(
                f"recorded manifest for {context_id} hashes to {manifest.context_id}"
            )
        return manifest

    def get_observation_context_for_run(self, run_id: str) -> ObservationContextManifest | UnknownObservationContext:
        row = self.connection.execute("SELECT context_id FROM observer_runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise LookupError(f"unknown ObserverRun: {run_id}")
        return self.get_observation_context(row["context_id"])

    def record_observer_execution(
        self,
        run: ObserverRun,
        manifest: ObservationContextManifest,
        findings: Sequence[Finding] = (),
    ) -> None:
        """Record manifest, ObserverRun and its Findings in one transaction (all or nothing)."""
        if run.context_id != manifest.context_id:
            raise ObservationContextIntegrityError("ObserverRun.context_id does not match the manifest")
        with self._atomic():
            self._insert_observation_context(manifest)
            self._insert_observer_run(run)
            for finding in findings:
                self._insert_finding(run.run_id, finding)

    def _recorded_references(self, context_id: str) -> tuple[DatasetReference, ...]:
        rows = self.connection.execute(
            """
            SELECT dataset, dataset_version, snapshot_id, content_hash
            FROM observation_context_datasets
            WHERE context_id = ?
            ORDER BY dataset
            """,
            (context_id,),
        ).fetchall()
        return tuple(DatasetReference(**dict(row)) for row in rows)

    def _check_manifest(self, manifest: ObservationContextManifest) -> bool:
        """Return True if this exact manifest is already recorded; raise on any inconsistency."""
        context_id = manifest.context_id
        exists = self.connection.execute(
            "SELECT 1 FROM observation_contexts WHERE context_id = ?", (context_id,)
        ).fetchone()
        if exists is not None:
            try:
                recorded = set(self._recorded_references(context_id))
            except ValueError:
                raise ObservationContextIntegrityError(f"recorded manifest for {context_id} is unreadable") from None
            if recorded != set(manifest.references):
                raise ObservationContextIntegrityError(
                    f"recorded membership for {context_id} differs from the supplied manifest"
                )
            return True
        for reference in manifest.references:
            for row in self.connection.execute(
                """
                SELECT DISTINCT dataset, dataset_version, content_hash
                FROM observation_context_datasets
                WHERE snapshot_id = ?
                """,
                (reference.snapshot_id,),
            ):
                recorded_identity = (row["dataset"], row["dataset_version"], row["content_hash"])
                if recorded_identity != (reference.dataset, reference.dataset_version, reference.content_hash):
                    raise SnapshotIntegrityError(
                        f"snapshot_id {reference.snapshot_id!r} is already recorded as "
                        f"{row['dataset']} v{row['dataset_version']} {row['content_hash']}, which conflicts with "
                        f"{reference.dataset} v{reference.dataset_version} {reference.content_hash}"
                    )
        return False

    def _insert_observation_context(self, manifest: ObservationContextManifest) -> None:
        if self._check_manifest(manifest):
            return  # identical manifest already recorded: idempotent
        self.connection.execute(
            "INSERT INTO observation_contexts (context_id, created_at) VALUES (?, ?)",
            (manifest.context_id, datetime.now(timezone.utc).isoformat()),
        )
        for reference in manifest.references:
            self.connection.execute(
                """
                INSERT INTO observation_context_datasets (context_id, dataset, dataset_version, snapshot_id, content_hash)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    manifest.context_id,
                    reference.dataset,
                    reference.dataset_version,
                    reference.snapshot_id,
                    reference.content_hash,
                ),
            )

    def list_findings(self) -> list[Finding]:
        rows = self.connection.execute("SELECT * FROM findings ORDER BY created_at").fetchall()
        findings: list[Finding] = []
        for row in rows:
            evidence_rows = self.connection.execute(
                "SELECT dataset, snapshot_id, ref FROM evidence WHERE finding_id = ? ORDER BY evidence_id",
                (row["finding_id"],),
            ).fetchall()
            subject_rows = self.connection.execute(
                "SELECT entity_type, entity_id FROM finding_subjects WHERE finding_id = ? ORDER BY subject_id",
                (row["finding_id"],),
            ).fetchall()
            findings.append(
                Finding(
                    finding_id=row["finding_id"],
                    observer_run_id=row["observer_run_id"],
                    observer_id=row["observer_id"],
                    observer_version=row["observer_version"],
                    category=row["category"],
                    subjects=[EntityReference(**dict(subject_row)) for subject_row in subject_rows],
                    severity=row["severity"],
                    title=row["title"],
                    observation=row["observation"],
                    created_at=row["created_at"],
                    metadata=json.loads(row["metadata_json"]),
                    evidence=[EvidenceReference(**dict(evidence_row)) for evidence_row in evidence_rows],
                )
            )
        return findings

    def get_findings_by_ids(self, finding_ids: list[str] | tuple[str, ...]) -> dict[str, Finding]:
        if not finding_ids:
            return {}
        placeholders = ",".join("?" for _ in finding_ids)
        rows = self.connection.execute(
            f"SELECT finding_id FROM findings WHERE finding_id IN ({placeholders})",
            tuple(finding_ids),
        ).fetchall()
        found_ids = {row["finding_id"] for row in rows}
        return {finding.finding_id: finding for finding in self.list_findings() if finding.finding_id in found_ids}

    def save_intelligence_context(self, context: IntelligenceContext) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT OR IGNORE INTO intelligence_contexts (intelligence_context_id, created_at)
                VALUES (?, ?)
                """,
                (context.intelligence_context_id, context.created_at.isoformat()),
            )
            for finding_id in context.finding_ids:
                self.connection.execute(
                    """
                    INSERT OR IGNORE INTO intelligence_context_findings (intelligence_context_id, finding_id)
                    VALUES (?, ?)
                    """,
                    (context.intelligence_context_id, finding_id),
                )

    def get_intelligence_context_finding_ids(self, intelligence_context_id: str) -> list[str]:
        rows = self.connection.execute(
            """
            SELECT finding_id
            FROM intelligence_context_findings
            WHERE intelligence_context_id = ?
            ORDER BY finding_id
            """,
            (intelligence_context_id,),
        ).fetchall()
        return [row["finding_id"] for row in rows]

    def save_insight(self, insight: Insight) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO insights (
                    insight_id, intelligence_context_id, intelligence_run_id, category, significance,
                    title, synthesis, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    insight.insight_id,
                    insight.intelligence_context_id,
                    insight.intelligence_run_id,
                    insight.category,
                    insight.significance,
                    insight.title,
                    insight.synthesis,
                    canonical_json(insight.metadata),
                    insight.created_at.isoformat(),
                ),
            )
            for subject in insight.subjects:
                self.connection.execute(
                    """
                    INSERT INTO insight_subjects (insight_id, entity_type, entity_id)
                    VALUES (?, ?, ?)
                    """,
                    (insight.insight_id, subject.entity_type, subject.entity_id),
                )
            for finding_id in insight.supporting_finding_ids:
                self.connection.execute(
                    """
                    INSERT INTO insight_findings (insight_id, finding_id)
                    VALUES (?, ?)
                    """,
                    (insight.insight_id, finding_id),
                )
