# UATU-OP-001 — Cross-Finding Pattern Synthesis

Status: SPECIFICATION / BENCHMARK

Operation ID:

```text
uatu.cross_finding_pattern_synthesis
```

This document defines the approved analytical semantics and benchmark infrastructure for OP-001. It does not implement an LLM-powered operation, a heuristic substitute, model integration, scheduling, selection, EvidenceResolver, or Uatu service framework.

## Purpose

OP-001 searches one exact `IntelligenceContext` for grounded higher-order patterns emerging from relationships between trusted `Finding` artifacts.

A valid pattern:

- uses at least two distinct Findings;
- expresses analytical information emerging from their relationship;
- contains information not expressed by any supporting Finding individually;
- is not merely a paraphrase, concatenation, or summary of Findings.

Conceptually:

```text
F1 says A
F2 says B

A + B -> new supported analytical meaning C
```

`C` must not simply equal `paraphrase(A)`, `paraphrase(B)`, or `A and B`.

The operation may return zero or more independent `InsightCandidate` values.

## Responsibility

OP-001 is an `IntelligenceOperation` specification. It eventually occupies this flow:

```text
IntelligenceContext
    -> uatu.cross_finding_pattern_synthesis
    -> IntelligenceRun
    -> InsightCandidate
    -> Runtime validation
    -> Insight
```

This benchmark stops before implementing the analytical operation itself.

Runtime continues to own execution integrity, candidate validation, Insight promotion, rejection telemetry, and persistence. OP-001 owns only the future analytical behavior that proposes candidates.

## Input Boundary

The only analytical input is the exact supplied `IntelligenceContext` and the trusted Findings it references.

Findings may come from the same Observer, different Observers, same or different domains, same or different periods, and same or different subjects. Shared subject is not required.

Mere co-presence in an `IntelligenceContext` never establishes a relationship.

OP-001 v1 operates only on canonical Finding content. It does not require or invoke EvidenceResolver.

## Pattern Definition

OP-001 v1 recognizes exactly three pattern types.

### co_occurring

Analytically related phenomena occurring in a compatible organizational, operational, or temporal context.

The Findings must contain a grounded basis for their joint interpretation.

### recurring

Analytically similar phenomena appearing in distinct temporal occurrences.

Requires analytical similarity and distinct temporal occurrences.

### compound

Several Findings jointly reveal materially different dimensions of a broader shared analytical object, scope, or problem.

Requires a shared analytical object or scope plus distinct but materially related dimensions.

No additional pattern types are allowed in v1.

## Forbidden Claims

OP-001 v1 must not produce:

- causal claims;
- predictive claims;
- counterfactual claims;
- prescriptive claims;
- unsupported generalizations;
- invented relationships.

Forbidden causal meaning includes claims equivalent to:

- A caused B
- B resulted from A
- A explains B
- B is due to A
- A drives B

OP-001 v1 also must not recommend actions or predict future outcomes.

Analytical restraint applies to all Candidate fields, including category, subjects, significance, title, synthesis, support, and metadata.

## Grounding And Support

Every valid Candidate requires both phenomenon support and relationship support.

Phenomenon support means the supporting Findings actually support the phenomena stated in the Candidate.

Relationship support means the supporting Findings contain sufficient basis for the relationship expressed by the declared pattern type.

For `co_occurring`, require grounded contextual compatibility.

For `recurring`, require analytical similarity across distinct temporal occurrences.

For `compound`, require a shared analytical object or scope plus distinct materially related dimensions.

The following alone are not sufficient relationship support:

- same broad month;
- same broad domain;
- same severity;
- presence in the same IntelligenceContext;
- general organizational proximity.

Support must be sufficient, relevant, and minimal. Every supporting Finding must materially support the specific pattern claim.

Severity is not relevance.

If Finding content does not sufficiently ground a relationship, the operation should narrow the claim to what is supported if a valid pattern remains. Otherwise it should return no Candidate.

Missing relationship support must never be filled with domain assumptions or model-generated hypotheses.

## Candidate Semantics

OP-001 uses the existing Contract 006 `InsightCandidate`. It does not create `PatternInsight` or another canonical artifact.

All OP-001 Candidates use:

```text
category = "uatu.cross_finding_pattern"
```

Required operation-specific metadata:

```text
metadata.pattern_type
```

Allowed `pattern_type` values:

- `co_occurring`
- `recurring`
- `compound`

Each Candidate requires at least two unique `supporting_finding_ids`.

All supporting Findings must belong to the exact `IntelligenceContext`.

Subjects represent entities genuinely addressed by the new Insight claim. They are not a mechanical union of subjects from supporting Findings and must not introduce ungrounded entities.

Title is a concise name of the pattern and must not smuggle in forbidden analytical claims.

Synthesis is one coherent atomic analytical claim that adds new information from joint interpretation and is not a summary or concatenation.

## Significance Semantics

Allowed values remain:

- `low`
- `medium`
- `high`

For OP-001:

`low` means the pattern adds new information but materiality remains local or limited.

`medium` means the pattern reveals a material phenomenon combining multiple Findings with meaningful operational or organizational relevance.

`high` means the pattern reveals a broader or recurring phenomenon whose joint interpretation exposes a materially important issue beyond an individual Finding.

Significance is not probability, confidence, causal strength, evidence quality, maximum Finding severity, or number of supporting Findings.

Do not implement `significance = max(finding.severity)` or support-count based scoring.

## Zero Output And Duplicates

No valid pattern is represented by:

```text
[]
```

Do not create a canonical "no pattern reason" artifact.

One coherent discovered pattern should produce one Candidate.

OP-001 v1 does not introduce global semantic deduplication, embeddings, LLM judges, or similarity infrastructure. The benchmark includes a structural duplicate-support-set check for the explicit duplicate scenario.

## Benchmark Philosophy

The benchmark is a behavioral specification created before any model-assisted OP-001 implementation.

It uses small fictional synthetic contexts with auditable expected outcomes. Expected outcomes encode deterministic structural expectations and human-review semantic expectations separately.

The deterministic evaluator checks what can be checked without pretending to understand language:

- output schema / Candidate validity;
- candidate count;
- category;
- `metadata.pattern_type`;
- supporting Finding membership;
- required support;
- forbidden support;
- support uniqueness;
- minimum support count;
- expected significance;
- zero-output correctness;
- explicit duplicate support-set behavior.

It does not claim to prove:

- analytical novelty;
- semantic grounding;
- causal restraint;
- unsupported generalization;
- synthesis quality.

Those remain human review concerns.

## Human Review Rubric

The benchmark preserves a multidimensional human-review profile. Reviewers assess:

- pattern detection;
- analytical novelty;
- relationship grounding;
- support correctness;
- support minimality;
- distractor resistance;
- analytical restraint;
- unsupported causality;
- unsupported prediction;
- unsupported prescription;
- unsupported generalization;
- significance calibration;
- atomicity/coherence;
- zero-output judgment.

There is no LLM-as-a-judge and no required aggregate score.

False positive, invented relationship, unsupported strong claim, and missed pattern remain visibly different failure modes.

## OP-001.7 — Model Input Contract

OP-001 v1 defines an operation-private bounded model input:

```text
Op001ModelInput
    findings[]
```

Each projected Finding contains exactly:

- `finding_id`
- `observer_id`
- `category`
- `severity`
- `subjects`
- `title`
- `observation`
- `metadata`

Projected subjects contain only:

- `entity_type`
- `entity_id`

`metadata` is the bounded canonical metadata already present on the trusted Finding. It must not be enriched, dereferenced, or used as a route to fetch more context.

OP-001 model input must not include:

- EvidenceReferences;
- Evidence payloads;
- `observer_version`;
- `observer_run_id`;
- `Finding.created_at`;
- IntelligenceContext ID;
- IntelligenceContext `created_at`;
- IntelligenceRun data;
- KCC entity enrichment;
- source datasets;
- repository handles;
- arbitrary fetched data.

Temporal reasoning must not use `Finding.created_at`; artifact creation time is not organizational event time.

Input projection is deterministic and uses `finding_id` ascending order, independent of repository retrieval order.

Projection must resolve only Findings already contained in the exact IntelligenceContext. It must not search for additional Findings, enrich from KCC, dereference EvidenceReferences, dereference entity IDs, infer missing fields, silently omit Findings, or silently truncate input.

Versioned OP-001 analytical instructions are separate from dynamic analytical input. Contract 008 still applies: this operation does not introduce canonical Prompt, PromptVersion, or PromptRegistry artifacts.

## OP-001.8 — Model Structured Output Contract

Model output is untrusted.

OP-001 v1 expects a strict operation-private structured response:

```text
Op001ModelResponse
    patterns[]
```

The valid no-pattern response is:

```json
{
  "patterns": []
}
```

No `no_pattern_reason`, explanation, status, success flag, or canonical zero-result artifact is introduced.

Each `Op001ModelPattern` contains only:

- `pattern_type`
- `supporting_finding_ids`
- `subjects`
- `significance`
- `title`
- `synthesis`

Allowed `pattern_type` values are exactly:

- `co_occurring`
- `recurring`
- `compound`

Allowed `significance` values are exactly:

- `low`
- `medium`
- `high`

`supporting_finding_ids` must contain at least two unique Finding IDs.

Output subjects contain only:

- `entity_type`
- `entity_id`

`title` and `synthesis` are required non-empty strings.

The model output schema forbids extra top-level, pattern-level, and subject-level fields.

The model must not control:

- `category`;
- arbitrary metadata;
- confidence;
- probability;
- reasoning;
- rationale;
- chain-of-thought;
- recommendations;
- actions;
- predictions;
- provenance fields;
- run IDs;
- evidence.

Before constructing any `InsightCandidate`, OP-001 validates each parsed model pattern against the exact model input.

At minimum, OP-001 validates:

- legal `pattern_type`;
- legal `significance`;
- support count of at least two;
- unique support IDs;
- every support ID exists in the exact model input;
- every output subject is grounded in subjects of the supporting Findings;
- valid title;
- valid synthesis.

Subject grounding rule:

```text
output subjects
    subset of
subjects present in supporting Findings
```

The model may not create a broader entity merely because it could plausibly contain the supporting entities.

If support contains only:

```text
machine:M14
machine:M15
```

then output subject:

```text
plant:PL01
```

is invalid unless `plant:PL01` itself appears in the supporting Findings.

OP-001 must not repair Finding IDs, substitute similar IDs, add missing support, remove unsupported subjects and continue, change significance, rewrite claims, or infer pattern type.

Invalid individual patterns are rejected before an InsightCandidate exists. This is model-output rejection, not Runtime candidate rejection.

For each valid model pattern, OP-001 constructs the existing Contract 006 `InsightCandidate`.

OP-001 supplies:

```text
category = "uatu.cross_finding_pattern"
metadata = {"pattern_type": <validated pattern_type>}
```

The model cannot add model identity, provider data, ModelRun ID, confidence, reasoning, raw response, or execution telemetry to `InsightCandidate.metadata`.

## OP-001.9 — Model Invocation And Failure Semantics

For OP-001 v1:

```text
one IntelligenceRun
    -> one OP-001 execution
    -> exactly one ModelRun / model invocation
```

OP-001 v1 does not implement:

- multi-pass reasoning;
- planner/critic;
- judge;
- automatic retry;
- repair invocation;
- second-pass validation model;
- fallback model;
- heuristic fallback.

The model boundary is testable with a provider double that returns a predefined response or raises a controlled error. A test double must not inspect Findings and synthesize benchmark answers.

Failure semantics:

Case A: valid zero result.

```json
{
  "patterns": []
}
```

The ModelRun succeeds, OP-001 succeeds, IntelligenceRun succeeds, and zero Candidates is legal.

Case B: provider/model failure.

Examples include provider unavailable, model load failure, inference process failure, timeout, or invocation exception.

The ModelRun fails. Because OP-001 v1 has no alternate analytical path, OP-001 fails and the IntelligenceRun fails with execution failure semantics. This must never be converted to `[]`.

Case C: inference technically completes but top-level output is malformed.

Examples include non-JSON output, wrong top-level shape, missing `patterns`, forbidden top-level fields, or otherwise invalid `Op001ModelResponse`.

The ModelRun may record technical invocation success, but OP-001 parsing/contract handling fails and the IntelligenceRun fails with execution failure semantics. This must not be treated as successful zero-result analysis.

Case D: valid top-level response containing one or more invalid individual patterns.

Invalid individual patterns are rejected without repair. Valid siblings may become InsightCandidates. The operation may still complete successfully.

Model-output rejection occurs before `InsightCandidate` exists and must remain distinct from Runtime candidate rejection.

ModelRun remains the only canonical model invocation provenance artifact. OP-001 does not create an OP-001-specific ModelRun, UatuModelRun, or model-output rejection artifact.

ModelRun is execution provenance. It is not Evidence, Finding support, Insight support, or proof of analytical truth.

Behavior-affecting execution configuration must not be hidden. Future provider settings such as timeout, temperature, top_p, max output tokens, seed, and context/inference settings must be representable in effective configuration and/or ModelRun inference parameters as appropriate.

OP-001 model-assisted execution is not marked deterministic merely because a future configuration might use temperature zero.

Raw model input, raw model output, and chain-of-thought are not canonical KCI history and are not persisted by default. Do not add raw prompt/response columns to canonical persistence.

Real provider/model integration remains deferred.

## Relationship To Contracts 005-008

Contract 005 defines `IntelligenceContext` as the exact immutable set of trusted Findings supplied to the operation. OP-001 must not select its own Findings, query outside the context, or treat selection as evidence.

Contract 006 defines `InsightCandidate` and `Insight`. OP-001 returns `InsightCandidate`; runtime promotion creates trusted `Insight` artifacts.

Contract 007 defines `IntelligenceOperation`, `IntelligenceRun`, candidate validation, rejection telemetry, and `ModelRun` provenance. OP-001 will eventually be one versioned `IntelligenceOperation`.

Contract 008 defines Uatu as a meta-observer architectural role. OP-001 is one Uatu analytical operation specification; Uatu is not an Agent, scheduler, publisher, or domain model.

## Explicit Deferred Functionality

Deferred and intentionally not implemented here:

- LLM-powered Uatu operation;
- fake deterministic heuristic OP-001 implementation;
- llama.cpp, GGUF, Ollama, cloud models, or external APIs;
- real model provider integration;
- prompt optimization;
- EvidenceResolver;
- finding selection/search outside IntelligenceContext;
- arbitrary KCC queries;
- input truncation;
- retry/fallback/model routing;
- signals, scheduler, triggers;
- agents, investigations, recommendations, actions, tasks;
- PromptRegistry or PromptVersion domain artifacts;
- chain-of-thought or raw model I/O persistence;
- Uatu memory, global status, manager/service/engine framework;
- fallback model router;
- embeddings, vector DB, semantic deduplication;
- LLM-as-a-judge;
- GUI, TUI, REST, or MCP surface;
- new organization domain models.
