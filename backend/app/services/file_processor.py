from __future__ import annotations

import json
import logging
import re
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from threading import Event, Lock
from typing import Any

from app.db.repositories import (
    AnalysisRepository,
    AnomalyRepository,
    AuditLogRepository,
    BatchRepository,
    DocumentRepository,
)
from app.db.session import SessionLocal
from app.services.anomaly_service import AnomalyService
from app.services.llm_service_factory import LLMRouterService
from app.services.openrouter_service import LLMProcessingCancelled

logger = logging.getLogger("app.nf_audit.processor")

FIELD_ALIASES = {
    "TIPO_DOCUMENTO": "tipo_documento",
    "NUMERO_DOCUMENTO": "numero_documento",
    "DATA_EMISSAO": "data_emissao",
    "FORNECEDOR": "fornecedor",
    "CNPJ_FORNECEDOR": "cnpj_fornecedor",
    "DESCRICAO_SERVICO": "descricao_servico",
    "VALOR_BRUTO": "valor_bruto",
    "DATA_PAGAMENTO": "data_pagamento",
    "DATA_EMISSAO_NF": "data_emissao_nf",
    "APROVADO_POR": "aprovado_por",
    "BANCO_DESTINO": "banco_destino",
    "STATUS": "status",
    "HASH_VERIFICACAO": "hash_verificacao",
}

EXPECTED_FIELDS = list(FIELD_ALIASES.values())
REQUIRED_FIELDS = {
    "tipo_documento",
    "numero_documento",
    "fornecedor",
    "cnpj_fornecedor",
    "valor_bruto",
    "status",
    "hash_verificacao",
}

NON_FATAL_LLM_STATUSES = {"failed"}


@dataclass(slots=True)
class PendingUploadDocument:
    document_id: str
    file_name: str
    file_path: str
    source_type: str
    mime_type: str | None
    file_size_bytes: int
    content: bytes


class FileProcessor:
    # Inicializa o processador em background e os servicos auxiliares.
    def __init__(self, max_workers: int = 10) -> None:
        self.max_workers = max_workers
        self.executor = self._create_executor()
        self.llm_service = LLMRouterService()
        self.anomaly_service = AnomalyService()
        self._tracked_futures: dict[str, Future] = {}
        self._cancel_events: dict[str, Event] = {}
        self._tracking_lock = Lock()

    # Agenda um lote para processamento assincorno em thread separada.
    def schedule_batch(self, batch_id: str, pending_documents: list[PendingUploadDocument]) -> None:
        with self._tracking_lock:
            if getattr(self.executor, "_shutdown", False):
                self.executor = self._create_executor()
        cancel_event = Event()
        future = self.executor.submit(self._process_batch, batch_id, pending_documents, cancel_event)
        with self._tracking_lock:
            self._cancel_events[batch_id] = cancel_event
            self._tracked_futures[batch_id] = future
        future.add_done_callback(lambda done: self._log_background_result(batch_id, done))

    # Consolida o resultado final da thread e limpa o rastreamento do lote.
    def _log_background_result(self, batch_id: str, future) -> None:
        try:
            future.result()
        except CancelledError:
            self._finalize_cancelled_batch(batch_id=batch_id, message="Lote cancelado antes de iniciar o processamento.")
        except Exception:
            logger.exception("batch_processing_failed batch_id=%s", batch_id)
        finally:
            self._cleanup_tracking(batch_id)

    # Sinaliza o cancelamento de um lote em execucao.
    def cancel_batch(self, batch_id: str) -> bool:
        with self._tracking_lock:
            cancel_event = self._cancel_events.get(batch_id)
            future = self._tracked_futures.get(batch_id)

        if cancel_event is None:
            return False

        cancel_event.set()
        if future is not None and future.cancel():
            self._finalize_cancelled_batch(batch_id=batch_id, message="Lote cancelado antes de iniciar a thread de processamento.")
        return True

    # Encerra o executor e fecha os clientes dos provedores de IA.
    def shutdown(self) -> None:
        with self._tracking_lock:
            tracked_batch_ids = list(self._cancel_events.keys())
            for cancel_event in self._cancel_events.values():
                cancel_event.set()
        for batch_id in tracked_batch_ids:
            self._finalize_cancelled_batch(
                batch_id=batch_id,
                message="Processamento interrompido durante o encerramento da aplicacao.",
                allow_final_states=True,
            )
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.llm_service.close()

    # Processa todas as etapas do lote: parse, IA, regras e fechamento.
    def _process_batch(self, batch_id: str, pending_documents: list[PendingUploadDocument], cancel_event: Event) -> None:
        db = SessionLocal()
        batch_repo = BatchRepository(db)
        document_repo = DocumentRepository(db)
        analysis_repo = AnalysisRepository(db)
        anomaly_repo = AnomalyRepository(db)
        audit_log_repo = AuditLogRepository(db)

        batch = batch_repo.get_by_id(batch_id)
        if batch is None:
            db.close()
            return

        try:
            if self._is_cancel_requested(cancel_event):
                self._cancel_current_batch(
                    batch_id=batch_id,
                    batch=batch,
                    batch_repo=batch_repo,
                    document_repo=document_repo,
                    audit_log_repo=audit_log_repo,
                    message="Lote cancelado antes do inicio do processamento.",
                )
                return
            batch_repo.mark_processing_started(batch)
            audit_log_repo.create(
                batch_id=batch_id,
                stage="upload",
                status="accepted",
                message="Lote recebido e enfileirado para processamento.",
            )

            current_chunk: list[dict[str, object]] = []
            for pending in pending_documents:
                if self._is_cancel_requested(cancel_event):
                    self._cancel_current_batch(
                        batch_id=batch_id,
                        batch=batch,
                        batch_repo=batch_repo,
                        document_repo=document_repo,
                        audit_log_repo=audit_log_repo,
                        message="Lote cancelado durante a etapa de leitura dos arquivos.",
                    )
                    return
                document = document_repo.get_by_id(pending.document_id)
                if document is None:
                    continue

                document_repo.update(document, status="processing")
                result = self._process_single(pending)
                document_repo.update(
                    document,
                    raw_text=result["raw_text"],
                    extracted_text=result["raw_text"],
                    extracted_data=result["extracted_data"],
                    missing_fields=result["missing_fields"],
                    truncated_fields=result["truncated_fields"],
                    decode_status=result["decode_status"],
                    parse_status=result["parse_status"],
                    extraction_status="parsed",
                    error_code=result["error_code"],
                    error_message=result["error_message"],
                    status="processing",
                )
                audit_log_repo.create(
                    batch_id=batch_id,
                    document_id=document.id,
                    stage="decode",
                    status=result["decode_status"],
                    message=result["decode_message"],
                )
                audit_log_repo.create(
                    batch_id=batch_id,
                    document_id=document.id,
                    stage="parse",
                    status=result["parse_status"],
                    message=result["parse_message"],
                    payload_ref=json.dumps(result["missing_fields"], ensure_ascii=False),
                )
                current_chunk.append(
                    {
                        "document_id": document.id,
                        "result": result,
                    }
                )
                if len(current_chunk) >= self._processing_chunk_size(len(pending_documents)):
                    self._finalize_document_chunk(
                        batch_id=batch_id,
                        batch=batch,
                        items=current_chunk,
                        total_documents=len(pending_documents),
                        batch_repo=batch_repo,
                        document_repo=document_repo,
                        analysis_repo=analysis_repo,
                        audit_log_repo=audit_log_repo,
                        cancel_event=cancel_event,
                    )
                    current_chunk = []

            if current_chunk:
                self._finalize_document_chunk(
                    batch_id=batch_id,
                    batch=batch,
                    items=current_chunk,
                    total_documents=len(pending_documents),
                    batch_repo=batch_repo,
                    document_repo=document_repo,
                    analysis_repo=analysis_repo,
                    audit_log_repo=audit_log_repo,
                    cancel_event=cancel_event,
                )

            current_documents = document_repo.list_all_by_batch_id(batch_id)
            anomaly_repo.delete_by_batch_id(batch_id)
            if self._is_cancel_requested(cancel_event):
                self._cancel_current_batch(
                    batch_id=batch_id,
                    batch=batch,
                    batch_repo=batch_repo,
                    document_repo=document_repo,
                    audit_log_repo=audit_log_repo,
                    message="Lote cancelado antes da avaliacao das anomalias.",
                )
                return
            anomalies = self.anomaly_service.evaluate(batch_id=batch_id, batch_documents=current_documents)
            anomaly_repo.create_many(batch_id, anomalies)

            for anomaly in anomalies:
                audit_log_repo.create(
                    batch_id=batch_id,
                    document_id=str(anomaly["document_id"]),
                    stage="rule_eval",
                    status="flagged",
                    message=str(anomaly["rule_name"]),
                    payload_ref=json.dumps(
                        {
                            "rule_code": anomaly["rule_code"],
                            "confidence": anomaly["confidence"],
                            "evidence_values": anomaly["evidence_values"],
                        },
                        ensure_ascii=False,
                    ),
                )

            refreshed_documents = document_repo.list_all_by_batch_id(batch_id)
            processed_files = len(refreshed_documents)
            successful_files = sum(1 for document in refreshed_documents if document.status == "done")
            error_files = sum(1 for document in refreshed_documents if document.status == "error")
            anomaly_count = len(anomalies)
            final_status = "completed"
            if error_files and successful_files:
                final_status = "completed_with_errors"
            elif error_files and not successful_files:
                final_status = "failed"

            batch_repo.finalize(
                batch,
                processed_files=processed_files,
                successful_files=successful_files,
                error_files=error_files,
                anomaly_count=anomaly_count,
                status=final_status,
            )
        except LLMProcessingCancelled:
            self._cancel_current_batch(
                batch_id=batch_id,
                batch=batch,
                batch_repo=batch_repo,
                document_repo=document_repo,
                audit_log_repo=audit_log_repo,
                message="Lote cancelado durante a chamada ao provedor de IA.",
            )
        except Exception as exc:
            batch_repo.finalize(
                batch,
                processed_files=batch.processed_files,
                successful_files=batch.successful_files,
                error_files=max(batch.error_files, 1),
                anomaly_count=batch.anomaly_count,
                status="failed",
            )
            audit_log_repo.create(
                batch_id=batch_id,
                stage="processing",
                status="failed",
                message="Falha interna durante o processamento do lote.",
                payload_ref=str(exc),
            )
        finally:
            db.close()

    # Recalcula os contadores do lote com base no estado atual dos documentos.
    def _update_batch_progress(self, *, batch_repo: BatchRepository, document_repo: DocumentRepository, batch) -> None:
        refreshed_documents = document_repo.list_all_by_batch_id(batch.id)
        processed_files = sum(1 for document in refreshed_documents if document.status in {"done", "error"})
        successful_files = sum(1 for document in refreshed_documents if document.status == "done")
        error_files = sum(1 for document in refreshed_documents if document.status == "error")
        batch_repo.update(
            batch,
            processed_files=processed_files,
            successful_files=successful_files,
            error_files=error_files,
            status="processing",
        )

    # Finaliza um micro-lote unindo parser local, resposta de IA e auditoria.
    def _finalize_document_chunk(
        self,
        *,
        batch_id: str,
        batch,
        items: list[dict[str, object]],
        total_documents: int,
        batch_repo: BatchRepository,
        document_repo: DocumentRepository,
        analysis_repo: AnalysisRepository,
        audit_log_repo: AuditLogRepository,
        cancel_event: Event,
    ) -> None:
        if self._is_cancel_requested(cancel_event):
            self._cancel_current_batch(
                batch_id=batch_id,
                batch=batch,
                batch_repo=batch_repo,
                document_repo=document_repo,
                audit_log_repo=audit_log_repo,
                message="Lote cancelado antes da etapa de enriquecimento por IA.",
            )
            raise LLMProcessingCancelled("Lote cancelado antes da finalizacao do micro-lote.")

        # O micro-lote preserva a auditoria por documento sem abrir mao
        # do ganho de processar varios itens na mesma chamada ao provedor.
        llm_inputs: list[dict[str, object]] = []
        llm_results_by_document: dict[str, dict[str, object]] = {}

        for item in items:
            document_id = str(item["document_id"])
            result = item["result"]
            assert isinstance(result, dict)
            document = document_repo.get_by_id(document_id)
            if document is None:
                continue
            should_use_llm = self.llm_service.should_use_llm_for_document(
                decode_status=str(result["decode_status"]),
                parse_status=str(result["parse_status"]),
                missing_fields=result["missing_fields"] if isinstance(result["missing_fields"], list) else [],
                truncated_fields=result["truncated_fields"] if isinstance(result["truncated_fields"], list) else [],
            )
            if should_use_llm:
                document_repo.update(
                    document,
                    extraction_status="queued_llm",
                    status="processing",
                )
                llm_inputs.append(
                    {
                        "document_id": document_id,
                        "raw_text": result["raw_text"],
                        "parsed_fields": result["extracted_data"],
                        "missing_fields": result["missing_fields"],
                        "truncated_fields": result["truncated_fields"],
                    }
                )
            else:
                document_repo.update(
                    document,
                    extraction_status="local_ready",
                    status="processing",
                )
                llm_results_by_document[document_id] = self.llm_service.build_local_parser_result(
                    parsed_fields=result["extracted_data"] if isinstance(result["extracted_data"], dict) else {},
                    missing_fields=result["missing_fields"] if isinstance(result["missing_fields"], list) else [],
                    truncated_fields=result["truncated_fields"] if isinstance(result["truncated_fields"], list) else [],
                    message="Extracao deterministica concluida sem necessidade de chamada ao LLM.",
                )

        if llm_inputs:
            # Registra cada request ao LLM como evento de auditoria do lote.
            def record_llm_request_event(event: dict[str, object]) -> None:
                provider_name = str(event.get("provider") or "llm")
                audit_log_repo.create(
                    batch_id=batch_id,
                    stage="llm_request",
                    status=str(event.get("status") or "unknown"),
                    message=f"{provider_name} request {event.get('strategy') or 'unknown'}",
                    payload_ref=json.dumps(event, ensure_ascii=False),
                )

            for llm_input in llm_inputs:
                document = document_repo.get_by_id(str(llm_input["document_id"]))
                if document is not None:
                    document_repo.update(
                        document,
                        extraction_status="llm_processing",
                        status="processing",
                    )
            llm_results_by_document.update(
                self.llm_service.analyze_invoices_batch(
                    llm_inputs,
                    cancel_checker=lambda: self._is_cancel_requested(cancel_event),
                    request_event_callback=record_llm_request_event,
                    total_documents=total_documents,
                )
            )

        for item in items:
            if self._is_cancel_requested(cancel_event):
                self._cancel_current_batch(
                    batch_id=batch_id,
                    batch=batch,
                    batch_repo=batch_repo,
                    document_repo=document_repo,
                    audit_log_repo=audit_log_repo,
                    message="Lote cancelado durante a consolidacao dos resultados.",
                )
                raise LLMProcessingCancelled("Lote cancelado durante a consolidacao do micro-lote.")

            document_id = str(item["document_id"])
            result = item["result"]
            assert isinstance(result, dict)
            document = document_repo.get_by_id(document_id)
            if document is None:
                continue
            llm_result = llm_results_by_document.get(document_id) or self.llm_service.build_local_parser_result(
                parsed_fields=result["extracted_data"] if isinstance(result["extracted_data"], dict) else {},
                missing_fields=result["missing_fields"] if isinstance(result["missing_fields"], list) else [],
                truncated_fields=result["truncated_fields"] if isinstance(result["truncated_fields"], list) else [],
                message="Analise local aplicada por ausencia de resposta do LLM.",
            )

            audit_log_repo.create(
                batch_id=batch_id,
                document_id=document.id,
                stage="llm_extract",
                status=str(llm_result.get("extraction_status") or "unknown"),
                message=str(llm_result.get("summary") or "Analise de IA executada."),
                payload_ref=json.dumps(
                    {
                        "provider": llm_result.get("provider"),
                        "requested_model": llm_result.get("requested_model"),
                        "effective_model": llm_result.get("model"),
                        "fallback_used": llm_result.get("fallback_used"),
                        "attempted_models": llm_result.get("attempted_models"),
                        "provider_error": llm_result.get("provider_error"),
                        "raw_response": llm_result.get("raw_response"),
                    },
                    ensure_ascii=False,
                ),
            )

            llm_status = str(llm_result.get("extraction_status") or "success")
            llm_fields = (
                llm_result.get("normalized_fields")
                if self._should_merge_llm_fields(llm_status=llm_status)
                and isinstance(llm_result.get("normalized_fields"), dict)
                else {}
            )
            # Uma resposta fraca ou falha do LLM nao pode apagar valores
            # que o parser deterministico ja extraiu corretamente.
            merged_data = self._merge_fields(
                base_fields=result["extracted_data"],
                llm_fields=llm_fields,
            )
            final_missing_fields = self._calculate_missing_fields(merged_data)
            final_truncated_fields = self._merge_field_lists(
                result["truncated_fields"],
                llm_result.get("truncated_fields") if self._should_merge_llm_fields(llm_status=llm_status) else [],
            )
            extraction_status = self._determine_extraction_status(
                parse_status=result["parse_status"],
                decode_status=result["decode_status"],
                missing_fields=final_missing_fields,
                llm_status=llm_status,
            )
            document_status = "error" if extraction_status == "failed" else "done"
            error_code = result["error_code"]
            error_message = result["error_message"]

            if document_status != "error":
                error_code = None
                error_message = None
            elif not error_code and any(field in REQUIRED_FIELDS for field in final_missing_fields):
                error_code = "required_fields_missing"
                error_message = "Campos obrigatorios nao puderam ser extraidos."
            elif not error_code:
                error_code = "unprocessable_file"
            if document_status == "error" and not error_message:
                error_message = "Arquivo nao processavel."

            document_repo.update_processing_result(
                document,
                raw_text=result["raw_text"],
                extracted_text=result["raw_text"],
                extracted_data=merged_data,
                missing_fields=final_missing_fields,
                truncated_fields=final_truncated_fields,
                decode_status=result["decode_status"],
                parse_status=result["parse_status"],
                extraction_status=extraction_status,
                error_code=error_code,
                error_message=error_message,
                status=document_status,
            )
            self._update_batch_progress(batch_repo=batch_repo, document_repo=document_repo, batch=batch)

            analysis_repo.upsert(
                document.id,
                provider=llm_result.get("provider"),
                model=llm_result.get("model"),
                requested_model=llm_result.get("requested_model"),
                fallback_used="true" if llm_result.get("fallback_used") else "false",
                attempted_models=llm_result.get("attempted_models"),
                prompt_version=llm_result.get("prompt_version"),
                classification=llm_result.get("classification"),
                risk_score=llm_result.get("risk_score"),
                summary=llm_result.get("summary"),
                inconsistencies=llm_result.get("inconsistencies"),
                confidence_overall=llm_result.get("confidence_overall"),
                raw_response=llm_result.get("raw_response"),
                extraction_status=llm_result.get("extraction_status"),
                missing_fields=final_missing_fields,
                truncated_fields=final_truncated_fields,
            )

    # Consulta o tamanho ideal do micro-lote junto ao roteador de IA.
    def _processing_chunk_size(self, total_documents: int | None = None) -> int:
        return self.llm_service.get_processing_chunk_size(total_documents)

    # Processa um arquivo isolado ate o resultado local inicial.
    def _process_single(self, pending: PendingUploadDocument) -> dict[str, Any]:
        decode_result = self._decode_bytes(pending.content)
        if decode_result["status"] == "failed":
            return {
                "raw_text": "",
                "decode_status": "failed",
                "decode_message": decode_result["message"],
                "parse_status": "failed",
                "parse_message": "Arquivo nao pode ser decodificado.",
                "extracted_data": self._empty_extracted_data(),
                "missing_fields": EXPECTED_FIELDS.copy(),
                "truncated_fields": [],
                "error_code": "invalid_encoding",
                "error_message": decode_result["message"],
            }

        parse_result = self._parse_invoice_text(decode_result["text"])
        return {
            "raw_text": decode_result["text"],
            "decode_status": decode_result["status"],
            "decode_message": decode_result["message"],
            "parse_status": parse_result["parse_status"],
            "parse_message": parse_result["message"],
            "extracted_data": parse_result["extracted_data"],
            "missing_fields": parse_result["missing_fields"],
            "truncated_fields": parse_result["truncated_fields"],
            "error_code": parse_result["error_code"],
            "error_message": parse_result["error_message"],
        }

    # Tenta decodificar o arquivo com encodings conhecidos.
    def _decode_bytes(self, content: bytes) -> dict[str, str]:
        for encoding, status in (("utf-8-sig", "success"), ("utf-8", "success"), ("cp1252", "recovered"), ("latin-1", "recovered")):
            try:
                text = content.decode(encoding)
            except UnicodeDecodeError:
                continue
            if self._looks_corrupted(text):
                continue
            message = "Arquivo decodificado com sucesso."
            if status == "recovered":
                message = f"Arquivo recuperado com fallback de encoding ({encoding})."
            return {"status": status, "text": text, "message": message}
        return {"status": "failed", "text": "", "message": "Encoding invalido ou conteudo corrompido."}

    # Detecta rapidamente textos vazios ou corrompidos.
    def _looks_corrupted(self, text: str) -> bool:
        if not text.strip():
            return True
        control_characters = sum(1 for char in text if ord(char) < 32 and char not in "\r\n\t")
        control_ratio = control_characters / max(len(text), 1)
        return "\ufffd" in text or control_ratio > 0.02

    # Extrai pares CHAVE: VALOR e marca ausencias ou truncamentos.
    def _parse_invoice_text(self, raw_text: str) -> dict[str, Any]:
        extracted_data = self._empty_extracted_data()
        missing_fields = EXPECTED_FIELDS.copy()
        truncated_fields: list[str] = []
        matched_any = False

        for raw_line in raw_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if ":" not in line:
                possible_field = self._normalize_key(line)
                if possible_field in FIELD_ALIASES:
                    truncated_fields.append(FIELD_ALIASES[possible_field])
                continue

            key, value = line.split(":", 1)
            normalized_key = self._normalize_key(key)
            canonical_key = FIELD_ALIASES.get(normalized_key)
            if not canonical_key:
                continue

            matched_any = True
            cleaned_value = self._clean_value(value)
            if cleaned_value == "":
                truncated_fields.append(canonical_key)
                continue

            extracted_data[canonical_key] = self._normalize_field(canonical_key, cleaned_value)
            if canonical_key in missing_fields:
                missing_fields.remove(canonical_key)

        parse_status = "success"
        message = "Campos extraidos com sucesso."
        error_code = None
        error_message = None

        if not matched_any:
            parse_status = "failed"
            message = "Nenhuma estrutura CHAVE: VALOR foi encontrada."
            error_code = "parse_failed"
            error_message = "Formato do arquivo nao corresponde ao esperado."
        elif missing_fields or truncated_fields:
            parse_status = "partial"
            message = "Arquivo extraido parcialmente; ha campos ausentes ou truncados."

        if self._has_obvious_truncation(raw_text):
            parse_status = "partial" if parse_status != "failed" else parse_status
            for field in ("descricao_servico", "banco_destino"):
                if field not in truncated_fields and extracted_data.get(field) == "nao_extraido":
                    truncated_fields.append(field)

        return {
            "parse_status": parse_status,
            "message": message,
            "extracted_data": extracted_data,
            "missing_fields": missing_fields,
            "truncated_fields": sorted(set(truncated_fields)),
            "error_code": error_code,
            "error_message": error_message,
        }

    # Padroniza a chave lida do arquivo para o nome canonico interno.
    def _normalize_key(self, key: str) -> str:
        cleaned = re.sub(r"[^A-Z0-9_]", "", key.upper().strip().replace(" ", "_"))
        return cleaned

    # Limpa espacos repetidos antes da normalizacao dos campos.
    def _clean_value(self, value: str) -> str:
        return re.sub(r"\s+", " ", value.strip())

    # Normaliza cada campo para o formato esperado pelo sistema.
    def _normalize_field(self, field_name: str, value: str) -> object:
        if not value:
            return "nao_extraido"
        if field_name in {"data_emissao", "data_pagamento", "data_emissao_nf"}:
            return self._normalize_date(value)
        if field_name == "valor_bruto":
            return self._normalize_currency(value)
        if field_name == "cnpj_fornecedor":
            digits = "".join(char for char in value if char.isdigit())
            return digits or "nao_extraido"
        if field_name == "status":
            return value.upper()
        if field_name == "tipo_documento":
            return value.upper()
        if field_name == "hash_verificacao":
            return value.upper()
        return value

    # Converte datas reconhecidas para o padrao ISO.
    def _normalize_date(self, value: str) -> str:
        candidate = value.strip()
        for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(candidate, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return candidate or "nao_extraido"

    # Converte valores monetarios textuais para numero.
    def _normalize_currency(self, value: str) -> object:
        cleaned = value.replace("R$", "").replace(" ", "").replace(".", "").replace(",", ".")
        try:
            return round(float(cleaned), 2)
        except ValueError:
            return "nao_extraido"

    # Sinaliza sinais evidentes de corte no fim do documento.
    def _has_obvious_truncation(self, raw_text: str) -> bool:
        stripped = raw_text.rstrip()
        return bool(stripped and not stripped.endswith((".", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9")) and ":" not in stripped.splitlines()[-1])

    # Gera a estrutura base com todos os campos marcados como nao extraidos.
    def _empty_extracted_data(self) -> dict[str, object]:
        return {field: "nao_extraido" for field in EXPECTED_FIELDS}

    # Recalcula os campos ausentes a partir do dado final consolidado.
    def _calculate_missing_fields(self, extracted_data: dict[str, object]) -> list[str]:
        return [field for field, value in extracted_data.items() if value in {None, "", "nao_extraido"}]

    # Mescla parser local e IA preservando o dado valido ja encontrado.
    def _merge_fields(self, *, base_fields: dict[str, object], llm_fields: dict[str, object]) -> dict[str, object]:
        merged = dict(base_fields)
        for field in EXPECTED_FIELDS:
            llm_value = llm_fields.get(field)
            if llm_value not in {None, "", "nao_extraido"}:
                merged[field] = llm_value
        return merged

    # Decide se os campos vindos do LLM podem ser aproveitados.
    def _should_merge_llm_fields(self, *, llm_status: str) -> bool:
        return llm_status not in NON_FATAL_LLM_STATUSES

    # Junta listas de alerta sem repetir campos.
    def _merge_field_lists(self, *values: object) -> list[str]:
        merged: list[str] = []
        for item in values:
            if isinstance(item, list):
                for value in item:
                    if isinstance(value, str) and value not in merged:
                        merged.append(value)
        return merged

    # Determina o status final de extracao do documento.
    def _determine_extraction_status(
        self,
        *,
        parse_status: str,
        decode_status: str,
        missing_fields: list[str],
        llm_status: str,
    ) -> str:
        if decode_status == "failed" or parse_status == "failed":
            return "failed"
        if any(field in REQUIRED_FIELDS for field in missing_fields):
            return "failed"
        if llm_status == "failed":
            return "partial"
        if parse_status == "partial" or llm_status in {"partial", "fallback"} or missing_fields:
            return "partial"
        return "success"

    # Consulta se o lote recebeu pedido de cancelamento.
    def _is_cancel_requested(self, cancel_event: Event) -> bool:
        return cancel_event.is_set()

    # Reverte documentos em andamento e marca o lote como cancelado.
    def _cancel_current_batch(
        self,
        *,
        batch_id: str,
        batch,
        batch_repo: BatchRepository,
        document_repo: DocumentRepository,
        audit_log_repo: AuditLogRepository,
        message: str,
    ) -> None:
        # Reverte documentos em andamento para permitir nova tentativa do lote
        # sem deixar itens parcialmente processados com cara de estado final.
        processing_documents = [document for document in document_repo.list_all_by_batch_id(batch_id) if document.status == "processing"]
        for document in processing_documents:
            document_repo.update(
                document,
                status="pending",
                decode_status="pending",
                parse_status="pending",
                extraction_status="pending",
                error_code=None,
                error_message=None,
                processed_at=None,
            )

        refreshed_documents = document_repo.list_all_by_batch_id(batch_id)
        processed_files = sum(1 for document in refreshed_documents if document.status in {"done", "error"})
        successful_files = sum(1 for document in refreshed_documents if document.status == "done")
        error_files = sum(1 for document in refreshed_documents if document.status == "error")
        batch_repo.mark_cancelled(
            batch,
            processed_files=processed_files,
            successful_files=successful_files,
            error_files=error_files,
            anomaly_count=batch.anomaly_count,
        )
        audit_log_repo.create(
            batch_id=batch_id,
            stage="processing",
            status="cancelled",
            message=message,
        )

    # Garante o cancelamento final do lote mesmo fora da thread original.
    def _finalize_cancelled_batch(self, *, batch_id: str, message: str, allow_final_states: bool = False) -> None:
        db = SessionLocal()
        try:
            batch_repo = BatchRepository(db)
            document_repo = DocumentRepository(db)
            audit_log_repo = AuditLogRepository(db)
            batch = batch_repo.get_by_id(batch_id)
            if batch is None:
                return
            if not allow_final_states and batch.status in {"completed", "completed_with_errors", "failed", "cancelled"}:
                return
            self._cancel_current_batch(
                batch_id=batch_id,
                batch=batch,
                batch_repo=batch_repo,
                document_repo=document_repo,
                audit_log_repo=audit_log_repo,
                message=message,
            )
        finally:
            db.close()

    # Remove o lote das estruturas internas de rastreamento.
    def _cleanup_tracking(self, batch_id: str) -> None:
        with self._tracking_lock:
            self._tracked_futures.pop(batch_id, None)
            self._cancel_events.pop(batch_id, None)

    # Cria o pool de threads usado no processamento em background.
    def _create_executor(self) -> ThreadPoolExecutor:
        return ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="nf-audit")
