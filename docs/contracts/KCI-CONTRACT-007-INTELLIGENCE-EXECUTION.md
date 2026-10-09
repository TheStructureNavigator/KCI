# KCI Contract 007 — Intelligence Execution

Status: APPROVED

## Core Boundary

```text
IntelligenceOperation owns synthesis.
Runtime owns execution integrity.
```

Keep distinct:

- IntelligenceContext = input
- IntelligenceOperation = analytical behavior
- IntelligenceRun = execution occurrence
- ModelRun = one concrete model invocation
- InsightCandidate = proposed analytical output
- Insight = trusted promoted analytical artifact

## Flow

Observation level:

```text
ObservationContext -> ObserverRun -> Finding
```

Intelligence level:

```text
IntelligenceContext -> IntelligenceRun -> Insight
```

Full flow:

```text
KCC Dataset/Snapshot
    -> ObservationContext
    -> Observer
    -> ObserverRun
    -> FindingCandidate
    -> Finding
    -> IntelligenceContext
    -> IntelligenceOperation
    -> IntelligenceRun
    -> InsightCandidate
    -> Insight
```

Uatu is future and is not implemented by this contract.

## 007.1 — Intelligence Operation Identity and Version

Each IntelligenceOperation version has:

- `operation_id`
- `operation_version`
- `deterministic`

`operation_id` is the stable machine-readable semantic identity of the analytical operation.

`operation_version` identifies the version of analytical behavior.

`deterministic` declares whether this version satisfies the deterministic behavior contract.

Do not identify an operation by model name, provider, GGUF filename, machine, deployment environment, or Uatu.

If identical IntelligenceContext and effective configuration may intentionally produce different analytical decisions because the implementation changed, `operation_version` must change.

IntelligenceOperation is not a model, ModelProvider, Agent, Uatu, persistence, or Runtime.

IntelligenceOperation receives an already constructed exact IntelligenceContext. It must not select its own Findings, query for more Findings, expand context, replace Findings, or construct a new IntelligenceContext.

IntelligenceOperation returns InsightCandidates and does not create trusted Insights.

## 007.2 — Intelligence Operation Configuration

Every execution has explicit effective configuration.

Runtime resolves defaults and validates configuration before analytical execution begins.

Effective configuration represents analytical parameters of one execution. It is distinct from operation version, ModelRun inference parameters, and deployment configuration.

Do not place DB paths, network share paths, logging settings, GPU/device selection, executable paths, transport settings, infrastructure timeouts, credentials, API keys, tokens, or passwords in effective configuration.

Contract 007 does not introduce configuration IDs or registries.

## 007.3 — IntelligenceRun Identity and Provenance

IntelligenceRun represents one concrete execution attempt of one operation version on one exact IntelligenceContext with one immutable effective configuration.

It records:

- `run_id`
- `operation_id`
- `operation_version`
- `deterministic`
- `intelligence_context_id`
- `effective_configuration`
- status/outcome
- started/finished/duration
- candidate/promoted/rejected counts
- model run count
- failure category/detail when relevant

`run_id` is unique per execution attempt and is not deterministic or content-derived.

Re-running identical operation/context/config creates a new IntelligenceRun.

Run outcome distinguishes:

- preconditions not satisfied / operation not started
- execution started but failed
- execution succeeded

A successful IntelligenceRun may produce zero candidates and zero Insights.

Trusted Insights created by Contract 007 execution include `intelligence_run_id` and retain `intelligence_context_id`.

Standalone Contract 006 promotion may produce Insights without `intelligence_run_id`; Contract 007-created Insights always have a real IntelligenceRun.

## 007.4 — Intelligence Execution Boundary

Runtime lifecycle:

1. resolve effective configuration
2. validate exact persisted IntelligenceContext
3. establish IntelligenceRun provenance
4. invoke IntelligenceOperation
5. collect InsightCandidates
6. validate/promote candidates independently
7. persist trusted Insights
8. record rejection telemetry
9. finalize counts/timing/outcome

If preconditions fail, the operation is not invoked and the run outcome is distinguishable from execution failure.

If the operation throws after execution starts, the failed IntelligenceRun remains persisted.

Runtime does not rewrite synthesis, reinterpret claims, decide novelty, change significance, change subjects, repair support, or perform domain reasoning.

EvidenceResolver is not implemented.

## 007.5 — Candidate Acceptance and Run Outcome

Candidate validation outcome is distinct from execution outcome.

Valid successful cases include:

- zero candidates
- all candidates promoted
- some candidates rejected
- all candidates rejected

Invalid candidates do not automatically make IntelligenceRun failed.

Runtime records bounded rejection telemetry:

- `candidate_index`
- failure category
- detail/reason

No candidate ID or rejected-candidate trusted artifact is introduced. Full invalid Candidate payload is not persisted.

Runtime must not repair invalid candidates.

Runtime/persistence failure while promoting a valid candidate is an execution failure, not ordinary candidate rejection.

## 007.6 — Model-Assisted Intelligence Execution

ModelRun remains the single artifact for one concrete model invocation.

An analytical execution may have:

```text
ObserverRun -> 0..n ModelRuns
IntelligenceRun -> 0..n ModelRuns
```

A ModelRun belongs to exactly one analytical execution: ObserverRun or IntelligenceRun, never both.

Do not introduce IntelligenceModelRun, UatuModelRun, SynthesisModelRun, model router, generic fallback framework, or common ExecutionRun superclass/table.

Provider/model identity remain separate from operation identity.

Do not persist raw prompts, raw responses, chain-of-thought, or reasoning by default.

Raw model output is not Insight and is not automatically InsightCandidate.

ModelRun failure does not globally imply IntelligenceRun failure.

## 007.7 — Determinism and Reproducibility

Each IntelligenceOperation version declares `deterministic`.

For deterministic operations, identical operation ID/version, exact IntelligenceContext, and immutable effective configuration must produce semantically equivalent analytical output.

Different run IDs, insight IDs, timestamps, durations, and telemetry do not violate determinism.

Deterministic operations must not make analytical decisions using hidden mutable inputs such as implicit current time, undeclared randomness, arbitrary external APIs, mutable global state, or repository latest queries.

Model-assisted operations are not automatically deterministic merely because temperature is zero or a seed is fixed.

Contract 007 does not introduce execution fingerprints, environment hashes, or hardware fingerprints.

## Explicit Deferred Concerns

- Uatu
- MetaObserver
- production synthesis operations
- Finding selection algorithms
- SelectionRun
- EvidenceResolver
- unrestricted KCC queries
- Signals/triggers/scheduler
- recommendation semantics
- review lifecycle
- feedback/publication/supersession
- Investigation/Task/Action/Agents
- model router
- generic fallback framework
- common ExecutionRun abstraction
- raw model prompt/response persistence
- chain-of-thought persistence
- candidate domain identity
