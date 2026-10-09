# KCI - Knowledge Center Intelligence

KCI is an experimental, local/offline prototype for an intelligence layer above KCC.

This checkpoint intentionally implements only a walking skeleton:

```text
Synthetic Dataset
    -> ProductionObserver
    -> FindingCandidate
    -> Core Validation
    -> Finding
    -> SQLite
```

KCI does not reconstruct the KCC domain model. It observes supplied dataset snapshots and produces evidence-backed findings about those snapshots.

## Run

```powershell
python -m kci --dataset datasets\synthetic\unexplained_downtime.json --db kci.sqlite3
```

The demo runs the deterministic `ProductionObserver`, validates candidates, persists the observer run and accepted findings, and prints a concise summary.

## Test

```powershell
python -m pytest
```

Tests do not require internet access, llama.cpp, a local model, Docker, or any external service.

## Architecture

- [Architecture overview](docs/architecture.md)
- [Architecture contracts](docs/contracts/README.md)
