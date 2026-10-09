# KCI Contract 001 — Knowledge / Intelligence Boundary

Status: APPROVED

## Context

KCI - Knowledge Center Intelligence - is a separate bounded context above KCC - Knowledge Center Core.

KCC is the organizational knowledge layer.

KCI is the intelligence layer.

The fundamental distinction is:

```text
KCC answers:
    "What does the organization know?"

KCI answers:
    "What in that knowledge is worth attention?"
```

The architecture must preserve this boundary as KCI grows.

## Core Model

Conceptually, knowledge and intelligence flow through the system as follows:

```text
Source Systems / Applications
            ↓
           KCC
            ↓
    Facts / Datasets
            ↓
           KCI
            ↓
        Findings
            ↓
         Insights
            ↓
      Publication / Human
```

Later stages such as Insights and Publication may not yet exist in KCI v0.1.

## Ownership

Applications and source systems own their operational data.

KCC owns canonical organizational semantics and controlled projections of knowledge exposed to KCI.

KCI owns intelligence derived from those projections.

The concise ownership rule is:

```text
Application owns data
        ↓
KCC understands/projects knowledge
        ↓
KCI derives intelligence
```

KCC may access application databases through controlled read-only providers or adapters. This does not transfer ownership of application data to KCC.

If KCC must modify an application in the future, that should occur through an explicit application command/API rather than direct database mutation.

## KCC Responsibilities

KCC is responsible for concepts such as:

- canonical facts
- domain semantics
- entity identity
- relationships
- history
- domain-level aggregations/statistics
- controlled projections
- scope/data minimization
- dataset/version semantics

KCC should expose purpose-specific intelligence Datasets rather than forcing KCI to reconstruct source-system semantics.

## KCI Responsibilities

KCI is responsible for concepts such as:

- Observer execution
- detection
- FindingCandidates
- validation
- Findings
- evidence provenance
- run history
- ModelRun history
- later synthesis into Insights
- later review/publication workflow
- later feedback/evaluation

KCI must not become another source of truth for organizational facts.

## Fundamental Invariant

```text
KCI DOES NOT RECONSTRUCT THE KCC DOMAIN MODEL.
```

KCI may retain:

- Dataset identifiers
- Snapshot identifiers
- entity references
- EvidenceReferences
- technical caches needed for execution
- derived intelligence artifacts

KCI must not recreate canonical Machine, Employee, Project, Organization, or similar domain ownership merely for intelligence processing.

## Data Direction

KCC provides facts and context to KCI:

```text
KCC
  ↓
Facts / Context
  ↓
KCI
```

KCI provides Findings and later Insights to KC or other consumers:

```text
KCI
  ↓
Findings / Insights
  ↓
KC / consumers
```

Interpretation produced by KCI does not mutate KCC facts.

## Evidence

The long-term provenance chain is:

```text
Insight
    ↓
Finding
    ↓
EvidenceReference
    ↓
KCC Dataset / Snapshot / Fact
```

For KCI v0.1 the implemented portion is:

```text
Finding
    ↓
EvidenceReference
    ↓
Dataset / Snapshot / ref
```

LLM output is not evidence.

Observer text is not evidence.

Evidence must ultimately refer back to supplied organizational facts or data.

A factual Finding without valid evidence must not become an accepted or persisted Finding through the normal KCI runtime pipeline.

## Independence

KC/KCC must remain operational if KCI is unavailable.

KCI is an optional intelligence capability. Failure of an Observer, local model, KCI worker, or the entire KCI subsystem must not constitute failure of the Knowledge Center.

Informally:

```text
Awaria Uatu nie jest awarią Knowledge Center.
```

## Technology Independence

Contract 001 does not bind the architecture to:

- SQLite
- PostgreSQL
- filesystem transport
- network share
- REST
- message broker
- llama.cpp
- GGUF
- any specific model
- any specific operating system
- any specific Observer

These are implementation and deployment choices. The architecture contract is above them.

## Observers

An Observer follows this conceptual shape:

```text
Data
  ↓
Observe
  ↓
Finding
```

An Agent follows a different conceptual shape:

```text
Goal
  ↓
Investigation
  ↓
Actions / Requests
  ↓
Result
```

KCI v0.1 implements Observer foundations only.

Agents are outside the current scope.

## Current Implementation Evidence

KCI v0.1 demonstrates this contract through:

- generic DatasetEnvelope
- ProductionObserver isolated from KCI Core
- FindingCandidate before trusted Finding
- central validation
- evidence provenance
- SQLite KCI-owned intelligence persistence
- ObserverRun telemetry
- ModelProvider abstraction
- deterministic execution without a model
- no Internet dependency

This section demonstrates conformance only; it does not make the implementation choices part of Contract 001.
