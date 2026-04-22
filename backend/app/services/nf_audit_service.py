from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.repositories import (
    AnalysisRepository,
    AnomalyRepository,
    AuditLogRepository,
    BatchRepository,
    DocumentRepository,
    ReportRepository,
)
from app.schemas.nf_audit import (
    NFAuditAnomalyResponse,
    NFAuditBatchProgressDocument,
    NFAuditBatchProgressResponse,
    NFAuditBatchResponse,
    NFAuditDocumentResponse,
    NFAuditProviderIssueSummary,
    NFAuditProgressSummary,
)
from app.services.file_processor import FileProcessor, PendingUploadDocument
from app.services.report_service import ReportService

FILENAME_PATTERN = re.compile(r"^[\w .-]+$", re.UNICODE)
file_processor = FileProcessor(max_workers=settings.processing_max_workers)
report_service = ReportService()


# Carrega JSON salvo no banco com fallback seguro.
def safe_json_loads(value: str | None, default: object) -> object:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


# Converte o payload textual da auditoria em dicionario.
def _audit_payload_dict(value: str | None) -> dict[str, object]:
    parsed = safe_json_loads(value, {})
    return parsed if isinstance(parsed, dict) else {}


# Converte o lote persistido para o schema basico da API.
def batch_to_response(batch) -> NFAuditBatchResponse:
    return NFAuditBatchResponse(
        batch_id=batch.id,
        batch_name=batch.batch_name,
        status=batch.status,
        total_files=batch.total_files,
        processed_files=batch.processed_files,
        successful_files=batch.successful_files,
        error_files=batch.error_files,
        anomaly_count=batch.anomaly_count,
        started_at=batch.started_at.isoformat() if batch.started_at else None,
        finished_at=batch.finished_at.isoformat() if batch.finished_at else None,
        progress=build_progress_summary(batch=batch, documents=None, latest_stage=None, audit_logs=None),
    )


# Identifica a etapa atual de um documento no pipeline.
def _determine_document_stage(document) -> str:
    if document.status == "pending":
        return "queued"
    if document.status == "error":
        return "failed"
    if document.status == "done":
        return "completed"
    if document.extraction_status in {"queued_llm", "llm_pending", "llm_processing"}:
        return "llm_validation"
    if document.decode_status != "pending" or document.parse_status != "pending":
        return "local_parsing"
    return "processing"


# Consolida a etapa predominante do lote inteiro.
def _determine_batch_stage(*, batch, documents, latest_stage: str | None) -> str:
    if batch.status == "pending":
        return "queued"
    if batch.status == "cancelling":
        return "cancelling"
    if batch.status == "cancelled":
        return "cancelled"
    if batch.status in {"completed", "completed_with_errors"}:
        return "completed"
    if batch.status == "failed":
        return "failed"
    if latest_stage == "rule_eval":
        return "rule_evaluation"
    if latest_stage == "llm_request":
        return "llm_validation"
    if latest_stage == "llm_extract":
        return "llm_validation"
    if latest_stage in {"decode", "parse"}:
        return "local_parsing"
    if documents is not None:
        if any(_determine_document_stage(document) == "llm_validation" for document in documents):
            return "llm_validation"
        if any(_determine_document_stage(document) == "local_parsing" for document in documents):
            return "local_parsing"
    return "processing"


# Monta o resumo operacional usado no acompanhamento do lote.
def build_progress_summary(*, batch, documents, latest_stage: str | None, audit_logs: list | None) -> NFAuditProgressSummary:
    pending_files = max(batch.total_files - batch.processed_files, 0)
    processing_files = 0

    if documents is not None:
        pending_files = sum(1 for document in documents if document.status == "pending")
        processing_files = sum(1 for document in documents if document.status == "processing")

    completed_files = batch.successful_files + batch.error_files
    progress_percent = 0.0
    if batch.total_files > 0:
        progress_percent = round((completed_files / batch.total_files) * 100, 2)

    estimated_remaining_seconds: int | None = None
    throughput_files_per_minute: float | None = None
    average_seconds_per_file: float | None = None
    local_parsed_files = 0
    llm_queued_files = 0
    llm_processing_files = 0
    llm_completed_files = 0
    llm_skipped_files = 0
    llm_request_count = 0
    llm_request_failures = 0
    llm_fallback_count = 0
    average_llm_request_seconds: float | None = None
    provider_issue_map: dict[str, dict[str, object]] = {}

    if documents is not None:
        local_parsed_files = sum(1 for document in documents if document.parse_status != "pending")
        llm_queued_files = sum(1 for document in documents if document.extraction_status == "queued_llm")
        llm_processing_files = sum(1 for document in documents if document.extraction_status == "llm_processing")
        llm_skipped_files = sum(1 for document in documents if document.extraction_status == "local_ready")

    if audit_logs is not None:
        llm_completed_document_ids: set[str] = set()
        llm_skipped_document_ids: set[str] = set()
        for log in audit_logs:
            if log.stage != "llm_extract" or not log.document_id:
                continue
            payload = _audit_payload_dict(log.payload_ref)
            provider = payload.get("provider")
            if provider == "local-parser":
                llm_skipped_document_ids.add(log.document_id)
            else:
                llm_completed_document_ids.add(log.document_id)
        llm_completed_files = len(llm_completed_document_ids)
        llm_skipped_files = max(llm_skipped_files, len(llm_skipped_document_ids))
        llm_request_logs = [log for log in audit_logs if log.stage == "llm_request"]
        llm_request_count = sum(1 for log in llm_request_logs if log.status == "success")
        llm_request_failures = sum(1 for log in llm_request_logs if log.status == "failed")
        llm_durations_ms: list[int] = []
        for log in llm_request_logs:
            payload = _audit_payload_dict(log.payload_ref)
            if log.status == "failed":
                error_code = str(payload.get("error_code") or "").strip()
                if error_code:
                    issue = provider_issue_map.setdefault(
                        error_code,
                        {
                            "count": 0,
                            "retryable": bool(payload.get("retryable")),
                            "user_message": str(payload.get("user_message") or "A validacao por IA teve uma falha externa."),
                            "provider": str(payload.get("provider") or "") or None,
                            "http_status": payload.get("http_status") if isinstance(payload.get("http_status"), int) else None,
                        },
                    )
                    issue["count"] = int(issue["count"]) + 1
                    issue["retryable"] = bool(payload.get("retryable"))
                    if payload.get("user_message"):
                        issue["user_message"] = str(payload["user_message"])
                    if payload.get("provider"):
                        issue["provider"] = str(payload["provider"])
                    if isinstance(payload.get("http_status"), int):
                        issue["http_status"] = payload["http_status"]
            if payload.get("fallback_used") is True:
                llm_fallback_count += 1
            duration_ms = payload.get("duration_ms")
            if log.status == "success" and isinstance(duration_ms, int):
                llm_durations_ms.append(duration_ms)
        if llm_durations_ms:
            average_llm_request_seconds = round((sum(llm_durations_ms) / len(llm_durations_ms)) / 1000, 2)
    if (
        batch.started_at
        and not batch.finished_at
        and batch.processed_files > 0
    ):
        started_at = batch.started_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        elapsed_seconds = max(int((datetime.now(timezone.utc) - started_at).total_seconds()), 1)
        avg_seconds_per_file = elapsed_seconds / batch.processed_files
        average_seconds_per_file = round(avg_seconds_per_file, 2)
        throughput_files_per_minute = round((batch.processed_files / elapsed_seconds) * 60, 2)
        if batch.total_files > batch.processed_files:
            estimated_remaining_seconds = max(int(avg_seconds_per_file * (batch.total_files - batch.processed_files)), 1)
    elif batch.started_at and batch.finished_at and batch.processed_files > 0:
        started_at = batch.started_at
        finished_at = batch.finished_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        if finished_at.tzinfo is None:
            finished_at = finished_at.replace(tzinfo=timezone.utc)
        elapsed_seconds = max(int((finished_at - started_at).total_seconds()), 1)
        average_seconds_per_file = round(elapsed_seconds / batch.processed_files, 2)
        throughput_files_per_minute = round((batch.processed_files / elapsed_seconds) * 60, 2)

    return NFAuditProgressSummary(
        pending_files=pending_files,
        processing_files=processing_files,
        completed_files=completed_files,
        progress_percent=progress_percent,
        estimated_remaining_seconds=estimated_remaining_seconds,
        current_stage=_determine_batch_stage(batch=batch, documents=documents, latest_stage=latest_stage),
        throughput_files_per_minute=throughput_files_per_minute,
        average_seconds_per_file=average_seconds_per_file,
        local_parsed_files=local_parsed_files,
        llm_queued_files=llm_queued_files,
        llm_processing_files=llm_processing_files,
        llm_completed_files=llm_completed_files,
        llm_skipped_files=llm_skipped_files,
        llm_request_count=llm_request_count,
        llm_request_failures=llm_request_failures,
        llm_fallback_count=llm_fallback_count,
        average_llm_request_seconds=average_llm_request_seconds,
        provider_issues=[
            NFAuditProviderIssueSummary(
                error_code=error_code,
                count=int(issue["count"]),
                retryable=bool(issue["retryable"]),
                user_message=str(issue["user_message"]),
                provider=str(issue["provider"]) if issue["provider"] is not None else None,
                http_status=issue["http_status"] if isinstance(issue["http_status"], int) else None,
            )
            for error_code, issue in sorted(
                provider_issue_map.items(),
                key=lambda item: (-int(item[1]["count"]), item[0]),
            )
        ],
    )


# Converte a anomalia persistida para o payload de resposta.
def anomaly_to_response(anomaly, file_name: str) -> NFAuditAnomalyResponse:
    evidence_fields = safe_json_loads(anomaly.evidence_fields, [])
    evidence_values = safe_json_loads(anomaly.evidence_values, {})
    return NFAuditAnomalyResponse(
        id=anomaly.id,
        document_id=anomaly.document_id,
        file_name=file_name,
        rule_code=anomaly.rule_code,
        rule_name=anomaly.rule_name,
        severity=anomaly.severity,
        confidence=anomaly.confidence,
        evidence_fields=evidence_fields if isinstance(evidence_fields, list) else [],
        evidence_values=evidence_values if isinstance(evidence_values, dict) else {},
        details=anomaly.details,
        created_at=anomaly.created_at.isoformat(),
    )


# Converte documento, analise e anomalias para o schema de detalhe.
def document_to_response(document, analysis, anomalies) -> NFAuditDocumentResponse:
    extracted_data = safe_json_loads(document.extracted_data, {})
    missing_fields = safe_json_loads(document.missing_fields, [])
    truncated_fields = safe_json_loads(document.truncated_fields, [])
    attempted_models = safe_json_loads(analysis.attempted_models if analysis else None, [])
    return NFAuditDocumentResponse(
        id=document.id,
        file_name=document.file_name,
        file_path=document.file_path,
        source_type=document.source_type,
        mime_type=document.mime_type,
        file_size_bytes=document.file_size_bytes,
        status=document.status,
        decode_status=document.decode_status,
        parse_status=document.parse_status,
        extraction_status=document.extraction_status,
        error_code=document.error_code,
        error_message=document.error_message,
        processed_at=document.processed_at.isoformat() if document.processed_at else None,
        extracted_data=extracted_data if isinstance(extracted_data, dict) else {},
        missing_fields=missing_fields if isinstance(missing_fields, list) else [],
        truncated_fields=truncated_fields if isinstance(truncated_fields, list) else [],
        anomalies=anomalies,
        analysis_summary=analysis.summary if analysis else None,
        llm_provider=analysis.provider if analysis else None,
        llm_model=analysis.model if analysis else None,
        llm_requested_model=analysis.requested_model if analysis else None,
        llm_fallback_used=(analysis.fallback_used == "true") if analysis and analysis.fallback_used is not None else None,
        llm_attempted_models=attempted_models if isinstance(attempted_models, list) else [],
        prompt_version=analysis.prompt_version if analysis else None,
    )


# Monta as linhas do CSV principal de resultados.
def build_result_rows(documents, analyses_by_document, anomalies_by_document) -> list[dict[str, object]]:
    severity_order = {"high": 3, "medium": 2, "low": 1}
    rows: list[dict[str, object]] = []
    for document in documents:
        extracted_data = safe_json_loads(document.extracted_data, {})
        analysis = analyses_by_document.get(document.id)
        anomalies = anomalies_by_document.get(document.id, [])
        anomaly_codes = [item.rule_code for item in anomalies]
        max_severity = ""
        if anomalies:
            max_severity = max(anomalies, key=lambda item: severity_order.get(item.severity, 0)).severity
        rows.append(
            {
                "batch_id": document.batch_id,
                "document_id": document.id,
                "file_name": document.file_name,
                "status": document.status,
                "decode_status": document.decode_status,
                "parse_status": document.parse_status,
                "extraction_status": document.extraction_status,
                "has_anomaly": 1 if anomalies else 0,
                "has_encoding_error": 1 if document.decode_status == "failed" or document.error_code == "invalid_encoding" else 0,
                "has_encoding_recovery": 1 if document.decode_status == "recovered" else 0,
                "error_code": document.error_code or "",
                "error_message": document.error_message or "",
                "tipo_documento": extracted_data.get("tipo_documento", ""),
                "numero_documento": extracted_data.get("numero_documento", ""),
                "data_emissao": extracted_data.get("data_emissao", ""),
                "fornecedor": extracted_data.get("fornecedor", ""),
                "cnpj_fornecedor": extracted_data.get("cnpj_fornecedor", ""),
                "descricao_servico": extracted_data.get("descricao_servico", ""),
                "valor_bruto": extracted_data.get("valor_bruto", ""),
                "data_pagamento": extracted_data.get("data_pagamento", ""),
                "data_emissao_nf": extracted_data.get("data_emissao_nf", ""),
                "aprovado_por": extracted_data.get("aprovado_por", ""),
                "banco_destino": extracted_data.get("banco_destino", ""),
                "status_nf": extracted_data.get("status", ""),
                "hash_verificacao": extracted_data.get("hash_verificacao", ""),
                "anomaly_codes": "|".join(anomaly_codes),
                "anomaly_count": len(anomalies),
                "max_severity": max_severity,
                "prompt_version": analysis.prompt_version if analysis else "",
                "analysis_summary": analysis.summary if analysis else "",
                "classification": analysis.classification if analysis else "",
                "risk_score": analysis.risk_score if analysis else "",
                "confidence_overall": analysis.confidence_overall if analysis else "",
                "llm_provider": analysis.provider if analysis else "",
                "llm_model": analysis.model if analysis else "",
                "llm_requested_model": analysis.requested_model if analysis else "",
                "llm_fallback_used": analysis.fallback_used if analysis else "",
                "llm_attempted_models": analysis.attempted_models if analysis else "",
                "processed_at": document.processed_at.isoformat() if document.processed_at else "",
            }
        )
    return rows


# Monta as linhas do CSV separado de auditoria.
def build_audit_rows(*, batch_id: str, audit_logs, documents_by_id: dict[str, object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in audit_logs:
        payload = _audit_payload_dict(item.payload_ref)
        document = documents_by_id.get(item.document_id or "")
        verification = str(payload.get("rule_code") or item.stage)
        result = str(payload.get("extraction_status") or item.status)
        rows.append(
            {
                "batch_id": batch_id,
                "audit_log_id": item.id,
                "document_id": item.document_id or "",
                "file_name": document.file_name if document is not None else "",
                "stage": item.stage,
                "status": item.status,
                "message": item.message,
                "verification": verification,
                "result": result,
                "rule_code": payload.get("rule_code", ""),
                "confidence": payload.get("confidence", ""),
                "evidence_fields": payload.get("evidence_fields", []),
                "evidence_values": payload.get("evidence_values", {}),
                "provider": payload.get("provider", ""),
                "requested_model": payload.get("requested_model", ""),
                "effective_model": payload.get("effective_model", ""),
                "fallback_used": payload.get("fallback_used", ""),
                "strategy": payload.get("strategy", ""),
                "error_code": payload.get("error_code", ""),
                "http_status": payload.get("http_status", ""),
                "retryable": payload.get("retryable", ""),
                "user_message": payload.get("user_message", ""),
                "technical_message": payload.get("technical_message", ""),
                "duration_ms": payload.get("duration_ms", ""),
                "payload_ref": item.payload_ref or "",
                "created_at": item.created_at.isoformat(),
            }
        )
    return rows


# Monta as linhas do CSV separado de anomalias.
def build_anomaly_rows(*, batch_id: str, anomalies, documents_by_id: dict[str, object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for anomaly in anomalies:
        document = documents_by_id.get(anomaly.document_id)
        extracted_data = safe_json_loads(document.extracted_data if document is not None else None, {})
        rows.append(
            {
                "batch_id": batch_id,
                "anomaly_id": anomaly.id,
                "document_id": anomaly.document_id,
                "file_name": document.file_name if document is not None else "",
                "fornecedor": extracted_data.get("fornecedor", "") if isinstance(extracted_data, dict) else "",
                "cnpj_fornecedor": extracted_data.get("cnpj_fornecedor", "") if isinstance(extracted_data, dict) else "",
                "rule_code": anomaly.rule_code,
                "rule_name": anomaly.rule_name,
                "severity": anomaly.severity,
                "confidence": anomaly.confidence,
                "evidence_fields": safe_json_loads(anomaly.evidence_fields, []),
                "evidence_values": safe_json_loads(anomaly.evidence_values, {}),
                "details": anomaly.details or "",
                "created_at": anomaly.created_at.isoformat(),
            }
        )
    return rows


class NFAuditService:
    # Inicializa a camada de orquestracao da API de auditoria.
    def __init__(self, db: Session) -> None:
        self.db = db
        self.batch_repo = BatchRepository(db)
        self.document_repo = DocumentRepository(db)
        self.analysis_repo = AnalysisRepository(db)
        self.anomaly_repo = AnomalyRepository(db)
        self.report_repo = ReportRepository(db)
        self.audit_log_repo = AuditLogRepository(db)

    # Recebe os arquivos, valida o lote e agenda o processamento.
    async def upload_batch(self, *, files: list[UploadFile], batch_name: str | None):
        if not files:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Envie ao menos um arquivo.")

        pending_documents: list[dict[str, object]] = []
        total_size = 0

        for upload in files:
            upload_name = self._validate_file_name(upload.filename or "")
            payload = await upload.read()
            if not payload:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Arquivo vazio nao e permitido.")
            if len(payload) > settings.upload_max_file_size_bytes:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Arquivo excede o tamanho maximo permitido.")
            total_size += len(payload)
            if total_size > settings.upload_max_total_size_bytes:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Lote excede o tamanho total permitido.")

            lower_name = upload_name.lower()
            if lower_name.endswith(".zip"):
                total_size -= len(payload)
                pending_documents.extend(self._extract_zip_entries(upload_name=upload_name, payload=payload, total_size_ref=[total_size]))
                total_size = sum(int(item["file_size_bytes"]) for item in pending_documents)
            elif lower_name.endswith(".txt"):
                pending_documents.append(
                    {
                        "file_name": upload_name,
                        "file_path": upload_name,
                        "source_type": "txt",
                        "mime_type": upload.content_type or "text/plain",
                        "file_size_bytes": len(payload),
                        "content": payload,
                    }
                )
            else:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Somente arquivos .txt ou .zip sao aceitos.")

        if not pending_documents:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nenhum arquivo .txt valido foi encontrado.")

        created_batch = self.batch_repo.create(
            batch_name=batch_name or f"Lote NF {len(pending_documents)} arquivos",
            total_files=len(pending_documents),
        )

        scheduled_documents: list[PendingUploadDocument] = []
        for pending in pending_documents:
            document = self.document_repo.create(
                batch_id=created_batch.id,
                file_name=str(pending["file_name"]),
                file_path=str(pending["file_path"]),
                source_type=str(pending["source_type"]),
                mime_type=pending["mime_type"],
                file_size_bytes=int(pending["file_size_bytes"]),
                decode_status="pending",
                parse_status="pending",
                extraction_status="pending",
                status="pending",
            )
            scheduled_documents.append(
                PendingUploadDocument(
                    document_id=document.id,
                    file_name=document.file_name,
                    file_path=document.file_path,
                    source_type=document.source_type,
                    mime_type=document.mime_type,
                    file_size_bytes=document.file_size_bytes,
                    content=bytes(pending["content"]),
                )
            )

        created_batch = self.batch_repo.mark_processing_started(created_batch)
        file_processor.schedule_batch(created_batch.id, scheduled_documents)
        return created_batch

    # Busca um lote e padroniza o erro 404.
    def get_batch(self, *, batch_id: str):
        batch = self.batch_repo.get_by_id(batch_id)
        if not batch:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lote nao encontrado.")
        return batch

    # Solicita o cancelamento de um lote ainda em andamento.
    def cancel_batch(self, *, batch_id: str):
        batch = self.get_batch(batch_id=batch_id)
        if batch.status in {"completed", "completed_with_errors", "failed", "cancelled"}:
            return batch

        if batch.status != "cancelling":
            batch = self.batch_repo.mark_cancelling(batch)
            self.audit_log_repo.create(
                batch_id=batch_id,
                stage="processing",
                status="cancelling",
                message="Cancelamento solicitado pelo usuario.",
            )

        cancel_requested = file_processor.cancel_batch(batch_id)
        if not cancel_requested:
            file_processor.finalize_cancelled_batch(
                batch_id=batch_id,
                message="Lote cancelado sem worker ativo; estado reconciliado.",
            )
        refreshed_batch = self.batch_repo.get_by_id(batch_id)
        return refreshed_batch or batch

    # Lista os documentos do lote com filtros e paginacao.
    def list_documents(
        self,
        *,
        batch_id: str,
        search: str | None,
        status: str | None,
        extraction_status: str | None,
        decode_status: str | None,
        has_anomaly: bool | None,
        skip: int,
        limit: int,
    ):
        self.get_batch(batch_id=batch_id)
        documents = self.document_repo.list_by_batch_id(
            batch_id,
            search=search,
            status=status,
            extraction_status=extraction_status,
            decode_status=decode_status,
            has_anomaly=has_anomaly,
            skip=skip,
            limit=limit,
        )
        total = self.document_repo.count_by_batch_id(
            batch_id,
            search=search,
            status=status,
            extraction_status=extraction_status,
            decode_status=decode_status,
            has_anomaly=has_anomaly,
        )
        return documents, total

    # Retorna o estado consolidado do lote para o dashboard.
    def get_batch_progress(self, *, batch_id: str) -> NFAuditBatchProgressResponse:
        batch = self.get_batch(batch_id=batch_id)
        documents = self.document_repo.list_all_by_batch_id(batch_id)
        audit_logs = self.audit_log_repo.list_by_batch_id(batch_id)
        return NFAuditBatchProgressResponse(
            batch_id=batch.id,
            batch_name=batch.batch_name,
            status=batch.status,
            total_files=batch.total_files,
            processed_files=batch.processed_files,
            successful_files=batch.successful_files,
            error_files=batch.error_files,
            anomaly_count=batch.anomaly_count,
            started_at=batch.started_at.isoformat() if batch.started_at else None,
            finished_at=batch.finished_at.isoformat() if batch.finished_at else None,
            progress=build_progress_summary(
                batch=batch,
                documents=documents,
                latest_stage=self._latest_batch_stage(batch_id),
                audit_logs=audit_logs,
            ),
            documents=[
                NFAuditBatchProgressDocument(
                    document_id=document.id,
                    file_name=document.file_name,
                    status=document.status,
                    current_stage=_determine_document_stage(document),
                    decode_status=document.decode_status,
                    parse_status=document.parse_status,
                    extraction_status=document.extraction_status,
                    error_code=document.error_code,
                    processed_at=document.processed_at.isoformat() if document.processed_at else None,
                )
                for document in documents
            ],
        )

    # Lista as anomalias do lote com filtros e paginacao.
    def list_anomalies(
        self,
        *,
        batch_id: str,
        rule_code: str | None,
        severity: str | None,
        search: str | None,
        skip: int,
        limit: int,
    ):
        self.get_batch(batch_id=batch_id)
        documents_by_id = {item.id: item.file_name for item in self.document_repo.list_all_by_batch_id(batch_id)}
        anomalies = self.anomaly_repo.list_by_batch_id(
            batch_id,
            rule_code=rule_code,
            severity=severity,
            search=search,
            skip=skip,
            limit=limit,
        )
        total = self.anomaly_repo.count_by_batch_id(
            batch_id,
            rule_code=rule_code,
            severity=severity,
            search=search,
        )
        return anomalies, documents_by_id, total

    # Exporta o CSV principal de resultados do lote.
    def export_results(self, *, batch_id: str):
        self.get_batch(batch_id=batch_id)
        documents = self.document_repo.list_all_by_batch_id(batch_id)
        analyses_by_document = {document.id: self.analysis_repo.get_by_document_id(document.id) for document in documents}
        anomalies = self.anomaly_repo.list_by_batch_id(batch_id, skip=0, limit=100000)
        anomalies_by_document: dict[str, list] = {}
        for anomaly in anomalies:
            anomalies_by_document.setdefault(anomaly.document_id, []).append(anomaly)

        csv_path = report_service.generate_results_csv(
            batch_id=batch_id,
            rows=build_result_rows(documents, analyses_by_document, anomalies_by_document),
        )
        report = self.report_repo.create(batch_id=batch_id, csv_path=csv_path, report_type="results")
        self.audit_log_repo.create(batch_id=batch_id, stage="export", status="done", message="CSV principal exportado.", payload_ref=csv_path)
        return report

    # Exporta o CSV de auditoria do lote.
    def export_audit(self, *, batch_id: str):
        self.get_batch(batch_id=batch_id)
        documents_by_id = {item.id: item for item in self.document_repo.list_all_by_batch_id(batch_id)}
        audit_rows = build_audit_rows(
            batch_id=batch_id,
            audit_logs=self.audit_log_repo.list_by_batch_id(batch_id),
            documents_by_id=documents_by_id,
        )

        csv_path = report_service.generate_audit_csv(batch_id=batch_id, rows=audit_rows)
        report = self.report_repo.create(batch_id=batch_id, csv_path=csv_path, report_type="audit")
        self.audit_log_repo.create(batch_id=batch_id, stage="export", status="done", message="CSV de auditoria exportado.", payload_ref=csv_path)
        return report

    # Exporta o CSV de anomalias do lote.
    def export_anomalies(self, *, batch_id: str):
        self.get_batch(batch_id=batch_id)
        documents_by_id = {item.id: item for item in self.document_repo.list_all_by_batch_id(batch_id)}
        anomalies = self.anomaly_repo.list_by_batch_id(batch_id, skip=0, limit=100000)
        csv_path = report_service.generate_anomalies_csv(
            batch_id=batch_id,
            rows=build_anomaly_rows(
                batch_id=batch_id,
                anomalies=anomalies,
                documents_by_id=documents_by_id,
            ),
        )
        report = self.report_repo.create(batch_id=batch_id, csv_path=csv_path, report_type="anomalies")
        self.audit_log_repo.create(batch_id=batch_id, stage="export", status="done", message="CSV de anomalias exportado.", payload_ref=csv_path)
        return report

    # Resolve o arquivo fisico de um relatorio ja gerado.
    def get_report_download(self, *, report_id: str):
        report = self.report_repo.get_by_id(report_id)
        if not report:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Relatorio nao encontrado.")
        report_path = Path(report.csv_path)
        if not report_path.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Arquivo de relatorio nao encontrado.")
        return report, report_path

    @staticmethod
    # Valida nomes de arquivo aceitos pelo upload.
    def _validate_file_name(file_name: str) -> str:
        candidate = PurePosixPath(file_name).name.strip()
        if not candidate or candidate in {".", ".."} or not FILENAME_PATTERN.fullmatch(candidate):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nome de arquivo invalido.")
        return candidate

    # Extrai os .txt de um ZIP validando nomes e limites.
    def _extract_zip_entries(self, *, upload_name: str, payload: bytes, total_size_ref: list[int]) -> list[dict[str, object]]:
        extracted: list[dict[str, object]] = []
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as zip_file:
                for info in zip_file.infolist():
                    if info.is_dir():
                        continue
                    entry_name = self._validate_file_name(info.filename)
                    if not entry_name.lower().endswith(".txt"):
                        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ZIP deve conter apenas arquivos .txt.")
                    if info.file_size > settings.upload_max_file_size_bytes:
                        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Arquivo dentro do ZIP excede o tamanho permitido.")
                    entry_content = zip_file.read(info.filename)
                    total_size_ref[0] += len(entry_content)
                    if total_size_ref[0] > settings.upload_max_total_size_bytes:
                        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Lote excede o tamanho total permitido.")
                    extracted.append(
                        {
                            "file_name": entry_name,
                            "file_path": f"{upload_name}::{entry_name}",
                            "source_type": "zip_entry",
                            "mime_type": "text/plain",
                            "file_size_bytes": len(entry_content),
                            "content": entry_content,
                        }
                    )
        except zipfile.BadZipFile as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Arquivo ZIP invalido.") from exc
        return extracted

    # Descobre a ultima etapa registrada para o lote.
    def _latest_batch_stage(self, batch_id: str) -> str | None:
        audit_logs = self.audit_log_repo.list_by_batch_id(batch_id)
        if not audit_logs:
            return None
        return audit_logs[-1].stage
