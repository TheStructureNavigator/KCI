# KCI Contract 006 — Insight

Status: APPROVED

## Core Distinction

```text
Finding = noteworthy observation
Insight = new synthesis / interpretation
```

An Insight is not a prettier Finding, a summary of Findings, concatenated Finding text, raw LLM output, a recommendation, an action, a task, an alert, a publication, a workflow object, or objective guaranteed truth.

Canonical epistemic chain:

```text
KCC Fact
    |
    v
EvidenceRecord
    |
    | EvidenceReference
    v
Finding
    |
    | supporting finding_id
    v
Insight
```

Wider flow:

```text
KCC Dataset/Snapshot
    -> ObservationContext
    -> Observer
    -> FindingCandidate
    -> Runtime
    -> Finding
    -> IntelligenceContext
    -> future IntelligenceOperation
    -> InsightCandidate
    -> Runtime
    -> Insight
```

Future IntelligenceOperation is future/deferred. Contract 006 implements only the Insight artifact, InsightCandidate, validation/promotion boundary, and persistence needed for the artifact.

## 006.1 — Insight Identity and Meaning

Insight is an immutable historical KCI artifact representing one new analytical claim produced through synthesis/interpretation of one or more trusted Findings belonging to one exact IntelligenceContext.

A Finding represents an analytical observation.

An Insight represents higher-level interpretation/synthesis.

Insight must semantically represent a new analytical claim. It must not merely copy one Finding, concatenate Finding text, or mechanically summarize Findings.

Runtime does not enforce "new synthesis" using text similarity, heuristics, embeddings, LLM calls, or semantic reasoning. That is the responsibility of a future intelligence operation.

An Insight may be supported by one Finding. The boundary is semantic synthesis, not artifact count.

Each trusted Insight has a unique `insight_id`. It is not a content hash, deterministic from claim content, or a deduplication key.

Two separately promoted Insights may have identical analytical content and still have different `insight_id` values.

Semantic equivalence, deduplication, correlation, and supersession are not implemented.

## 006.2 — Insight Support

Every trusted Insight has at least one supporting trusted Finding.

Canonical direct support is:

```text
supporting_finding_ids
```

not direct EvidenceReferences.

The provenance chain is:

```text
Insight
    -> supporting Findings
        -> their EvidenceReferences
            -> exact KCC Evidence
```

All supporting Findings must belong to the exact IntelligenceContext used to produce the Insight.

Distinction:

```text
IntelligenceContext
    = all Findings available to the operation

supporting_finding_ids
    = exact Findings supporting this Insight claim
```

An Insight does not need to reference every Finding in its IntelligenceContext.

Runtime owns referential integrity and context containment.

Future intelligence operation owns semantic relevance and analytical sufficiency.

Contract 006 does not add canonical direct `Insight -> EvidenceReference`.

It does not copy Finding content, Finding subjects, Finding metadata, Finding Evidence, or EvidenceRecord payloads into Insight support persistence.

## 006.3 — Insight Claim

InsightCandidate analytical content:

- `category`
- `subjects`
- `significance`
- `title`
- `synthesis`
- `supporting_finding_ids`
- `metadata`

Use the existing minimal EntityReference contract for subjects.

Do not create InsightSubject domain entities or KCC domain classes such as Machine, Employee, Project, or Department.

`category` is a stable machine-readable intelligence semantic category. There is no global category enum in Contract 006.

`title` is a short human-readable label.

`synthesis` is the final analytical claim. Contract 006 does not use Finding's `observation` field and does not persist chain-of-thought.

Insight may contain zero or more EntityReference subjects. Runtime validates structure only. Runtime does not automatically calculate Insight subjects as the union of Finding subjects.

`metadata` may contain structured analytical details specific to Insight semantics, but must not copy KCC Facts, Dataset payloads, EvidenceRecord payloads, complete Findings, or arbitrary source-system records.

Insight and InsightCandidate do not contain `confidence`.

## 006.4 — Insight Significance

Every trusted Insight contains `significance`.

Contract 006 v1 scale:

- `low`
- `medium`
- `high`

Finding.severity != Insight.significance.

Runtime must not derive significance from Finding severity, max severity, average severity, Finding count, number of domains, or cross-domain composition.

The future intelligence operation assigns analytical significance.

Significance means the significance of the synthesized analytical claim according to the semantics of the intelligence operation.

Significance is not confidence, probability, urgency, action priority, publication priority, or exact business impact.

High significance does not automatically trigger alert, publication, Investigation, or Action.

No global numeric intelligence score is introduced.

## 006.5 — Insight Provenance and IntelligenceContext

Every trusted Insight is traceable to the exact IntelligenceContext that represented the full Finding input available to the operation.

Insight has:

```text
intelligence_context_id
```

Preserve the distinction:

```text
intelligence_context_id
    = complete available Finding input

supporting_finding_ids
    = exact Finding artifacts supporting this claim
```

Supporting Findings must be a subset of Findings in that IntelligenceContext.

Insight does not copy IntelligenceContext content.

Insight has `created_at`, meaning only the time the historical Insight artifact was created. It does not mean phenomenon time, Dataset period, Dataset `as_of`, Snapshot `generated_at`, Finding `created_at`, or execution start time.

Context = input.

Run = execution occurrence.

Insight = output claim.

Run is future/deferred; IntelligenceRun does not exist yet.

## 006.6 — InsightCandidate and Promotion

Future intelligence operations produce InsightCandidate objects.

They do not directly create trusted Insight artifacts.

InsightCandidate contains analytical content only:

- `category`
- `subjects`
- `significance`
- `title`
- `synthesis`
- `supporting_finding_ids`
- `metadata`

InsightCandidate does not own trusted system provenance such as `insight_id`, trusted `intelligence_context_id`, `created_at`, or future `intelligence_run_id`.

Runtime promotion validates structure, at least one support, no duplicate support IDs, persisted trusted Findings, and support containment within the exact IntelligenceContext.

Runtime supplies `insight_id`, exact `intelligence_context_id`, and `created_at`.

Runtime must not rewrite synthesis, title, category, significance, subjects, metadata, or supporting Findings.

Raw model output is not Insight and is not automatically InsightCandidate.

Partial-success policy for multiple future candidates in one execution is deferred.

## 006.7 — Insight Immutability and Persistence Boundary

Trusted Insight is an immutable historical analytical artifact.

After promotion, do not mutate category, subjects, significance, title, synthesis, supporting Findings, metadata, or IntelligenceContext provenance.

Canonical persistence stores Insight-owned content and reference-based provenance:

```text
insights
    insight_id
    intelligence_context_id
    category
    significance
    title
    synthesis
    metadata_json
    created_at

insight_subjects
    insight_id
    entity_type
    entity_id

insight_findings
    insight_id
    finding_id
```

Supporting Findings are stored by reference only.

Persistence must not copy Finding title, observation, severity, metadata, subjects, EvidenceReferences, or Evidence payload.

Insight subjects remain minimal EntityReference values and do not create KCI-owned domain entities.

Insight does not own Finding, IntelligenceContext, ObserverRun, ObservationContext, or Evidence.

Deleting an Insight must not delete upstream provenance artifacts.

Insight is not a workflow object. Contract 006 does not add status, review_status, published, dismissed, confirmed, superseded, assigned_to, due_date, resolution, action_priority, recommendation, or next_action.

## Explicit Deferred Concerns

- IntelligenceRun
- IntelligenceOperation execution framework
- Uatu
- MetaObserver
- EvidenceResolver
- SelectionRun
- selection algorithms
- Signals
- triggering
- scheduler
- review lifecycle
- feedback
- publication
- supersession
- recommendations
- Investigations
- Tasks
- Actions
- Agents
- semantic deduplication
- semantic correlation
