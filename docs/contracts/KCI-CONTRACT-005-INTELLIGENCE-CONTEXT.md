# KCI Contract 005 — Intelligence Context

Status: APPROVED

## Core Meaning

```text
ObservationContext
    = exact KCC knowledge input supplied to an Observer

IntelligenceContext
    = exact KCI Finding input supplied to a higher-level intelligence operation
```

Core invariants:

```text
co-presence != relationship
selection != evidence
IntelligenceContext != claim
```

IntelligenceContext is an immutable input artifact.

It is not KCI Memory, a Finding store, a claim, an Insight, an Investigation, a selection policy, an execution/run, a query mechanism over KCC, or a Dataset container.

## 005.1 — Purpose and Boundary

IntelligenceContext represents the exact, frozen set of existing trusted KCI Finding artifacts supplied to one higher-level intelligence operation.

The primary input unit is Finding.

IntelligenceContext is semantically distinct from ObservationContext.

ObservationContext contains KCC knowledge projections and immutable Snapshots.

IntelligenceContext contains references to KCI Finding artifacts.

IntelligenceContext must not contain Dataset payloads, Snapshot payloads, or EvidenceRecord payloads.

Existing Finding provenance and EvidenceReferences remain the path back toward KCC knowledge.

IntelligenceContext performs no I/O, KCC access, Evidence resolution, selection, analysis, or execution.

This contract is not bound specifically to Uatu.

## 005.2 — Intelligence Context Identity

IntelligenceContext has stable logical identity:

```text
intelligence_context_id
```

It represents the exact set of Finding artifacts in the context.

Identity is deterministic and derived from a canonical, order-independent representation of included `finding_id` values using SHA-256:

```text
intelligence_context_sha256:<digest>
```

The same exact `finding_id` set produces the same `intelligence_context_id`.

Changing the set by adding, removing, or replacing a Finding produces a different identity.

Input order does not affect identity.

Two semantically identical Findings with different `finding_id` values are different historical artifacts and therefore produce different IntelligenceContext identities.

Context identity describes input only. It does not include consumer identity, future Uatu version, future IntelligenceRun, model, prompt, configuration, execution time, `created_at`, selection mechanism, selection reason, or selection method.

IntelligenceContext must contain at least one Finding.

## 005.3 — Finding Provenance and Context Composition

Only existing trusted Finding artifacts may participate in an IntelligenceContext.

IntelligenceContext does not accept FindingCandidates, arbitrary claim dictionaries, raw Observer output, or unvalidated pseudo-Findings.

A context may contain Findings originating from different Observers, Observer versions, ObserverRuns, ObservationContexts, Datasets, Snapshots, domains, subjects, categories, severities, scopes, temporal periods, `as_of` states, and `created_at` values.

Cross-domain composition is allowed.

Do not create domain-specific context classes such as ProductionIntelligenceContext or MaintenanceIntelligenceContext.

IntelligenceContext does not require common subject, category, severity, period, `as_of`, `generated_at`, Observer, ObserverRun, or ObservationContext.

Co-presence does not establish causal, temporal, organizational, semantic, or root-cause relationship.

Each `finding_id` may appear at most once. Duplicate input is invalid and must not be silently deduplicated.

Semantic deduplication is outside this contract.

IntelligenceContext does not filter Findings by severity, age, category, subject, Observer, or any other analytical property. Selection is outside this contract.

## 005.4 — Context Semantics vs Selection Semantics

IntelligenceContext represents what was supplied.

It does not represent why those Findings were selected.

Selection is not Evidence.

The fact that Findings were selected together is not Evidence and must not be treated as support for an analytical claim.

IntelligenceContext itself is not an analytical claim.

Contract 005 does not add required fields such as purpose, question, goal, reason, topic, selection_reason, selection_method, or selection_version.

The same IntelligenceContext may later be consumed by different intelligence operations for different purposes without changing identity.

Manual human selection also does not create Evidence or an analytical relationship between Findings.

## 005.5 — Evidence Access Boundary

IntelligenceContext contains Findings and therefore preserves their existing EvidenceReferences.

It must not copy or automatically materialize EvidenceRecord payloads.

Future evidence inspection boundary:

```text
IntelligenceContext
        |
        v
future intelligence operation
        |
        +-- reads Findings
        |
        +-- may request resolution of existing EvidenceReferences
                |
                v
        future EvidenceResolver
                |
                v
               KCC
```

EvidenceResolver is not implemented by Contract 005.

Finding defines the evidence boundary.

Higher intelligence may inspect that evidence but may not silently expand beyond it.

Future Evidence resolution may only operate on canonical EvidenceReferences already belonging to Findings in the supplied IntelligenceContext.

Historical Evidence remains addressed using the exact `(dataset, snapshot_id, ref)` tuple. There is no fallback-to-latest semantics.

Whether evidence was actually resolved during a future execution is execution provenance, not IntelligenceContext identity.

## 005.6 — Historical Stability and Referential Integrity

IntelligenceContext refers to concrete historical Finding artifacts by `finding_id`.

There is no latest Finding, dynamic Finding query, automatic replacement, or automatic update to newer equivalent Findings.

If `F31` exists in `IC17` and later `F88` represents a newer similar observation, `IC17` still contains `F31`.

Using `F88` requires a different IntelligenceContext.

Runtime enforces referential integrity during construction:

1. at least one `finding_id` requested,
2. no duplicate `finding_id` values,
3. every `finding_id` exists,
4. every `finding_id` identifies a trusted persisted Finding,
5. resulting context structure is valid.

Canonical IntelligenceContext persistence stores Finding references, not copies of Finding analytical content.

It does not duplicate category, title, observation, severity, metadata, subjects, EvidenceReferences, Observer provenance, Dataset payload, or EvidenceRecord payload.

Contract 005 does not define retention, archival, soft deletion, or garbage collection.

## 005.7 — Construction and Execution Boundary

IntelligenceContext must be constructed before a higher-level intelligence operation starts.

The future intelligence operation must receive an already validated, immutable context.

It must not choose its own Findings, fetch arbitrary Findings from persistence, construct its own input context, or mutate the context.

Selection and construction remain separate:

```text
Selection mechanism
    decides requested finding_id values

Runtime/context construction
    validates and materializes the exact set
```

Runtime must not decide whether Findings belong together, whether they are relevant, whether they are fresh enough, whether severity is sufficient, or whether they describe the same problem.

No silent repair is allowed.

Invalid requests with missing or duplicate Findings fail without creating a partial context.

IntelligenceContext itself performs no execution. It has no `run`, `analyze`, or `ask_uatu` behavior.

## Provenance Chain

```text
KCC Snapshot
    ^
    | EvidenceReference
Finding
    ^
    | finding_id
IntelligenceContext
    ^
    | future reference
future IntelligenceRun
    ^
    |
future Insight
```

IntelligenceRun and Insight are future/deferred.

## Explicit Deferred Concerns

- Insight / InsightCandidate
- Uatu
- MetaObserver
- IntelligenceRun
- SelectionRun
- selection algorithms
- Signals
- triggering
- scheduler
- Observer Catalog / Discovery
- EvidenceResolver implementation
- Agents
- Investigations
- semantic deduplication
- automatic correlation
- KCC search/query behavior
