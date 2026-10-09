from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS observer_runs (
    run_id TEXT PRIMARY KEY,
    observer_id TEXT NOT NULL,
    observer_version TEXT NOT NULL,
    context_id TEXT NOT NULL,
    effective_configuration_json TEXT NOT NULL,
    dataset TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    duration_ms REAL,
    status TEXT NOT NULL CHECK (status IN ('succeeded', 'failed', 'requirements_failed')),
    failure_category TEXT,
    candidates_count INTEGER NOT NULL,
    findings_count INTEGER NOT NULL,
    validation_failures_count INTEGER NOT NULL,
    model_runs_count INTEGER NOT NULL,
    error TEXT
);

CREATE TABLE IF NOT EXISTS model_runs (
    run_id TEXT PRIMARY KEY,
    observer_run_id TEXT,
    intelligence_run_id TEXT,
    provider TEXT NOT NULL,
    model TEXT,
    model_artifact_hash TEXT,
    quantization TEXT,
    inference_parameters_json TEXT NOT NULL,
    prompt_version TEXT,
    context_size INTEGER,
    input_tokens INTEGER,
    output_tokens INTEGER,
    model_load_ms REAL,
    prompt_eval_ms REAL,
    generation_ms REAL,
    total_ms REAL,
    started_at TEXT,
    finished_at TEXT,
    prompt_tokens_per_second REAL,
    generation_tokens_per_second REAL,
    peak_memory_mb REAL,
    status TEXT NOT NULL CHECK (status IN ('succeeded', 'failed', 'requirements_failed')),
    error TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (observer_run_id) REFERENCES observer_runs(run_id) ON DELETE CASCADE,
    FOREIGN KEY (intelligence_run_id) REFERENCES intelligence_runs(run_id) ON DELETE CASCADE,
    CHECK (
        (observer_run_id IS NOT NULL AND intelligence_run_id IS NULL)
        OR (observer_run_id IS NULL AND intelligence_run_id IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS findings (
    finding_id TEXT PRIMARY KEY,
    observer_run_id TEXT NOT NULL,
    observer_id TEXT NOT NULL,
    observer_version TEXT NOT NULL,
    category TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    observation TEXT NOT NULL,
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    FOREIGN KEY (observer_run_id) REFERENCES observer_runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS finding_subjects (
    subject_id INTEGER PRIMARY KEY AUTOINCREMENT,
    finding_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    FOREIGN KEY (finding_id) REFERENCES findings(finding_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS evidence (
    evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
    finding_id TEXT NOT NULL,
    dataset TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    ref TEXT NOT NULL,
    FOREIGN KEY (finding_id) REFERENCES findings(finding_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS intelligence_contexts (
    intelligence_context_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS intelligence_context_findings (
    intelligence_context_id TEXT NOT NULL,
    finding_id TEXT NOT NULL,
    PRIMARY KEY (intelligence_context_id, finding_id),
    FOREIGN KEY (intelligence_context_id) REFERENCES intelligence_contexts(intelligence_context_id),
    FOREIGN KEY (finding_id) REFERENCES findings(finding_id)
);

CREATE TABLE IF NOT EXISTS insights (
    insight_id TEXT PRIMARY KEY,
    intelligence_context_id TEXT NOT NULL,
    intelligence_run_id TEXT,
    category TEXT NOT NULL,
    significance TEXT NOT NULL,
    title TEXT NOT NULL,
    synthesis TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (intelligence_context_id) REFERENCES intelligence_contexts(intelligence_context_id),
    FOREIGN KEY (intelligence_run_id) REFERENCES intelligence_runs(run_id)
);

CREATE TABLE IF NOT EXISTS insight_subjects (
    subject_id INTEGER PRIMARY KEY AUTOINCREMENT,
    insight_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    UNIQUE (insight_id, entity_type, entity_id),
    FOREIGN KEY (insight_id) REFERENCES insights(insight_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS insight_findings (
    insight_id TEXT NOT NULL,
    finding_id TEXT NOT NULL,
    PRIMARY KEY (insight_id, finding_id),
    FOREIGN KEY (insight_id) REFERENCES insights(insight_id) ON DELETE CASCADE,
    FOREIGN KEY (finding_id) REFERENCES findings(finding_id)
);

CREATE TABLE IF NOT EXISTS intelligence_runs (
    run_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL,
    operation_version TEXT NOT NULL,
    deterministic INTEGER NOT NULL,
    intelligence_context_id TEXT NOT NULL,
    effective_configuration_json TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    duration_ms REAL,
    status TEXT NOT NULL CHECK (status IN ('succeeded', 'failed', 'requirements_failed')),
    failure_category TEXT,
    candidates_count INTEGER NOT NULL,
    promoted_count INTEGER NOT NULL,
    rejected_count INTEGER NOT NULL,
    model_runs_count INTEGER NOT NULL,
    error TEXT
);

CREATE TABLE IF NOT EXISTS intelligence_candidate_rejections (
    rejection_id INTEGER PRIMARY KEY AUTOINCREMENT,
    intelligence_run_id TEXT NOT NULL,
    candidate_index INTEGER NOT NULL,
    failure_category TEXT NOT NULL,
    detail TEXT NOT NULL,
    FOREIGN KEY (intelligence_run_id) REFERENCES intelligence_runs(run_id) ON DELETE CASCADE
);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA_SQL)
    connection.commit()
