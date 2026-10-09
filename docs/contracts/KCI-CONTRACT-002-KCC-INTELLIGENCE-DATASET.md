# KCI Contract 002 — KCC Intelligence Dataset

Status: APPROVED

## Purpose

This contract defines the input boundary between KCC and KCI. It formalizes what a KCC Intelligence Dataset is, how Dataset Snapshots are identified, how EvidenceRecords are addressed, and how an ObservationContext is assembled for Observer execution.

Contract 002 is subordinate to and consistent with [KCI Contract 001 — Knowledge / Intelligence Boundary](KCI-CONTRACT-001-KNOWLEDGE-INTELLIGENCE-BOUNDARY.md).

## Terminology

- Dataset: a logical, named, versioned KCC knowledge projection published for intelligence use.
- Snapshot: one immutable materialization of one Dataset.
- ObservationContext: the exact immutable set of Dataset Snapshots supplied to one Observer execution.
- EvidenceRecord: an explicitly designated addressable record in a Dataset Snapshot that may support factual Findings.
- EvidenceReference: the canonical KCI reference to evidence: `(dataset, snapshot_id, ref)`.
- FindingCandidate: untrusted Observer/model output before runtime validation.
- Finding: validated intelligence artifact backed by valid EvidenceReferences.
- ObserverRun: telemetry and provenance record for one Observer execution attempt.

## Approved Invariants

- KCI DOES NOT RECONSTRUCT THE KCC DOMAIN MODEL.
- ObservationContext is an execution/input container only.
- Dataset contract ownership belongs to KCC.
- KCI consumes KCC Dataset contracts; it does not infer source-system semantics.
- EvidenceRecords must be explicit in the Dataset contract/model.
- Arbitrary JSON dictionaries containing `ref` are not evidence.
- LLM output is not evidence.
- Observer prose is not evidence.
- KCI stores intelligence/provenance, not a duplicate KCC knowledge warehouse.

## 002.1 — Observer Input Unit

The unit of input to an Observer is ObservationContext.

ObservationContext contains one or more DatasetEnvelope objects required for one Observer execution.

Observer declares required Datasets and compatible Dataset versions.

KCI Runtime checks requirements before Observer execution. If a required compatible Dataset is unavailable, the Observer must not start.

ObservationContext MUST NOT become a KCC domain model and MUST NOT introduce domain entities such as Machine, Employee, Department, Project, or Shift.

Optional Datasets are outside this checkpoint.

## 002.2 — Dataset and Snapshot Identity

Dataset is a logical, named, versioned contract/projection of knowledge published by KCC.

Examples:

- `production.downtime`
- `production.shift_summary`
- `projects.progress`
- `competence.coverage`

Snapshot is one concrete immutable materialization of one Dataset. Each Snapshot has a globally unique `snapshot_id`.

Existing Snapshot contents never change. Correction or regeneration creates a new Snapshot.

`generated_at` means when KCC created the Snapshot. The time represented by organizational reality is described separately by temporal metadata.

ObservationContext may contain Snapshots from multiple Datasets. This does not create one common Dataset Snapshot.

ObservationContext has its own `context_id` identifying the exact set of Snapshots supplied to an execution. ObserverRun must preserve enough information to reconstruct the ObservationContext used for the run.

## 002.3 — Evidence Addressing

A KCC Dataset may contain explicitly designated EvidenceRecords: addressable elements of knowledge that may support factual Findings.

Each EvidenceRecord has a `ref`. The semantics of `ref` are defined by the contract of that Dataset.

The canonical KCI evidence identity is:

```text
(dataset, snapshot_id, ref)
```

`ref` does not need to be globally unique outside its Dataset Snapshot.

An EvidenceRecord may represent a source-like event, a controlled aggregation, a statistic, or another KCC knowledge projection.

EvidenceReference and EntityReference are different concepts.

Before promoting FindingCandidate to trusted Finding, Runtime must verify that:

1. referenced Dataset exists in the ObservationContext,
2. `snapshot_id` is exactly the Snapshot used in that ObservationContext,
3. `ref` identifies an explicit EvidenceRecord in that Snapshot.

Invalid EvidenceReference prevents promotion to Finding.

## 002.4 — Dataset Versioning

There are two independent version levels:

- `schema_version`: version of the common DatasetEnvelope protocol.
- `dataset_version`: version of the contract of a specific named Dataset.

Each Dataset evolves independently.

`dataset_version` changes when an existing consumer cannot safely interpret the Dataset using previous contract semantics. Breaking changes include changed field meaning, changed field type, removal of required information, and incompatible structural changes.

Compatible additive information may be introduced without incrementing `dataset_version` when existing consumers can safely ignore it.

Consumers should tolerate unknown additional fields for a supported Dataset version.

Observers must declare which Dataset version or versions they can safely interpret. Runtime validates compatibility before Observer execution.

Dataset contract versions use simple monotonically increasing integer versions. SemVer is not required here.

Snapshot has no `snapshot_version`. Changing data creates a new `snapshot_id`. Changing an incompatible Dataset contract creates a new `dataset_version`.

The public JSON field remains `schema`.

## 002.5 — Knowledge Scope and Time

Each Dataset Snapshot describes the scope of knowledge it represents.

`scope` is supplied according to KCC Dataset semantics. KCI preserves scope for context and provenance, but MUST NOT reconstruct organizational domain models from scope.

Dataset scope and Finding subject are different concepts.

Temporal semantics distinguish:

- `period`: knowledge describing an interval of organizational reality.
- `as_of`: knowledge representing state at a specific moment.
- `generated_at`: time when the Snapshot was generated.

Do not require both `period` and `as_of` simultaneously.

Datasets in one ObservationContext do not need identical `period`, `as_of`, `generated_at`, or `scope`.

Freshness policy is outside this checkpoint.

## 002.6 — Dataset Ownership and Purpose

The contract of each named KCC Intelligence Dataset belongs to KCC.

KCC defines Dataset semantics, payload structure, field meanings, EvidenceRecords, scope semantics, temporal semantics, and projection generation rules.

KCI consumes published Dataset contracts. Observers depend on public KCC Dataset contracts, not application tables, databases, or application-specific APIs.

Dataset is a controlled knowledge projection. It is not synonymous with a database table and is not a technical database dump.

One Dataset may be produced by KCC from multiple source systems.

Datasets should be purpose-specific and data-minimized. Broad "everything" Datasets are not approved.

For KCI, the canonical evidence address remains `(dataset, snapshot_id, ref)`. Mapping an EvidenceRecord to source systems, tables, or rows remains a KCC responsibility.

Synthetic fixtures must not contain personal identifying information.

## 002.7 — ObservationContext Assembly and Consistency

ObservationContext represents the exact set of Dataset Snapshots provided to one execution.

Snapshots in one ObservationContext do not need identical `generated_at`, `period`, `as_of`, or `scope`.

ObservationContext is not a globally transactional Snapshot of the entire Knowledge Center.

Runtime is responsible for assembling a valid ObservationContext before the Observer executes.

Observer declares requirements but does not fetch Dataset files, select latest Snapshots, query KCC storage, or know filesystem/network/database transport.

Once assembled for execution, ObservationContext composition is immutable. A newer Snapshot appearing after execution begins must not alter the Context of the running Observer.

Input requirement failure must be semantically distinguishable from Observer execution failure.

Global freshness policy and generic latest-Snapshot selection are outside this checkpoint.

## 002.8 — Snapshot Ownership, Integrity and Retention

KCC owns Dataset Snapshots and their canonical history.

KCI is not an archive or second source of truth for KCC knowledge.

KCI stores Snapshot identifiers, EvidenceReferences, and provenance needed for intelligence artifacts and ObserverRuns.

Snapshot must carry a cryptographic `content_hash`.

`content_hash` is integrity metadata. It is not evidence.

KCI may use disposable technical Dataset caches, but such caches do not acquire KCC ownership or semantics.

Retention policy and Snapshot archiving are outside this checkpoint.

Historical EvidenceReference remains meaningful even if its Snapshot can no longer currently be resolved.

Reusing the same `snapshot_id` for changed Snapshot content is a contract violation. A `content_hash` mismatch is an integrity violation.

SHA-256 is the approved baseline hash algorithm for this checkpoint.

## 002.9 — ObservationContext Identity

ObservationContext has stable logical identity derived from the exact set of Dataset Snapshots it contains.

Creating a Context multiple times from the same set of Snapshots must produce the same logical `context_id`.

Snapshot order must not affect context identity.

Changing any Snapshot in the Context must produce a different `context_id`.

`context_id` identifies input knowledge, not Observer execution. Multiple ObserverRuns and multiple Observers may use the same `context_id`.

The following are not part of ObservationContext identity:

- `observer_id`
- `observer_version`
- Observer configuration
- model/provider
- execution result

Deterministic canonicalization and SHA-256 hashing are sufficient for this checkpoint.

## Explicit Non-Goals

This contract does not approve or implement Uatu, Agents, Signals, scheduling, REST, MCP, GUI/TUI, message brokers, PostgreSQL, Docker, Celery, APScheduler, Ollama, real llama.cpp execution, model routing, KCC network integration, network-share transport, Dataset registry services, schema registry services, Dataset discovery APIs, generic dependency graphs, freshness policy, retention policy, authorization, source-system lineage, generalized Entity models, or KCC domain objects inside KCI.

## Relationship to Contract 001

Contract 001 defines the knowledge/intelligence boundary.

Contract 002 defines the Dataset, Snapshot, EvidenceRecord, and ObservationContext mechanics that make that boundary executable.

Together they preserve the ownership chain:

```text
Application owns operational data
    ↓
KCC understands/projects knowledge
    ↓
KCI derives intelligence
```
