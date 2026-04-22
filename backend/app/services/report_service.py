from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path


class ReportService:
    # Garante a pasta onde os CSVs exportados serao gravados.
    def __init__(self) -> None:
        self.reports_dir = Path(__file__).resolve().parents[2] / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    # Gera o CSV principal com um registro por documento.
    def generate_results_csv(self, batch_id: str, rows: list[dict[str, object]]) -> str:
        fieldnames = [
            "batch_id",
            "document_id",
            "file_name",
            "status",
            "decode_status",
            "parse_status",
            "extraction_status",
            "has_anomaly",
            "has_encoding_error",
            "has_encoding_recovery",
            "error_code",
            "error_message",
            "tipo_documento",
            "numero_documento",
            "data_emissao",
            "fornecedor",
            "cnpj_fornecedor",
            "descricao_servico",
            "valor_bruto",
            "data_pagamento",
            "data_emissao_nf",
            "aprovado_por",
            "banco_destino",
            "status_nf",
            "hash_verificacao",
            "anomaly_codes",
            "anomaly_count",
            "max_severity",
            "prompt_version",
            "analysis_summary",
            "classification",
            "risk_score",
            "confidence_overall",
            "llm_provider",
            "llm_model",
            "llm_requested_model",
            "llm_fallback_used",
            "llm_attempted_models",
            "processed_at",
        ]
        return self._generate_csv(batch_id=batch_id, rows=rows, report_type="results", fieldnames=fieldnames)

    # Gera o CSV separado do log de auditoria.
    def generate_audit_csv(self, batch_id: str, rows: list[dict[str, object]]) -> str:
        fieldnames = [
            "batch_id",
            "audit_log_id",
            "document_id",
            "file_name",
            "stage",
            "status",
            "message",
            "verification",
            "result",
            "rule_code",
            "confidence",
            "evidence_fields",
            "evidence_values",
            "provider",
            "requested_model",
            "effective_model",
            "fallback_used",
            "strategy",
            "error_code",
            "http_status",
            "retryable",
            "user_message",
            "technical_message",
            "duration_ms",
            "payload_ref",
            "created_at",
        ]
        return self._generate_csv(batch_id=batch_id, rows=rows, report_type="audit", fieldnames=fieldnames)

    # Gera o CSV separado das anomalias detectadas.
    def generate_anomalies_csv(self, batch_id: str, rows: list[dict[str, object]]) -> str:
        fieldnames = [
            "batch_id",
            "anomaly_id",
            "document_id",
            "file_name",
            "fornecedor",
            "cnpj_fornecedor",
            "rule_code",
            "rule_name",
            "severity",
            "confidence",
            "evidence_fields",
            "evidence_values",
            "details",
            "created_at",
        ]
        return self._generate_csv(batch_id=batch_id, rows=rows, report_type="anomalies", fieldnames=fieldnames)

    # Cria o arquivo CSV e normaliza as linhas antes da escrita.
    def _generate_csv(
        self,
        *,
        batch_id: str,
        rows: list[dict[str, object]],
        report_type: str,
        fieldnames: list[str],
    ) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        csv_path = self.reports_dir / f"batch_{batch_id}_{report_type}_{timestamp}.csv"

        with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                normalized_row = {
                    field: self._normalize_value_for_csv(row.get(field, ""))
                    for field in fieldnames
                }
                writer.writerow(normalized_row)

        return str(csv_path)

    # Converte listas e dicionarios para texto seguro em CSV.
    def _normalize_value_for_csv(self, value: object) -> object:
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return value
