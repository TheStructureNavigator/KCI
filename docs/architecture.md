# KCI Architecture

KCI is a separate bounded context above KCC.

```text
Source Systems -> KCC -> Datasets -> KCI -> Findings -> Insights -> KC
```

KCC remains the knowledge layer: facts, canonical semantics, and controlled projections. KCI is the intelligence layer: Observers, FindingCandidates, validation, Findings, EvidenceReferences, ObserverRuns, ModelRuns, and later Insights.

The prototype is offline-first and currently uses local JSON fixtures plus SQLite. Transport is intentionally separate from the intelligence contracts so future filesystem, REST, network share, or broker transports do not change the Dataset or Finding contracts.

## Architecture Contracts

Formal architecture contracts live in [contracts/README.md](contracts/README.md).

Current approved contract:

- [KCI Contract 001 — Knowledge / Intelligence Boundary](contracts/KCI-CONTRACT-001-KNOWLEDGE-INTELLIGENCE-BOUNDARY.md): APPROVED
- [KCI Contract 002 — KCC Intelligence Dataset](contracts/KCI-CONTRACT-002-KCC-INTELLIGENCE-DATASET.md): APPROVED
- [KCI Contract 003 — Observer Execution](contracts/KCI-CONTRACT-003-OBSERVER-EXECUTION.md): APPROVED
- [KCI Contract 004 — Finding](contracts/KCI-CONTRACT-004-FINDING.md): APPROVED
- [KCI Contract 005 — Intelligence Context](contracts/KCI-CONTRACT-005-INTELLIGENCE-CONTEXT.md): APPROVED
- [KCI Contract 006 — Insight](contracts/KCI-CONTRACT-006-INSIGHT.md): APPROVED
- [KCI Contract 007 — Intelligence Execution](contracts/KCI-CONTRACT-007-INTELLIGENCE-EXECUTION.md): APPROVED
- [KCI Contract 008 — Meta-Observer / Uatu](contracts/KCI-CONTRACT-008-META-OBSERVER-UATU.md): APPROVED

Approved operation specifications live in [operations/README.md](operations/README.md).
Concrete model provider specifications live in [models/README.md](models/README.md).

Contract 001 defines the stable boundary between KCC as the knowledge layer and KCI as the intelligence layer.
Contract 002 defines Dataset, Snapshot, EvidenceRecord, and ObservationContext invariants at the KCC/KCI input boundary.
Contract 003 defines Observer identity, effective configuration, ObserverRun provenance, FindingCandidate promotion, ModelRun linkage, and the runtime execution boundary.
Contract 004 defines Finding identity, subjects, claim fields, severity, evidence requirements, and time semantics.
Contract 005 defines immutable reference-only contexts over trusted Findings for future higher-level intelligence operations.
Contract 006 defines InsightCandidate, trusted Insight artifacts, supporting Finding references, significance, and reference-only Insight persistence.
Contract 007 defines IntelligenceOperation, IntelligenceRun, per-candidate Insight promotion, rejection telemetry, and ModelRun linkage to intelligence execution.
Contract 008 defines Uatu as the meta-observer / higher-level intelligence role realized through versioned IntelligenceOperations over exact IntelligenceContexts.

UATU-OP-001 defines the Cross-Finding Pattern Synthesis specification and synthetic benchmark for the future `uatu.cross_finding_pattern_synthesis` operation. It does not implement model execution or analytical synthesis.

## Approved Foundation

KCI v0.1 Foundation: APPROVED

Verified baseline:

- 11 tests passed
- deterministic walking skeleton executed successfully
- Finding persisted with evidence provenance
- Observer telemetry active from run #1

The implemented walking skeleton is:

```text
DatasetEnvelope
    -> Observer.observe()
    -> FindingCandidate
    -> validate_candidates()
    -> Finding
    -> SQLite repository
```

Every observer execution produces an ObserverRun with timing, status, counts, Dataset/Snapshot identifiers, and error information when applicable.

The first Observer is ProductionObserver. It contains one deterministic rule: unexplained downtime greater than or equal to a configurable threshold produces a Finding with EvidenceReferences pointing to the source event refs in the supplied Dataset.

## Future Signals

Signals are expected to sit between facts and Observers:

```text
Facts -> Signals -> Observers -> Findings
```

A Signal may eventually wake or prioritize an Observer, but Signals are not implemented in KCI v0.1.
