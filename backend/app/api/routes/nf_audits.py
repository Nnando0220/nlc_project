"""Rotas publicas do fluxo de auditoria de NFs.

As rotas delegam regra de negocio ao servico e mantem o handler HTTP enxuto.
"""

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.nf_audit import (
    NFAuditAnomalyListResponse,
    NFAuditBatchProgressResponse,
    NFAuditBatchResponse,
    NFAuditDocumentListResponse,
    NFAuditUploadResponse,
)
from app.schemas.report import GenerateReportResponse
from app.services.nf_audit_service import (
    NFAuditService,
    anomaly_to_response,
    batch_to_response,
    build_progress_summary,
    document_to_response,
)

router = APIRouter()


def _service(db: Session) -> NFAuditService:
    """Factory local para centralizar a criacao do servico por request."""
    return NFAuditService(db)


# Etapa 1: envio e criacao do lote.
@router.post("/nf-audits/uploads", response_model=NFAuditUploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_nf_audit_batch(
    files: list[UploadFile] = File(...),
    batch_name: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> NFAuditUploadResponse:
    """Recebe arquivos e agenda o processamento assincrono do lote."""
    batch = await _service(db).upload_batch(files=files, batch_name=batch_name)
    return NFAuditUploadResponse(
        batch_id=batch.id,
        batch_name=batch.batch_name,
        status=batch.status,
        total_files=batch.total_files,
        processed_files=batch.processed_files,
        error_files=batch.error_files,
        anomaly_count=batch.anomaly_count,
        progress=build_progress_summary(batch=batch, documents=None, latest_stage=None, audit_logs=None),
    )


# Etapa 2: acompanhamento operacional do lote.
@router.get("/nf-audits/batches/{batch_id}", response_model=NFAuditBatchResponse)
def get_nf_audit_batch(
    batch_id: str,
    db: Session = Depends(get_db),
) -> NFAuditBatchResponse:
    """Retorna resumo do lote com progresso consolidado."""
    service = _service(db)
    batch = service.get_batch(batch_id=batch_id)
    documents = service.document_repo.list_all_by_batch_id(batch_id)
    audit_logs = service.audit_log_repo.list_by_batch_id(batch_id)
    response = batch_to_response(batch)
    response.progress = build_progress_summary(
        batch=batch,
        documents=documents,
        latest_stage=service._latest_batch_stage(batch_id),
        audit_logs=audit_logs,
    )
    return response


@router.post("/nf-audits/batches/{batch_id}/cancel", response_model=NFAuditBatchResponse)
def cancel_nf_audit_batch(
    batch_id: str,
    db: Session = Depends(get_db),
) -> NFAuditBatchResponse:
    """Solicita cancelamento cooperativo do processamento do lote."""
    service = _service(db)
    batch = service.cancel_batch(batch_id=batch_id)
    documents = service.document_repo.list_all_by_batch_id(batch_id)
    audit_logs = service.audit_log_repo.list_by_batch_id(batch_id)
    response = batch_to_response(batch)
    response.progress = build_progress_summary(
        batch=batch,
        documents=documents,
        latest_stage=service._latest_batch_stage(batch_id),
        audit_logs=audit_logs,
    )
    return response


@router.get("/nf-audits/batches/{batch_id}/progress", response_model=NFAuditBatchProgressResponse)
def get_nf_audit_batch_progress(
    batch_id: str,
    db: Session = Depends(get_db),
) -> NFAuditBatchProgressResponse:
    """Retorna progresso detalhado do lote e estado por documento."""
    return _service(db).get_batch_progress(batch_id=batch_id)


# Etapa 3: revisao de dados e anomalias.
@router.get("/nf-audits/batches/{batch_id}/documents", response_model=NFAuditDocumentListResponse)
def list_nf_audit_documents(
    batch_id: str,
    search: str | None = Query(default=None),
    status: str | None = Query(default=None),
    extraction_status: str | None = Query(default=None),
    decode_status: str | None = Query(default=None),
    has_anomaly: bool | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
) -> NFAuditDocumentListResponse:
    """Lista documentos processados com filtros e dados enriquecidos."""
    service = _service(db)
    documents, total = service.list_documents(
        batch_id=batch_id,
        search=search,
        status=status,
        extraction_status=extraction_status,
        decode_status=decode_status,
        has_anomaly=has_anomaly,
        skip=skip,
        limit=limit,
    )
    items = []
    for document in documents:
        analysis = service.analysis_repo.get_by_document_id(document.id)
        anomalies = [anomaly_to_response(item, document.file_name) for item in service.anomaly_repo.list_by_document_id(document.id)]
        items.append(document_to_response(document, analysis, anomalies))
    return NFAuditDocumentListResponse(items=items, total=total, skip=skip, limit=limit)


@router.get("/nf-audits/batches/{batch_id}/anomalies", response_model=NFAuditAnomalyListResponse)
def list_nf_audit_anomalies(
    batch_id: str,
    rule_code: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    search: str | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> NFAuditAnomalyListResponse:
    """Lista anomalias do lote com filtros de regra, severidade e busca."""
    service = _service(db)
    anomalies, documents_by_id, total = service.list_anomalies(
        batch_id=batch_id,
        rule_code=rule_code,
        severity=severity,
        search=search,
        skip=skip,
        limit=limit,
    )
    return NFAuditAnomalyListResponse(
        items=[anomaly_to_response(item, documents_by_id.get(item.document_id, "")) for item in anomalies],
        total=total,
        skip=skip,
        limit=limit,
    )


# Etapa 4: exportacao e download para BI.
@router.post("/nf-audits/batches/{batch_id}/exports/results.csv", response_model=GenerateReportResponse)
def export_nf_audit_results(
    batch_id: str,
    db: Session = Depends(get_db),
) -> GenerateReportResponse:
    """Gera o CSV principal de resultados por documento."""
    report = _service(db).export_results(batch_id=batch_id)
    return GenerateReportResponse(report_id=report.id, batch_id=report.batch_id, csv_path=report.csv_path, report_type=report.report_type)


@router.post("/nf-audits/batches/{batch_id}/exports/audit.csv", response_model=GenerateReportResponse)
def export_nf_audit_logs(
    batch_id: str,
    db: Session = Depends(get_db),
) -> GenerateReportResponse:
    """Gera o CSV de trilha de auditoria do lote."""
    report = _service(db).export_audit(batch_id=batch_id)
    return GenerateReportResponse(report_id=report.id, batch_id=report.batch_id, csv_path=report.csv_path, report_type=report.report_type)


@router.post("/nf-audits/batches/{batch_id}/exports/anomalies.csv", response_model=GenerateReportResponse)
def export_nf_audit_anomalies(
    batch_id: str,
    db: Session = Depends(get_db),
) -> GenerateReportResponse:
    """Gera o CSV granular de anomalias detectadas."""
    report = _service(db).export_anomalies(batch_id=batch_id)
    return GenerateReportResponse(report_id=report.id, batch_id=report.batch_id, csv_path=report.csv_path, report_type=report.report_type)


@router.get("/nf-audits/reports/{report_id}/download")
def download_nf_audit_report(
    report_id: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    """Realiza download do arquivo CSV previamente gerado."""
    report, report_path = _service(db).get_report_download(report_id=report_id)
    filename = Path(report.csv_path).name
    return FileResponse(path=report_path, media_type="text/csv", filename=filename)
