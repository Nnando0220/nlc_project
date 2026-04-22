"""remove user dependency from batches

Revision ID: 20260421_0003
Revises: 20260419_0002
Create Date: 2026-04-21 00:20:00
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "20260421_0003"
down_revision = "20260419_0002"
branch_labels = None
depends_on = None


def _table_columns(connection, table_name: str) -> set[str]:
    return {
        row[1]
        for row in connection.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    }


def upgrade() -> None:
    connection = op.get_bind()
    batch_columns = _table_columns(connection, "document_batches")
    if "user_id" not in batch_columns:
        connection.execute(text("DROP INDEX IF EXISTS idx_batches_user_id"))
        connection.execute(text("DROP TABLE IF EXISTS users"))
        return

    connection.execute(text("PRAGMA foreign_keys = OFF"))
    connection.execute(text("PRAGMA legacy_alter_table = ON"))
    connection.execute(text("ALTER TABLE document_batches RENAME TO document_batches_legacy"))
    connection.execute(
        text(
            """
            CREATE TABLE document_batches (
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
            )
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO document_batches (
                id,
                batch_name,
                total_files,
                processed_files,
                successful_files,
                error_files,
                anomaly_count,
                status,
                created_at,
                started_at,
                finished_at
            )
            SELECT
                id,
                batch_name,
                total_files,
                processed_files,
                successful_files,
                error_files,
                anomaly_count,
                status,
                created_at,
                started_at,
                finished_at
            FROM document_batches_legacy
            """
        )
    )
    connection.execute(text("DROP TABLE document_batches_legacy"))
    connection.execute(text("DROP INDEX IF EXISTS idx_batches_user_id"))
    connection.execute(text("DROP TABLE IF EXISTS users"))
    connection.execute(text("PRAGMA legacy_alter_table = OFF"))
    connection.execute(text("PRAGMA foreign_keys = ON"))


def downgrade() -> None:
    connection = op.get_bind()
    batch_columns = _table_columns(connection, "document_batches")
    if "user_id" in batch_columns:
        return

    connection.execute(text("PRAGMA foreign_keys = OFF"))
    connection.execute(text("PRAGMA legacy_alter_table = ON"))
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT OR IGNORE INTO users (id, name, email, password_hash)
            VALUES ('public-upload-user', 'Public Upload', 'public-upload@system.local', 'auth-disabled')
            """
        )
    )
    connection.execute(text("ALTER TABLE document_batches RENAME TO document_batches_legacy"))
    connection.execute(
        text(
            """
            CREATE TABLE document_batches (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
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
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                CHECK (status IN ('pending', 'processing', 'cancelling', 'cancelled', 'completed', 'completed_with_errors', 'failed', 'done', 'error'))
            )
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO document_batches (
                id,
                user_id,
                batch_name,
                total_files,
                processed_files,
                successful_files,
                error_files,
                anomaly_count,
                status,
                created_at,
                started_at,
                finished_at
            )
            SELECT
                id,
                'public-upload-user',
                batch_name,
                total_files,
                processed_files,
                successful_files,
                error_files,
                anomaly_count,
                status,
                created_at,
                started_at,
                finished_at
            FROM document_batches_legacy
            """
        )
    )
    connection.execute(text("DROP TABLE document_batches_legacy"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS idx_batches_user_id ON document_batches(user_id)"))
    connection.execute(text("PRAGMA legacy_alter_table = OFF"))
    connection.execute(text("PRAGMA foreign_keys = ON"))
