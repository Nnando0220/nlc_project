"""add batch cancellation statuses

Revision ID: 20260419_0002
Revises: 20260419_0001
Create Date: 2026-04-19 23:45:00
"""
from __future__ import annotations

import re

from alembic import op
from sqlalchemy import text


revision = "20260419_0002"
down_revision = "20260419_0001"
branch_labels = None
depends_on = None

TARGET_COLUMNS = [
    "id",
    "batch_name",
    "total_files",
    "processed_files",
    "successful_files",
    "error_files",
    "anomaly_count",
    "status",
    "created_at",
    "started_at",
    "finished_at",
]

DEFAULT_SELECT_BY_COLUMN = {
    "processed_files": "0",
    "successful_files": "0",
    "error_files": "0",
    "anomaly_count": "0",
    "status": "'pending'",
    "created_at": "CURRENT_TIMESTAMP",
    "started_at": "NULL",
    "finished_at": "NULL",
}


def _table_exists(connection, table_name: str) -> bool:
    return (
        connection.execute(
            text(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type = 'table' AND name = :name
                """
            ),
            {"name": table_name},
        ).fetchone()
        is not None
    )


def _table_sql(connection, table_name: str) -> str:
    row = connection.execute(
        text(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'table' AND name = :name
            """
        ),
        {"name": table_name},
    ).fetchone()
    return str(row[0] or "") if row else ""


def _table_columns(connection, table_name: str) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    }


def _next_available_temp_table_name(connection, base_name: str) -> str:
    if not _table_exists(connection, base_name):
        return base_name
    suffix = 1
    while _table_exists(connection, f"{base_name}_{suffix}"):
        suffix += 1
    return f"{base_name}_{suffix}"


def _extract_statuses_from_check_sql(sql_fragment: str) -> set[str]:
    match = re.search(r"check\s*\((.*?)\)", sql_fragment, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return set()
    return {value.lower() for value in re.findall(r"'([^']+)'", match.group(1))}


def _create_document_batches(connection, status_constraint_sql: str) -> None:
    connection.execute(
        text(
            f"""
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
                CHECK ({status_constraint_sql})
            )
            """
        )
    )


def _copy_batches_from_source(connection, source_table: str) -> None:
    source_columns = _table_columns(connection, source_table)
    select_expressions: list[str] = []
    for column in TARGET_COLUMNS:
        if column in source_columns:
            select_expressions.append(column)
        else:
            select_expressions.append(f"{DEFAULT_SELECT_BY_COLUMN.get(column, 'NULL')} AS {column}")

    connection.execute(
        text(
            f"""
            INSERT OR IGNORE INTO document_batches (
                {", ".join(TARGET_COLUMNS)}
            )
            SELECT
                {", ".join(select_expressions)}
            FROM {source_table}
            """
        )
    )


def _rebuild_document_batches(status_constraint_sql: str) -> None:
    connection = op.get_bind()
    expected_statuses = _extract_statuses_from_check_sql(f"CHECK ({status_constraint_sql})")
    has_batches = _table_exists(connection, "document_batches")
    has_legacy = _table_exists(connection, "document_batches_legacy")

    if has_batches and not has_legacy:
        current_statuses = _extract_statuses_from_check_sql(_table_sql(connection, "document_batches"))
        if current_statuses == expected_statuses:
            return

    source_tables: list[str] = []
    connection.execute(text("PRAGMA foreign_keys = OFF"))
    connection.execute(text("PRAGMA legacy_alter_table = ON"))
    try:
        if has_legacy:
            source_tables.append("document_batches_legacy")

        if has_batches:
            if has_legacy:
                current_backup_name = _next_available_temp_table_name(connection, "document_batches_current")
                connection.execute(text(f"ALTER TABLE document_batches RENAME TO {current_backup_name}"))
                source_tables.append(current_backup_name)
            else:
                connection.execute(text("ALTER TABLE document_batches RENAME TO document_batches_legacy"))
                source_tables.append("document_batches_legacy")

        _create_document_batches(connection, status_constraint_sql)

        for table_name in source_tables:
            _copy_batches_from_source(connection, table_name)

        for table_name in source_tables:
            if _table_exists(connection, table_name):
                connection.execute(text(f"DROP TABLE {table_name}"))
    finally:
        connection.execute(text("PRAGMA legacy_alter_table = OFF"))
        connection.execute(text("PRAGMA foreign_keys = ON"))


def upgrade() -> None:
    _rebuild_document_batches(
        "status IN ('pending', 'processing', 'cancelling', 'cancelled', 'completed', 'completed_with_errors', 'failed', 'done', 'error')"
    )


def downgrade() -> None:
    _rebuild_document_batches(
        "status IN ('pending', 'processing', 'completed', 'completed_with_errors', 'failed', 'done', 'error')"
    )
