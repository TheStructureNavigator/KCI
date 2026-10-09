from __future__ import annotations

from kci.contracts import DatasetEnvelope, ObservationContext
from tests.conftest import load_fixture


def test_observation_context_identity_is_deterministic() -> None:
    context_a = ObservationContext(datasets=(load_fixture("normal_shift.json"),))
    context_b = ObservationContext(datasets=(load_fixture("normal_shift.json"),))

    assert context_a.context_id == context_b.context_id


def test_snapshot_order_does_not_affect_context_id() -> None:
    normal = load_fixture("normal_shift.json")
    mixed = load_fixture("mixed_problem.json")
    mixed_payload = mixed.model_dump(mode="json")
    mixed_payload["dataset"] = "synthetic.production.shift.secondary"
    mixed_payload["content_hash"] = DatasetEnvelope.model_validate(mixed_payload).computed_content_hash()
    secondary = DatasetEnvelope.model_validate(mixed_payload)

    context_a = ObservationContext(datasets=(normal, secondary))
    context_b = ObservationContext(datasets=(secondary, normal))

    assert context_a.context_id == context_b.context_id


def test_changing_snapshot_changes_context_id() -> None:
    normal = load_fixture("normal_shift.json")
    payload = normal.model_dump(mode="json")
    payload["snapshot_id"] = "normal-shift-002"
    payload["content_hash"] = DatasetEnvelope.model_validate(payload).computed_content_hash()
    changed = DatasetEnvelope.model_validate(payload)

    assert ObservationContext(datasets=(normal,)).context_id != ObservationContext(datasets=(changed,)).context_id
