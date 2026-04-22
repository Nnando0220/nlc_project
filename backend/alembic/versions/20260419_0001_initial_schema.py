"""initial schema

Revision ID: 20260419_0001
Revises:
Create Date: 2026-04-19 00:30:00
"""
from __future__ import annotations

from pathlib import Path

from alembic import op
from sqlalchemy import text


revision = "20260419_0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA_CANDIDATES = [
    Path(__file__).resolve().parents[1] / "schema.sql",
]


def _resolve_schema_path() -> Path:
    schema_path = next((candidate for candidate in SCHEMA_CANDIDATES if candidate.exists()), None)
    if schema_path is None:
        raise FileNotFoundError("Nao foi possivel localizar backend/alembic/schema.sql para a migration inicial.")
    return schema_path


def upgrade() -> None:
    schema_path = _resolve_schema_path()
    schema_sql = schema_path.read_text(encoding="utf-8")
    statements = [statement.strip() for statement in schema_sql.split(";") if statement.strip()]
    connection = op.get_bind()
    for statement in statements:
        connection.execute(text(statement))


def downgrade() -> None:
    connection = op.get_bind()
    for statement in [
        "DROP INDEX IF EXISTS idx_reports_batch_id",
        "DROP INDEX IF EXISTS idx_audit_logs_document_id",
        "DROP INDEX IF EXISTS idx_audit_logs_batch_id",
        "DROP INDEX IF EXISTS idx_anomalies_document_id",
        "DROP INDEX IF EXISTS idx_anomalies_batch_id",
        "DROP INDEX IF EXISTS idx_analyses_document_id",
        "DROP INDEX IF EXISTS idx_documents_batch_id",
        "DROP INDEX IF EXISTS idx_batches_user_id",
        "DROP TABLE IF EXISTS reports",
        "DROP TABLE IF EXISTS audit_logs",
        "DROP TABLE IF EXISTS anomalies",
        "DROP TABLE IF EXISTS ai_analyses",
        "DROP TABLE IF EXISTS documents",
        "DROP TABLE IF EXISTS document_batches",
        "DROP TABLE IF EXISTS users",
    ]:
        connection.execute(text(statement))
