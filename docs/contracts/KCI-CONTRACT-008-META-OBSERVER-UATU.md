# KCI Contract 008 — Meta-Observer / Uatu

Status: APPROVED

## Purpose

Contract 008 defines Uatu as the higher-level intelligence / meta-observer role in KCI.

Uatu synthesizes trusted Findings through the IntelligenceContext / IntelligenceOperation / IntelligenceRun / Insight pipeline established by Contracts 005-007.

"Meta-observer" is an architectural role.

It does not mean Uatu inherits from the Observer abstraction defined by Contract 003.

Core mnemonic:

```text
Observer -> notices
Uatu     -> synthesizes
Agent    -> pursues a goal
```

Fundamental invariant:

```text
KCI DOES NOT RECONSTRUCT THE KCC DOMAIN MODEL.
```

## 008.1 — Uatu Identity and Responsibility

Uatu is the KCI meta-observer / higher-level intelligence component responsible for interpretation and synthesis of trusted Findings.

Uatu acts on IntelligenceContext and produces InsightCandidates through versioned IntelligenceOperations.

Trusted Insights are created only through the Runtime trust boundary established by Contracts 006 and 007.

Uatu is not an Observer in the Contract 003 sense and does not primarily consume ObservationContext.

"Meta-observer" is an architectural role, not inheritance from Observer.

Uatu is not a single IntelligenceOperation.

Uatu is a component / architectural role realized by one or more versioned IntelligenceOperations with explicit analytical responsibilities.

Uatu is not:

- a model;
- ModelProvider;
- inference runtime.

A Uatu IntelligenceOperation may execute zero or more ModelRuns.

Uatu is not an Agent.

It does not own:

- goal-directed Investigation lifecycle;
- Actions;
- Tasks;
- system mutation.

Uatu does not directly publish or send intelligence to users.

Its canonical analytical output ends at:

```text
InsightCandidate
    -> Runtime validation/promotion
    -> Insight
```

Publication is a separate future concern.

Uatu does not maintain an alternate organization domain model.

Uatu's primary analytical material is trusted Findings contained in the exact IntelligenceContext.

Future controlled evidence inspection may be permitted only within the boundaries defined by Contracts 005-008.

Uatu must not perform arbitrary KCC querying or silently expand its analytical context.

Uatu may synthesize across:

- domains;
- Observers;
- periods;
- scopes.

However:

```text
co-presence in an IntelligenceContext does not itself establish a relationship.
```

Any relationship asserted by Uatu is a new analytical claim and must pass through the Insight trust pipeline.

## 008.2 — Uatu Analytical Input Boundary

The primary input to a Uatu IntelligenceOperation is the exact trusted IntelligenceContext passed to a specific IntelligenceRun.

Uatu may analyze canonical Finding content contained in that context, including:

- category;
- subjects;
- severity;
- title;
- observation;
- structured metadata;
- EvidenceReferences;
- Finding provenance.

Uatu may not:

- select additional Findings;
- search for additional Findings;
- fetch additional Findings outside the exact IntelligenceContext.

If additional Findings are required, a new IntelligenceContext must be constructed and a new execution performed.

Uatu operations must not have arbitrary access to:

- repository-wide Finding search;
- KCC query APIs;
- application/source databases.

Future controlled Evidence access is allowed only for canonical EvidenceReferences already belonging to Findings in the exact IntelligenceContext.

Evidence resolution must not expand or change IntelligenceContext identity.

Evidence resolution must be demand-driven and data-minimized.

Do not automatically materialize all evidence or dump entire datasets into a model.

A resolver, if implemented in the future, must resolve the exact canonical identity:

```text
(dataset, snapshot_id, ref)
```

There must be no fallback to:

- latest;
- similar;
- another snapshot;
- another evidence record.

Individual evidence resolution failure does not automatically imply global IntelligenceRun failure.

The versioned IntelligenceOperation determines whether the remaining permitted material is analytically sufficient.

A model used by a Uatu operation may never have broader data access than the operation itself.

Model input may contain only:

- material from the exact IntelligenceContext;
- explicitly permitted resolved evidence;
- versioned operation instructions/configuration.

Finding.metadata is legal analytical input but must not become a side-channel for embedding an entire KCC dataset or evidence payload.

Conceptual boundary:

```text
Exact IntelligenceContext
        ->
trusted Findings
        ->
optional constrained exact EvidenceReference resolution
        ->
Uatu
```

Never:

```text
Uatu
    ->
arbitrary KCC query
    ->
"give me more context"
```

## 008.3 — Uatu Operations and Analytical Responsibilities

Uatu is realized through one or more explicit versioned IntelligenceOperations.

Every Uatu IntelligenceOperation must have a concrete analytical responsibility.

Avoid generic operations equivalent to:

```text
uatu.general("find something interesting")
```

Contract 008 does not define a closed catalog of Uatu operations.

A single IntelligenceOperation may return:

```text
0..n InsightCandidates
```

Each InsightCandidate must represent one coherent atomic analytical claim according to Contract 006.

An operation analyzes the exact IntelligenceContext.

A specific Insight may be directly supported by any non-empty subset of Findings in that context.

Preserve the distinction:

```text
context Findings != supporting Findings
```

A Finding may be available to an operation without becoming support for a particular Insight.

Not using a Finding as support does not mean that Finding was absent from the IntelligenceContext.

A Uatu operation may identify relevant support among Findings already present in its exact context.

It may not search outside that context.

An IntelligenceOperation may execute:

```text
0..n ModelRuns
```

Model calls are execution details inside the IntelligenceRun.

They do not become:

- Agent steps;
- separate analytical operations;
- canonical reasoning artifacts.

Do not persist chain-of-thought as a canonical KCI artifact.

Every Uatu operation should be narrow and explicit enough to benchmark against representative IntelligenceContexts.

Benchmark the concrete analytical responsibility, not generic "Uatu intelligence".

A Uatu operation produces synthesis.

It does not produce:

- recommendations;
- plans;
- Tasks;
- Actions;
- publication.

A Uatu operation may be cross-domain or single-domain.

Uatu-ness does not require multiple domains.

Its defining property is synthesis of trusted Findings at the IntelligenceContext level.

## 008.4 — Analytical Restraint and Claim Discipline

Fundamental invariant:

```text
An Insight claim must not be stronger than its supporting analytical basis.
```

Uatu must not automatically convert:

- association into causality;
- co-occurrence into causality;
- temporal proximity into causality;
- cross-domain co-presence into causality.

Local scope must not be generalized beyond its analytical basis.

A limited observation period must not automatically become a durable trend.

Uatu must not invent missing facts to complete a narrative.

Interpretation is allowed.

Invented factual premises are not.

An Insight must not be merely:

- a paraphrase;
- a summary;
- a concatenation

of its supporting Findings.

It must add a new coherent analytical claim.

Returning:

```text
[]
```

is a valid and desirable analytical outcome when the available Findings do not sufficiently support a synthesis.

A successful IntelligenceRun with zero candidates is normal.

Contract 008 does not introduce:

- a global confidence score;
- a universal claim-strength ontology.

Method-specific metrics may exist only when a versioned IntelligenceOperation explicitly defines their semantics.

Model-reported confidence is not automatically Insight confidence.

Preserve:

```text
Insight.significance
    != confidence
    != evidence strength
    != causal strength
```

Benchmarks for Uatu operations must test analytical restraint, not only positive detection.

Representative benchmark categories should include:

- true positives;
- true negatives;
- overclaim traps;
- distractors;
- generalization traps;
- unsupported causality;
- irrelevant support;
- false positives.

A good Uatu is characterized both by valuable synthesis and by its ability not to invent relationships.

## 008.5 — Uatu Model Boundary and Structured Output

A model used inside Uatu is an untrusted analytical engine inside a versioned IntelligenceOperation.

A model does not directly produce a trusted Insight or other trusted canonical artifact.

Canonical conceptual pipeline:

```text
IntelligenceContext
    ->
Uatu IntelligenceOperation
    ->
bounded model input
    ->
ModelProvider
    ->
ModelRun
    ->
raw model output
    ->
operation parsing / analytical handling
    ->
InsightCandidate[]
    ->
Runtime validation
    ->
Insight
```

There are two distinct trust boundaries:

```text
raw model output
    ->
InsightCandidate
```

Owned by the versioned IntelligenceOperation.

```text
InsightCandidate
    ->
trusted Insight
```

Owned by Runtime.

Model-assisted operations should prefer bounded structured output over unrestricted free-form prose.

An operation-specific model-output schema may be stricter than generic InsightCandidate.

It does not replace Runtime validation.

The operation may perform technical:

- parsing;
- schema validation;
- explicit normalization.

It must not silently repair analytical errors such as:

- invented Finding IDs;
- unsupported analytical content;
- incorrect significance;
- causal overclaim;
- unsupported relationships.

Any analytical post-processing rule that changes behavior must be explicit and part of the versioned operation semantics.

Model input should expose stable Finding IDs so model output can reference its claimed support.

Runtime independently validates support membership and trust.

Category and significance semantics come from the versioned IntelligenceOperation.

Contract 008 does not introduce canonical:

- Prompt;
- PromptVersion;
- PromptRegistry.

Prompts/instructions that materially affect analytical behavior are part of the versioned operation implementation.

A behavior-affecting instruction/prompt change requires an operation_version change.

Model input preparation belongs to the versioned operation.

It must be:

- bounded;
- data-minimized;
- based only on permitted analytical material.

Model context-window capacity is not justification for sending all available information.

Raw model input, raw model output, and chain-of-thought are not canonical historical KCI artifacts and are not persisted by default.

Structured output must support zero candidates.

Even perfectly schema-shaped model JSON remains untrusted until:

- the operation constructs InsightCandidate;
- Runtime validates/promotes it.

## 008.6 — Uatu Provenance and Explainability

Uatu explainability means:

```text
canonical provenance + analytical support
```

It does not mean preservation of internal model reasoning or chain-of-thought.

Every trusted Uatu-produced Insight must be traceable through its provenance to:

- exact IntelligenceRun;
- exact IntelligenceContext;
- operation_id;
- operation_version;
- effective configuration;
- supporting Findings.

Supporting Findings are the direct analytical basis of an Insight.

Their EvidenceReferences provide the indirect provenance path back to KCC knowledge.

Preserve the distinction:

```text
IntelligenceContext
    =
all Findings available to the operation

supporting Findings
    =
Findings claimed to directly support a specific Insight
```

ModelRun is execution provenance.

ModelRun is not:

- Evidence;
- analytical support;
- proof of truth.

Model identity, provider identity, and inference parameters do not establish factual truth.

Raw model reasoning, chain-of-thought, and post-hoc model explanations are not canonical provenance.

Contract 008 does not introduce canonical artifacts such as:

- Explanation;
- ReasoningTrace;
- UatuThought.

A future user-facing "Why am I seeing this?" view should be a projection over the canonical provenance graph rather than stored chain-of-thought.

If controlled Evidence resolution is implemented later, resolution attempts/outcomes should be auditable at execution level without copying evidence payloads into KCI or creating another source of truth.

Uatu explainability should be able to answer:

- What Insight was produced?
- Which operation and version produced it?
- Which IntelligenceRun produced it?
- Which exact IntelligenceContext was used?
- Which effective configuration was used?
- Which Findings directly support it?
- Which EvidenceReferences anchor those Findings?
- Which ModelRuns participated in execution?

Traceability does not imply bit-for-bit reproducibility, especially for nondeterministic operations.

Canonical provenance graph:

```text
Insight
    ->
IntelligenceRun
    ->
IntelligenceContext
    ->
supporting Findings
    ->
EvidenceReferences
    ->
KCC
```

ModelRuns attach to IntelligenceRun as execution provenance.

## 008.7 — Uatu Failure, Degradation and Independence

Uatu is an optional higher-level intelligence layer.

Its unavailability or failure must not make unavailable:

- KC/KCC;
- organizational knowledge;
- independent Observer execution;
- trusted Findings;
- existing KCI history.

Failure of:

- a model;
- ModelProvider;
- a specific Uatu IntelligenceOperation;
- a specific IntelligenceRun

is not a global KCI or Knowledge Center failure.

Findings are standalone trusted KCI artifacts.

Their meaning, provenance, and availability do not depend on Uatu availability.

The unit of Uatu analytical execution outcome/failure remains:

```text
IntelligenceRun
```

Do not introduce a global Uatu analytical transaction.

Do not introduce a global Uatu success/failure state.

Failure of one Uatu IntelligenceOperation does not automatically fail another operation.

The following are legal successful outcomes and are not Uatu failure:

- zero InsightCandidates;
- some Candidates rejected by Runtime;
- all Candidates rejected by Runtime, if the operation itself completed successfully.

A ModelRun failure does not necessarily force IntelligenceRun failure if the versioned IntelligenceOperation has another explicit legal completion path.

Contract 008 does not define a generic fallback framework.

Degradation must be observable.

It must never be silent.

The system must not secretly change:

- model;
- provider;
- analytical method;
- input scope;
- operation semantics

in order to hide a failure.

Contract 008 does not introduce a canonical global UatuStatus.

Operational monitoring/projections may later expose availability if required.

Uatu may operate asynchronously or in batch.

Contract 008 establishes no real-time latency requirement.

Historical Findings, IntelligenceRuns, and Insights remain immutable historical artifacts regardless of later Uatu availability.

Fundamental invariant:

```text
FAILURE OF UATU IS NOT FAILURE OF KNOWLEDGE CENTER.
```

## Relationship To Existing Contracts

Contract 008 builds on, and does not replace, Contracts 005-007.

Canonical observation flow:

```text
ObservationContext
    -> Observer
    -> ObserverRun
    -> FindingCandidate
    -> Finding
```

Canonical higher-level intelligence flow:

```text
Finding[]
    -> IntelligenceContext
    -> IntelligenceOperation
    -> IntelligenceRun
    -> InsightCandidate
    -> Insight
```

Uatu occupies the IntelligenceOperation-level architectural role in the second flow.

Do not introduce:

- UatuRun;
- UatuContext;
- UatuFinding;
- UatuInsight;
- MetaObserverRun.

Existing contracts already provide the required canonical artifacts.

## Explicit Deferred Concerns

Contract 008 does not implement or require:

- EvidenceResolver;
- Finding selection/search service;
- Signals;
- scheduling;
- Agents;
- Investigations;
- Actions;
- Tasks;
- recommendations;
- publication;
- local LLM integration;
- llama.cpp;
- GGUF;
- cloud model integration;
- PromptRegistry;
- chain-of-thought storage;
- Uatu memory;
- global Uatu status;
- fallback router;
- generic UatuManager/UatuService/UatuEngine;
- new KCC/domain entity models.

These remain separate future concerns.
