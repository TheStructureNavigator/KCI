# KCI Contract 003 — Observer Execution

Status: APPROVED

## Purpose

Contract 003 defines how an Observer execution is identified, configured, executed, validated, measured, persisted, and reconstructed.

Contract 002 defines what knowledge was observed through DatasetEnvelope, immutable Snapshots, EvidenceRecords, and ObservationContext.

Contract 003 defines how that observation was executed.

The core execution flow is:

```text
ObservationContext
    ↓
KCI Runtime
    ↓
Observer
    ↓
FindingCandidate[]
    ↓
Runtime validation
    ↓
Finding
```

An optional model-assisted path may exist later:

```text
Observer
    ↓
ModelProvider
    ↓
ModelRun
    ↓
Observer logic
    ↓
FindingCandidate
```

A model must never have a direct path to Finding.

## 003.1 — Observer Identity and Version

Each Observer has a stable `observer_id` and `observer_version`.

`observer_id` identifies the semantic analytical purpose.

`observer_version` identifies the version of analytical behavior.

Configuration is not Observer version.

Prompt, rule, or algorithm changes that may intentionally change analytical results for the same ObservationContext and effective configuration require a new `observer_version`.

Using an LLM does not make an Observer an Agent. Observer remains conceptually:

```text
ObservationContext -> FindingCandidate[]
```

Agents are not implemented by this contract.

## 003.2 — Effective Observer Configuration

Observer execution uses an explicit effective configuration.

The effective configuration is the fully resolved analytical configuration actually used by the run. Defaults are materialized before execution and persisted with ObserverRun so future default changes do not change the meaning of historical runs.

Observer configuration contains analytical parameters such as thresholds, minimum sample size, or sensitivity.

Observer analytical configuration must not contain infrastructure values such as SQLite paths, network paths, log levels, worker identity, transport configuration, or secrets.

Canonical effective configuration JSON stored with ObserverRun is sufficient for this checkpoint. No `configuration_id` is introduced.

## 003.3 — ObserverRun Identity and Provenance

ObserverRun represents one execution attempt.

Each ObserverRun has a unique `run_id`.

`run_id` is not deterministic and must not be a hash of Observer, ObservationContext, and configuration. Two executions with identical analytical inputs are still different ObserverRuns.

ObserverRun provenance records at least:

- `observer_id`
- `observer_version`
- `context_id`
- effective configuration
- execution outcome
- timing and run telemetry

The runtime distinguishes:

- requirements not satisfied / Observer not started
- Observer started but execution failed
- Observer completed successfully

A successful ObserverRun may produce zero Findings. Zero Findings is not an execution failure.

Telemetry does not define run identity.

## 003.4 — FindingCandidate Promotion

Observer implementations return FindingCandidate objects.

Observer implementations must not directly create trusted Findings.

Runtime owns promotion:

```text
FindingCandidate -> validation -> Finding
```

Runtime validates candidate structure, EvidenceReferences, evidence membership in the exact ObservationContext used by the ObserverRun, and required provenance relationships.

Runtime may attach system provenance such as `finding_id`, `observer_run_id`, and `created_at`.

Runtime must not reinterpret, repair, or invent analytical content.

Invalid Candidates are rejected and recorded as validation failures.

A validated Finding is structurally valid, provenance-valid, and evidence-valid. It is not a claim that the analytical interpretation is objective ground truth.

Each trusted Finding produced by an Observer belongs to exactly one ObserverRun.

Current partial-success behavior: valid Candidates are promoted, invalid Candidates are rejected, ObserverRun status remains `succeeded`, and validation failure telemetry records rejected Candidates.

Finding lifecycle, review, supersession, deduplication, and correlation are deferred.

## 003.5 — ModelRun / Model-Assisted Observation

ObserverRun and ModelRun are different concepts.

ObserverRun is the full analytical execution.

ModelRun is one model invocation performed as part of an ObserverRun.

Relationship:

```text
ObserverRun -> 0..n ModelRuns
```

A deterministic Observer may have zero ModelRuns.

A model-assisted Observer may have one or more ModelRuns.

ModelRun references exactly one parent ObserverRun.

Unavailable model telemetry must remain null or absent. KCI must not fabricate token counts, timings, throughput, or memory metrics.

Raw model output is not Evidence and is not a Finding. It must pass through Observer logic and standard FindingCandidate validation.

This contract does not implement real llama.cpp inference, a model registry, model routing, fallback behavior, or persistence of full model input/output.

## 003.6 — Determinism and Reproducibility

Observer version declares whether analytical behavior is deterministic.

For a deterministic Observer:

```text
same observer_id
+ same observer_version
+ same effective configuration
+ same ObservationContext
= semantically equivalent analytical output
```

Differences in `run_id`, timestamps, duration, and telemetry do not violate determinism.

All analytical inputs affecting deterministic behavior must come from the versioned implementation, ObservationContext, and effective configuration.

Deterministic Observers must not depend on hidden mutable state, implicit system time, undeclared randomness, or undeclared external data.

Contract 003 does not introduce execution fingerprints or runtime environment fingerprints.

## 003.7 — Observer Execution Boundary

KCI Runtime owns the lifecycle of one ObserverRun.

Before Observer execution, Runtime:

1. resolves effective Observer configuration,
2. validates Contract 002 requirements,
3. validates required Dataset compatibility and integrity,
4. creates ObserverRun provenance.

If requirements are not satisfied, `Observer.observe()` is not called and ObserverRun records a requirements-failure outcome.

When requirements are satisfied, Runtime invokes the Observer through its public contract.

Observer owns analytical interpretation.

Runtime owns execution integrity, FindingCandidate validation, Finding promotion, persistence coordination, and ObserverRun finalization.

Observer implementations must not own persistence, ObserverRun lifecycle, Finding promotion, Dataset transport, scheduler behavior, CLI behavior, direct KCC fetching, or concrete SQLite access.

Runtime must not contain ProductionObserver-specific analytical logic.

Concrete model providers belong at the composition boundary. Simple constructor injection is sufficient when model-assisted Observers are introduced.

## Explicit Deferred Concerns

- Candidate partial-success policy beyond current telemetry
- Finding lifecycle/review
- Finding deduplication/correlation
- Uatu
- Agents
- Signals
- scheduling/triggers
- model routing/fallback framework
- model registry
- execution fingerprint
- runtime environment fingerprint
- real model inference
