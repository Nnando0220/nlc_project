PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS document_batches (
    id TEXT PRIMARY KEY,
    batch_name TEXT NOT NULL,
    total_files INTEGER NOT NULL DEFAULT 0,
    processed_files INTEGER NOT NULL DEFAULT 0,
    successful_files INTEGER NOT NULL DEFAULT 0,
    error_files INTEGER NOT NULL DEFAULT 0,
    anomaly_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    finished_at TEXT,
    CHECK (status IN ('pending', 'processing', 'cancelling', 'cancelled', 'completed', 'completed_with_errors', 'failed', 'done', 'error'))
);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    file_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'txt',
    mime_type TEXT,
    file_size_bytes INTEGER NOT NULL DEFAULT 0,
    raw_text TEXT,
    extracted_text TEXT,
    extracted_data TEXT,
    missing_fields TEXT,
    truncated_fields TEXT,
    decode_status TEXT NOT NULL DEFAULT 'pending',
    parse_status TEXT NOT NULL DEFAULT 'pending',
    extraction_status TEXT NOT NULL DEFAULT 'pending',
    error_code TEXT,
    error_message TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    processed_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (batch_id) REFERENCES document_batches(id) ON DELETE CASCADE,
    CHECK (status IN ('pending', 'processing', 'done', 'error'))
);

CREATE TABLE IF NOT EXISTS ai_analyses (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL UNIQUE,
    provider TEXT,
    model TEXT,
    requested_model TEXT,
    fallback_used TEXT,
    attempted_models TEXT,
    prompt_version TEXT,
    classification TEXT,
    risk_score REAL,
    summary TEXT,
    inconsistencies TEXT,
    confidence_overall REAL,
    raw_response TEXT,
    extraction_status TEXT,
    missing_fields TEXT,
    truncated_fields TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS anomalies (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    rule_code TEXT NOT NULL,
    rule_name TEXT NOT NULL,
    severity TEXT NOT NULL,
    confidence TEXT NOT NULL,
    evidence_fields TEXT,
    evidence_values TEXT,
    details TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (batch_id) REFERENCES document_batches(id) ON DELETE CASCADE,
    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    document_id TEXT,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT NOT NULL,
    payload_ref TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (batch_id) REFERENCES document_batches(id) ON DELETE CASCADE,
    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    report_type TEXT NOT NULL DEFAULT 'results',
    csv_path TEXT NOT NULL,
    generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (batch_id) REFERENCES document_batches(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_documents_batch_id ON documents(batch_id);
CREATE INDEX IF NOT EXISTS idx_analyses_document_id ON ai_analyses(document_id);
CREATE INDEX IF NOT EXISTS idx_anomalies_batch_id ON anomalies(batch_id);
CREATE INDEX IF NOT EXISTS idx_anomalies_document_id ON anomalies(document_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_batch_id ON audit_logs(batch_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_document_id ON audit_logs(document_id);
CREATE INDEX IF NOT EXISTS idx_reports_batch_id ON reports(batch_id);
