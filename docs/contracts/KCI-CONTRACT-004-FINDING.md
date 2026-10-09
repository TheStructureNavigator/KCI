# KCI Contract 004 — Finding

Status: APPROVED

## Core Invariant

Every Finding is one immutable, evidence-backed, noteworthy analytical claim produced by exactly one ObserverRun.

A Finding is an intelligence artifact.

It is not a KCC Fact, Evidence itself, an Insight, an alert, a notification, a recommendation, an action, a task/work item, a hypothesis, or a lifecycle/status record.

## Fact != Evidence != Finding != Insight

```text
Fact
    Something KCC knows.

Evidence
    An addressable element of KCC knowledge supporting an analytical claim.

Finding
    One analytical interpretation produced by one ObserverRun and validated by Runtime.

Insight
    Future higher-level synthesis of Findings/context.
```

Insight is deferred and is not implemented by Contract 004.

## Finding Structure

Finding v1 contains:

- `finding_id`
- `observer_run_id`
- `category`
- `subjects[]`
- `severity`
- `title`
- `observation`
- `evidence[1..n]`
- `metadata`
- `created_at`

Finding v1 has no generic confidence field.

## 004.1 — Finding Identity and Meaning

A Finding represents one analytical claim that an Observer considered noteworthy based on knowledge available in its ObservationContext and that was successfully promoted through the KCI Runtime trust boundary.

Finding is not a copy of a KCC Fact.

Finding is not Evidence.

Finding is not Insight.

A Finding is atomic in the analytical sense: one coherent analytical claim. It may use many EvidenceRecords and may concern multiple subjects.

Each Finding has a unique `finding_id` identifying one historical artifact. `finding_id` is not a deterministic hash of content, category, subject, Evidence, or ObserverRun inputs.

Two semantically equivalent Findings produced by two separate ObserverRuns remain distinct Findings with different `finding_id` values.

Each Finding belongs to exactly one ObserverRun.

Historical analytical content of a Finding is immutable.

Contract 004 does not implement lifecycle, resolution, dismissal, supersession, deduplication, or correlation.

Finding does not automatically cause notification, publication, escalation, or action.

## 004.2 — Finding Subject

Finding supports:

```text
subjects: list[EntityReference]
```

EntityReference is a minimal pointer to identity understood through KCC contracts:

```text
entity_type
entity_id
```

EntityReference is not a KCI reconstruction of a domain entity.

KCI does not introduce Machine, Employee, Shift, Project, Team, Department, OrganizationalUnit, or similar domain classes for Finding subjects.

Subjects answer:

```text
What does this Finding concern?
```

Evidence answers:

```text
What supports this Finding?
```

Finding may have zero subjects, one subject, or multiple subjects. Subject is not required.

Subject is not Dataset scope. Subject is not EvidenceReference.

Runtime may validate EntityReference structure, but it does not perform external KCC lookup or resolution during Finding promotion.

## 004.3 — Finding Claim

A Finding represents one coherent analytical claim.

Claim fields:

- `category`: stable machine-readable analytical category.
- `title`: short human-readable representation.
- `observation`: human-readable concrete analytical claim.
- `metadata`: Observer-specific structured analytical details.

Category belongs semantically to KCI intelligence, not to KCC Facts.

There is no central category registry in Contract 004.

Downstream logic should not parse `title` or `observation` when structured Finding fields already provide relevant semantics.

If an Observer identifies multiple independent analytical claims, it should produce multiple FindingCandidates.

`metadata` must not become an undocumented side channel for copying KCC Facts into KCI. Information supporting a factual claim must remain tied to Evidence.

Contract 004 does not implement a universal structured claim language, recommendations, or action fields.

## 004.4 — Finding Severity

Finding severity is required.

Allowed v1 values:

- `low`
- `medium`
- `high`

Conceptual ordering:

```text
low < medium < high
```

Severity means the degree of significance of the observed phenomenon according to the semantics of the Observer that produced it.

Severity does not mean global business impact, urgency, priority, confidence, or automatic escalation level.

The Observer owns analytical rules assigning severity.

For deterministic Observers, severity must be deterministic from ObservationContext, effective configuration, and versioned Observer behavior.

Contract 004 does not add `critical`, numeric severity scores, business impact scores, urgency, or priority.

## 004.5 — Confidence and Analytical Uncertainty

Finding v1 has no generic confidence field.

Generic confidence is absent from:

- FindingCandidate
- Finding
- ProductionObserver output
- Finding persistence

A generic confidence value has no stable cross-observer meaning across deterministic rules, statistical analysis, classifiers, anomaly detectors, and model-assisted Observers.

Method-specific analytical measures may appear in `metadata` when explicitly meaningful, such as `anomaly_score`, `classifier_probability`, or `z_score`.

Model-reported confidence must not automatically become Finding confidence.

Evidence quality, data completeness, freshness, statistical uncertainty, and model confidence remain separate concepts.

Contract 004 does not implement a calibration framework.

## 004.6 — Finding Evidence Semantics

Every trusted Finding must contain at least one EvidenceReference.

EvidenceReference identity remains exactly:

```text
(dataset, snapshot_id, ref)
```

All EvidenceReferences must refer to explicit EvidenceRecords from the exact ObservationContext used by the originating ObserverRun.

Observer owns semantic relevance of Evidence to the analytical claim.

Runtime owns referential integrity of Evidence.

Runtime validates that the referenced Dataset exists in the exact ObservationContext, `snapshot_id` matches, and `ref` identifies an explicit EvidenceRecord.

Runtime does not decide whether Evidence logically or domain-semantically proves the claim.

One Finding may reference multiple EvidenceRecords, including EvidenceRecords from multiple Datasets in the same ObservationContext.

One EvidenceRecord may support multiple Findings.

Finding persists EvidenceReferences, not copies of canonical Evidence payload.

Missing Evidence may not be replaced by model output, metadata, confidence/score, or Observer prose.

If a FindingCandidate has zero EvidenceReferences, it fails promotion and is recorded as a validation failure.

Hypothesis artifacts are deferred.

## 004.7 — Finding Time Semantics

Finding keeps `created_at`.

`created_at` means the time when the KCI Finding artifact was created.

It does not mean phenomenon time, Dataset period, Dataset `as_of`, or Dataset `generated_at`.

Temporal meaning of analyzed knowledge remains reconstructable through:

```text
Finding
    ↓
ObserverRun
    ↓
ObservationContext
    ↓
Dataset temporal metadata
```

Contract 004 does not automatically copy Dataset `period` or `as_of` into Finding.

Specific analytical time details may be stored in Observer-specific metadata when genuinely needed.

Finding `created_at` must not become a hidden analytical input.

Contract 004 does not implement freshness, expiry, TTL, or automatic Finding expiration.

## Explicit Deferred Concerns

- Insight
- Uatu
- Agents
- hypotheses
- Finding lifecycle/status
- review/confirmation/dismissal
- resolution
- supersession
- deduplication
- correlation
- publication
- notifications
- recommended actions
- urgency
- priority
- global business impact
- confidence calibration
- freshness/expiry/TTL
- entity graph / global entity resolution
