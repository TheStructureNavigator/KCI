# Benchmarks

This directory is reserved for reproducible KCI-specific quality evaluations.

Future scenarios should compare observer/model versions against expected outcomes such as detected findings, missed findings, unexpected findings, invalid evidence references, unsupported claims, and human usefulness ratings.

The goal is operational intelligence quality, not raw model speed alone.

## Uatu OP-001

`benchmarks/uatu/op001_scenarios.json` defines the synthetic benchmark specification for:

```text
uatu.cross_finding_pattern_synthesis
```

The benchmark is intentionally separate from any future model-assisted implementation. Deterministic evaluation checks structural properties only; semantic quality remains assigned to the documented human-review rubric.
