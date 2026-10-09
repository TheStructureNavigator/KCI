from __future__ import annotations

import json
from pathlib import Path

from kci.contracts import DatasetEnvelope, ObservationContext


ROOT = Path(__file__).resolve().parents[1]


def load_fixture(name: str) -> DatasetEnvelope:
    path = ROOT / "datasets" / "synthetic" / name
    return DatasetEnvelope.model_validate(json.loads(path.read_text(encoding="utf-8")))


def load_context(name: str) -> ObservationContext:
    return ObservationContext(datasets=(load_fixture(name),))
