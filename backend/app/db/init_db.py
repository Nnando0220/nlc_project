from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.core.config import settings
from app.db.models import AIAnalysis, Anomaly, AuditLog, Document, DocumentBatch, Report
from app.db.session import Base, engine

SCHEMA_CANDIDATES = [
    Path(__file__).resolve().parents[2] / "alembic" / "schema.sql",
]

TABLE_REQUIREMENTS: dict[str, set[str]] = {
    "document_batches": {
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
    },
    "documents": {
        "id",
        "batch_id",
        "file_name",
        "file_path",
        "source_type",
        "mime_type",
        "file_size_bytes",
        "raw_text",
        "extracted_text",
        "extracted_data",
        "missing_fields",
        "truncated_fields",
        "decode_status",
        "parse_status",
        "extraction_status",
        "error_code",
        "error_message",
        "status",
        "processed_at",
        "created_at",
    },
    "ai_analyses": {
        "id",
        "document_id",
        "provider",
        "model",
        "requested_model",
        "fallback_used",
        "attempted_models",
        "prompt_version",
        "classification",
        "risk_score",
        "summary",
        "inconsistencies",
        "confidence_overall",
        "raw_response",
        "extraction_status",
        "missing_fields",
        "truncated_fields",
        "created_at",
    },
    "reports": {"id", "batch_id", "report_type", "csv_path", "generated_at"},
    "anomalies": {
        "id",
        "batch_id",
        "document_id",
        "rule_code",
        "rule_name",
        "severity",
        "confidence",
        "evidence_fields",
        "evidence_values",
        "details",
        "created_at",
    },
    "audit_logs": {
        "id",
        "batch_id",
        "document_id",
        "stage",
        "status",
        "message",
        "payload_ref",
        "created_at",
    },
}

TABLE_COPY_COLUMNS: dict[str, list[str]] = {
    "document_batches": [
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
    ],
    "documents": [
        "id",
        "batch_id",
        "file_name",
        "file_path",
        "source_type",
        "mime_type",
        "file_size_bytes",
        "raw_text",
        "extracted_text",
        "extracted_data",
        "missing_fields",
        "truncated_fields",
        "decode_status",
        "parse_status",
        "extraction_status",
        "error_code",
        "error_message",
        "status",
        "processed_at",
        "created_at",
    ],
    "ai_analyses": [
        "id",
        "document_id",
        "provider",
        "model",
        "requested_model",
        "fallback_used",
        "attempted_models",
        "prompt_version",
        "classification",
        "risk_score",
        "summary",
        "inconsistencies",
        "confidence_overall",
        "raw_response",
        "extraction_status",
        "missing_fields",
        "truncated_fields",
        "created_at",
    ],
    "reports": ["id", "batch_id", "report_type", "csv_path", "generated_at"],
    "anomalies": [
        "id",
        "batch_id",
        "document_id",
        "rule_code",
        "rule_name",
        "severity",
        "confidence",
        "evidence_fields",
        "evidence_values",
        "details",
        "created_at",
    ],
    "audit_logs": [
        "id",
        "batch_id",
        "document_id",
        "stage",
        "status",
        "message",
        "payload_ref",
        "created_at",
    ],
}

EXPECTED_FOREIGN_KEYS: dict[str, dict[str, str]] = {
    "documents": {"batch_id": "document_batches"},
    "ai_analyses": {"document_id": "documents"},
    "anomalies": {
        "batch_id": "document_batches",
        "document_id": "documents",
    },
    "audit_logs": {
        "batch_id": "document_batches",
        "document_id": "documents",
    },
    "reports": {"batch_id": "document_batches"},
}

REBUILD_DEPENDENCIES: dict[str, set[str]] = {
    "document_batches": {"documents", "anomalies", "audit_logs", "reports"},
    "documents": {"ai_analyses", "anomalies", "audit_logs"},
}


def _fetch_existing_tables(connection: Any) -> dict[str, str]:
    rows = connection.execute(
        text("SELECT name, sql FROM sqlite_master WHERE type = 'table'"),
    ).mappings()
    return {row["name"]: row["sql"] or "" for row in rows}


def _fetch_columns(connection: Any, table_name: str) -> set[str]:
    rows = connection.execute(text(f"PRAGMA table_info({table_name})")).mappings()
    return {row["name"] for row in rows}


def _fetch_foreign_keys(connection: Any, table_name: str) -> list[dict[str, object]]:
    return list(connection.execute(text(f"PRAGMA foreign_key_list({table_name})")).mappings())


def _has_stale_foreign_keys(connection: Any, table_name: str) -> bool:
    expected_targets = EXPECTED_FOREIGN_KEYS.get(table_name)
    if not expected_targets:
        return False
    for foreign_key in _fetch_foreign_keys(connection, table_name):
        from_column = str(foreign_key["from"])
        expected_table = expected_targets.get(from_column)
        if expected_table and str(foreign_key["table"]) != expected_table:
            return True
    return False


def _should_rebuild_table(connection: Any, table_name: str, create_sql: str) -> bool:
    required_columns = TABLE_REQUIREMENTS.get(table_name)
    if not required_columns:
        return False
    columns = _fetch_columns(connection, table_name)
    if not required_columns.issubset(columns):
        return True
    if "_legacy" in create_sql or "_current" in create_sql:
        return True
    if _has_stale_foreign_keys(connection, table_name):
        return True
    if table_name == "document_batches" and ("completed_with_errors" not in create_sql or "cancelled" not in create_sql):
        return True
    if table_name == "document_batches" and "user_id" in columns:
        return True
    return False


def _expand_rebuild_dependencies(tables_to_rebuild: list[str], existing_tables: dict[str, str]) -> list[str]:
    # Uma FK antiga pode invalidar as tabelas dependentes, por isso o ramo
    # inteiro e reconstruido em ordem estavel antes da copia dos dados.
    expanded = set(tables_to_rebuild)
    pending = list(tables_to_rebuild)

    while pending:
        table_name = pending.pop()
        for dependent_table in REBUILD_DEPENDENCIES.get(table_name, set()):
            if dependent_table in existing_tables and dependent_table not in expanded:
                expanded.add(dependent_table)
                pending.append(dependent_table)

    ordered_tables = [table_name for table_name in TABLE_COPY_COLUMNS if table_name in expanded]
    return ordered_tables


def _rename_legacy_tables(connection: Any, tables_to_rebuild: list[str]) -> dict[str, str]:
    renamed_tables: dict[str, str] = {}
    for table_name in tables_to_rebuild:
        legacy_name = f"{table_name}_legacy"
        counter = 1
        while connection.execute(
            text(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :name",
            ),
            {"name": legacy_name},
        ).first():
            legacy_name = f"{table_name}_legacy_{counter}"
            counter += 1
        connection.execute(text(f"ALTER TABLE {table_name} RENAME TO {legacy_name}"))
        renamed_tables[table_name] = legacy_name
    return renamed_tables


def _copy_table_data(connection: Any, target_table: str, legacy_table: str, columns: list[str]) -> None:
    if target_table == legacy_table:
        return
    available_columns = _fetch_columns(connection, legacy_table)
    common_columns = [column for column in columns if column in available_columns]
    if not common_columns:
        return
    joined = ", ".join(common_columns)
    connection.execute(text(f"INSERT OR IGNORE INTO {target_table} ({joined}) SELECT {joined} FROM {legacy_table}"))


def _list_auxiliary_tables(existing_tables: dict[str, str]) -> dict[str, list[str]]:
    auxiliary_tables: dict[str, list[str]] = {table_name: [] for table_name in TABLE_COPY_COLUMNS}

    for table_name in existing_tables:
        for canonical_name in auxiliary_tables:
            if table_name == f"{canonical_name}_current" or table_name.startswith(f"{canonical_name}_legacy"):
                auxiliary_tables[canonical_name].append(table_name)

    return auxiliary_tables


def _drop_tables(connection: Any, table_names: list[str]) -> None:
    for table_name in table_names:
        connection.execute(text(f"DROP TABLE IF EXISTS {table_name}"))


def _create_schema_from_sql(connection: Any) -> None:
    schema_path = next((candidate for candidate in SCHEMA_CANDIDATES if candidate.exists()), None)
    if schema_path is None:
        raise FileNotFoundError("Nao foi possivel localizar backend/alembic/schema.sql")
    schema_sql = schema_path.read_text(encoding="utf-8")
    raw_statements = [statement.strip() for statement in schema_sql.split(";")]
    for statement in raw_statements:
        normalized = statement.lower()
        if statement and normalized != "pragma foreign_keys = on":
            connection.execute(text(statement))


def _migrate_sqlite_schema() -> None:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys = OFF")
        connection.exec_driver_sql("PRAGMA legacy_alter_table = ON")
        existing_tables = _fetch_existing_tables(connection)
        auxiliary_tables = _list_auxiliary_tables(existing_tables)
        initial_tables_to_rebuild = [
            table_name
            for table_name, create_sql in existing_tables.items()
            if table_name in TABLE_REQUIREMENTS and _should_rebuild_table(connection, table_name, create_sql)
        ]
        tables_to_rebuild = _expand_rebuild_dependencies(initial_tables_to_rebuild, existing_tables)

        renamed_tables = _rename_legacy_tables(connection, tables_to_rebuild) if tables_to_rebuild else {}
        _create_schema_from_sql(connection)
        connection.exec_driver_sql("PRAGMA foreign_keys = OFF")

        temporary_tables_to_drop: list[str] = []
        for table_name, columns in TABLE_COPY_COLUMNS.items():
            # Copia dados de todas as tabelas legadas/localizadas para manter
            # o historico completo do banco reparado, e nao apenas o schema atual.
            source_tables = [*auxiliary_tables.get(table_name, [])]
            renamed_table = renamed_tables.get(table_name)
            if renamed_table:
                source_tables.append(renamed_table)

            unique_sources: list[str] = []
            for source_table in source_tables:
                if source_table not in unique_sources:
                    unique_sources.append(source_table)

            for source_table in unique_sources:
                _copy_table_data(connection, table_name, source_table, columns)
                temporary_tables_to_drop.append(source_table)

        _drop_tables(connection, temporary_tables_to_drop)
        connection.execute(text("DROP TABLE IF EXISTS users"))
        connection.exec_driver_sql("PRAGMA legacy_alter_table = OFF")
        connection.exec_driver_sql("PRAGMA foreign_keys = ON")


def init_db() -> None:
    if settings.database_url.startswith("sqlite:///"):
        _migrate_sqlite_schema()
    Base.metadata.create_all(bind=engine)
