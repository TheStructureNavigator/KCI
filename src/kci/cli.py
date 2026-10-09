from __future__ import annotations

import argparse
import json
from pathlib import Path

from kci.contracts import DatasetEnvelope, ObservationContext
from kci.observers.production import ProductionObserver
from kci.persistence import KciRepository, connect, initialize_database
from kci.runtime import run_observer


def load_dataset(path: Path) -> DatasetEnvelope:
    with path.open("r", encoding="utf-8") as handle:
        return DatasetEnvelope.model_validate(json.load(handle))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the KCI local walking skeleton.")
    parser.add_argument("--dataset", type=Path, required=True, help="Path to a synthetic dataset JSON file.")
    parser.add_argument("--db", type=Path, default=Path("kci.sqlite3"), help="SQLite database path.")
    parser.add_argument("--threshold-minutes", type=int, default=30, help="Unexplained downtime threshold.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    dataset = load_dataset(args.dataset)
    context = ObservationContext(datasets=(dataset,))

    connection = connect(args.db)
    initialize_database(connection)
    repository = KciRepository(connection)

    observer = ProductionObserver()
    result = run_observer(
        observer,
        context,
        repository,
        requested_configuration={"threshold_minutes": args.threshold_minutes},
    )

    print(f"observer: {result.run.observer_id}@{result.run.observer_version}")
    print(f"snapshot: {result.run.dataset}/{result.run.snapshot_id}")
    print(f"context_id: {result.run.context_id}")
    print(f"effective_configuration: {result.run.effective_configuration}")
    print(f"status: {result.run.status}")
    print(f"duration_ms: {result.run.duration_ms:.2f}")
    print(f"findings_count: {len(result.findings)}")
    for finding in result.findings:
        refs = ", ".join(evidence.ref for evidence in finding.evidence)
        print(f"- {finding.title} [{refs}]")
    for failure in result.validation_failures:
        print(f"validation_failure[{failure.candidate_index}]: {failure.reason}")

    return 0 if result.run.status == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
