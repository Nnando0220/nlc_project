import csv
import io
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db.init_db import init_db
from app.main import app
from app.services.nf_audit_service import file_processor


def _wait_for_batch_status(
    client: TestClient,
    batch_id: str,
    statuses: set[str],
    timeout_seconds: float = 8.0,
) -> dict:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        response = client.get(f"/api/v1/nf-audits/batches/{batch_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] in statuses:
            return payload
        time.sleep(0.1)
    raise AssertionError("Batch did not finish in time")


def _wait_for_batch_completion(client: TestClient, batch_id: str, timeout_seconds: float = 8.0) -> dict:
    return _wait_for_batch_status(
        client,
        batch_id,
        {"completed", "completed_with_errors", "failed"},
        timeout_seconds=timeout_seconds,
    )


@pytest.fixture(autouse=True)
def disable_external_llm_calls():
    original_api_key = file_processor.llm_service.api_key
    original_provider_keys = None
    if hasattr(file_processor.llm_service, "providers"):
        original_provider_keys = {
            provider_name: service.api_key
            for provider_name, service in file_processor.llm_service.providers.items()
        }
    original_strategy = file_processor.llm_service.analysis_strategy
    file_processor.llm_service.api_key = ""
    file_processor.llm_service.analysis_strategy = "selective"
    try:
        yield
    finally:
        if original_provider_keys is not None and hasattr(file_processor.llm_service, "providers"):
            for provider_name, api_key in original_provider_keys.items():
                file_processor.llm_service.providers[provider_name].api_key = api_key
        else:
            file_processor.llm_service.api_key = original_api_key
        file_processor.llm_service.analysis_strategy = original_strategy


def test_auth_routes_should_not_be_exposed() -> None:
    with TestClient(app) as client:
        assert client.post("/api/v1/auth/register", json={}).status_code == 404
        assert client.post("/api/v1/auth/login", json={}).status_code == 404
        assert client.get("/api/v1/auth/me").status_code == 404


def test_should_not_expose_legacy_routes() -> None:
    init_db()
    with TestClient(app) as client:
        assert client.post("/api/v1/users", json={"name": "Legacy", "email": "legacy@example.com", "password": "12345678"}).status_code == 404
        assert client.post(
            "/api/v1/batches",
            json={"user_id": "legacy-user", "batch_name": "Legacy", "total_files": 1},
        ).status_code == 404
        assert client.get("/api/v1/users/legacy-user/batches").status_code == 404
        assert client.post("/api/v1/documents/some-document-id/analyze").status_code == 404
        assert client.post("/api/v1/batches/some-batch-id/reports/csv").status_code == 404


def test_nf_audit_upload_and_exports_with_txt_files() -> None:
    init_db()
    invoice_a = """TIPO_DOCUMENTO: NOTA_FISCAL
NUMERO_DOCUMENTO: NF-100
DATA_EMISSAO: 15/04/2024
FORNECEDOR: TechSoft Ltda
CNPJ_FORNECEDOR: 12345678000190
DESCRICAO_SERVICO: Licenca de Software ERP
VALOR_BRUTO: R$ 15000,00
DATA_PAGAMENTO: 20/04/2024
DATA_EMISSAO_NF: 15/04/2024
APROVADO_POR: Maria Silva
BANCO_DESTINO: Banco do Brasil Ag.1234 C/C 56789-0
STATUS: PAGO
HASH_VERIFICACAO: NLC042338471
"""
    invoice_b = """TIPO_DOCUMENTO: NOTA_FISCAL
NUMERO_DOCUMENTO: NF-100
DATA_EMISSAO: 16/04/2024
FORNECEDOR: TechSoft Ltda
CNPJ_FORNECEDOR: 12345678000191
DESCRICAO_SERVICO: Licenca de Software ERP
VALOR_BRUTO: R$ 45000,00
DATA_PAGAMENTO: 14/04/2024
DATA_EMISSAO_NF: 16/04/2024
APROVADO_POR: Aprovador Fantasma
BANCO_DESTINO: Banco do Brasil Ag.1234 C/C 56789-0
STATUS: PAGO
HASH_VERIFICACAO: NLC042338472
"""
    invoice_c = b"\xff\xfe\x00\x00arquivo corrompido"

    with TestClient(app) as client:
        upload_response = client.post(
            "/api/v1/nf-audits/uploads",
            files=[
                ("files", ("nota-001.txt", invoice_a.encode("utf-8"), "text/plain")),
                ("files", ("nota-002.txt", invoice_b.encode("utf-8"), "text/plain")),
                ("files", ("nota-003.txt", invoice_c, "text/plain")),
            ],
            data={"batch_name": "Lote Teste NF"},
        )

        assert upload_response.status_code == 202
        batch_id = upload_response.json()["batch_id"]
        assert upload_response.json()["status"] == "processing"
        assert upload_response.json()["progress"]["pending_files"] == 3

        batch_payload = _wait_for_batch_completion(client, batch_id)
        assert batch_payload["total_files"] == 3
        assert batch_payload["processed_files"] == 3
        assert batch_payload["anomaly_count"] >= 4
        assert batch_payload["status"] in {"completed_with_errors", "failed", "completed"}
        assert "progress" in batch_payload

        documents_response = client.get(
            f"/api/v1/nf-audits/batches/{batch_id}/documents?skip=0&limit=10",
        )
        assert documents_response.status_code == 200
        documents_payload = documents_response.json()
        assert documents_payload["total"] == 3
        assert any(item["file_name"] == "nota-003.txt" and item["status"] == "error" for item in documents_payload["items"])
        assert all("llm_provider" in item for item in documents_payload["items"])
        assert all("llm_model" in item for item in documents_payload["items"])
        assert all("llm_requested_model" in item for item in documents_payload["items"])
        assert all("llm_fallback_used" in item for item in documents_payload["items"])
        assert all("llm_attempted_models" in item for item in documents_payload["items"])

        documents_filtered_by_search = client.get(
            f"/api/v1/nf-audits/batches/{batch_id}/documents?search=TechSoft&skip=0&limit=10",
        )
        assert documents_filtered_by_search.status_code == 200
        assert documents_filtered_by_search.json()["total"] == 2

        documents_filtered_by_decode = client.get(
            f"/api/v1/nf-audits/batches/{batch_id}/documents?decode_status=failed&skip=0&limit=10",
        )
        assert documents_filtered_by_decode.status_code == 200
        filtered_decode_items = documents_filtered_by_decode.json()["items"]
        assert len(filtered_decode_items) == 1
        assert filtered_decode_items[0]["file_name"] == "nota-003.txt"

        anomalies_response = client.get(
            f"/api/v1/nf-audits/batches/{batch_id}/anomalies?skip=0&limit=50",
        )
        assert anomalies_response.status_code == 200
        anomaly_codes = {item["rule_code"] for item in anomalies_response.json()["items"]}
        assert "NF_DUPLICADA" in anomaly_codes
        assert "CNPJ_DIVERGENTE" in anomaly_codes
        assert "EMISSAO_APOS_PAGAMENTO" in anomaly_codes
        assert "APROVADOR_NAO_RECONHECIDO" in anomaly_codes
        assert "ARQUIVO_NAO_PROCESSAVEL" in anomaly_codes

        anomalies_filtered = client.get(
            f"/api/v1/nf-audits/batches/{batch_id}/anomalies?search=nota-003&skip=0&limit=50",
        )
        assert anomalies_filtered.status_code == 200
        filtered_anomaly_items = anomalies_filtered.json()["items"]
        assert len(filtered_anomaly_items) == 1
        assert filtered_anomaly_items[0]["rule_code"] == "ARQUIVO_NAO_PROCESSAVEL"

        progress_response = client.get(
            f"/api/v1/nf-audits/batches/{batch_id}/progress",
        )
        assert progress_response.status_code == 200
        progress_payload = progress_response.json()
        assert progress_payload["progress"]["completed_files"] == 3
        assert progress_payload["progress"]["progress_percent"] == 100.0
        assert len(progress_payload["documents"]) == 3

        results_export = client.post(f"/api/v1/nf-audits/batches/{batch_id}/exports/results.csv")
        audit_export = client.post(f"/api/v1/nf-audits/batches/{batch_id}/exports/audit.csv")
        anomalies_export = client.post(f"/api/v1/nf-audits/batches/{batch_id}/exports/anomalies.csv")
        assert results_export.status_code == 200
        assert audit_export.status_code == 200
        assert anomalies_export.status_code == 200
        assert Path(results_export.json()["csv_path"]).exists()
        assert Path(audit_export.json()["csv_path"]).exists()
        assert Path(anomalies_export.json()["csv_path"]).exists()
        assert results_export.json()["report_type"] == "results"
        assert audit_export.json()["report_type"] == "audit"
        assert anomalies_export.json()["report_type"] == "anomalies"
        results_download = client.get(
            f"/api/v1/nf-audits/reports/{results_export.json()['report_id']}/download",
        )
        audit_download = client.get(
            f"/api/v1/nf-audits/reports/{audit_export.json()['report_id']}/download",
        )
        anomalies_download = client.get(
            f"/api/v1/nf-audits/reports/{anomalies_export.json()['report_id']}/download",
        )
        assert results_download.status_code == 200
        assert audit_download.status_code == 200
        assert anomalies_download.status_code == 200
        assert "text/csv" in (results_download.headers.get("content-type") or "")
        assert "text/csv" in (audit_download.headers.get("content-type") or "")
        assert "text/csv" in (anomalies_download.headers.get("content-type") or "")

        with Path(results_export.json()["csv_path"]).open(encoding="utf-8", newline="") as results_file:
            results_rows = list(csv.DictReader(results_file))
        with Path(audit_export.json()["csv_path"]).open(encoding="utf-8", newline="") as audit_file:
            audit_rows = list(csv.DictReader(audit_file))
        with Path(anomalies_export.json()["csv_path"]).open(encoding="utf-8", newline="") as anomalies_file:
            anomaly_rows = list(csv.DictReader(anomalies_file))

        assert results_rows
        assert audit_rows
        assert anomaly_rows
        assert results_rows[0]["batch_id"] == batch_id
        assert {"has_anomaly", "has_encoding_error", "has_encoding_recovery", "confidence_overall"} <= set(results_rows[0].keys())
        assert audit_rows[0]["batch_id"] == batch_id
        assert {
            "verification",
            "result",
            "rule_code",
            "confidence",
            "provider",
            "effective_model",
            "error_code",
            "http_status",
            "retryable",
            "user_message",
            "technical_message",
        } <= set(audit_rows[0].keys())
        assert anomaly_rows[0]["batch_id"] == batch_id
        assert {"fornecedor", "cnpj_fornecedor", "rule_code", "severity", "confidence"} <= set(anomaly_rows[0].keys())


def test_nf_audit_accepts_zip_upload() -> None:
    init_db()
    invoice = """TIPO_DOCUMENTO: NOTA_FISCAL
NUMERO_DOCUMENTO: NF-777
DATA_EMISSAO: 01/03/2024
FORNECEDOR: Zip Supplier
CNPJ_FORNECEDOR: 99887766000155
DESCRICAO_SERVICO: Auditoria
VALOR_BRUTO: R$ 3500,00
DATA_PAGAMENTO: 02/03/2024
DATA_EMISSAO_NF: 01/03/2024
APROVADO_POR: Fernanda Costa
BANCO_DESTINO: Bradesco Ag.0001 C/C 99887-7
STATUS: PAGO
HASH_VERIFICACAO: NLC0932839730
"""
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zip_file:
        zip_file.writestr("nota_zip.txt", invoice)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/nf-audits/uploads",
            files=[("files", ("lote.zip", zip_buffer.getvalue(), "application/zip"))],
        )
        assert response.status_code == 202
        batch_id = response.json()["batch_id"]
        assert response.json()["status"] == "processing"
        batch_payload = _wait_for_batch_completion(client, batch_id)
        assert batch_payload["total_files"] == 1
        documents_response = client.get(
            f"/api/v1/nf-audits/batches/{batch_id}/documents?skip=0&limit=10",
        )
        assert documents_response.status_code == 200
        assert documents_response.json()["items"][0]["source_type"] == "zip_entry"


def test_non_invoice_documents_should_keep_local_fields_and_use_scope_anomaly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db()
    document_payload = """TIPO_DOCUMENTO: FATURA
NUMERO_DOCUMENTO: NF-98039
DATA_EMISSAO: 25/09/2023
FORNECEDOR: Limpeza & Facilities
CNPJ_FORNECEDOR: 56.789.012/0001-78
DESCRICAO_SERVICO: Manutencao Eletrica
VALOR_BRUTO: R$ 12.000,00
DATA_PAGAMENTO: 02/10/2023
DATA_EMISSAO_NF: 20/09/2023
APROVADO_POR: Ana Beatriz
BANCO_DESTINO: Santander Ag.3456 C/C 78901-2
STATUS: PAGO
HASH_VERIFICACAO: NLC0027776856
"""

    monkeypatch.setattr(
        file_processor.llm_service,
        "should_use_llm_for_document",
        lambda **_: True,
    )

    def fake_analyze_invoices_batch(
        documents: list[dict[str, object]],
        **_: object,
    ) -> dict[str, dict[str, object]]:
        document_id = str(documents[0]["document_id"])
        return {
            document_id: {
                "provider": "openrouter",
                "model": "inclusionai/ling-2.6-flash:free",
                "requested_model": "inclusionai/ling-2.6-flash:free",
                "fallback_used": False,
                "attempted_models": ["inclusionai/ling-2.6-flash:free"],
                "prompt_version": "nf-audit-v1",
                "classification": "fora_do_escopo",
                "risk_score": None,
                "summary": "FATURA nao e NOTA_FISCAL; extracao falhou.",
                "inconsistencies": {},
                "confidence_overall": 0.0,
                "raw_response": "{}",
                "extraction_status": "failed",
                "missing_fields": [
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
                    "status",
                ],
                "truncated_fields": [],
                "normalized_fields": {
                    "tipo_documento": "nao_extraido",
                    "numero_documento": "nao_extraido",
                    "data_emissao": "nao_extraido",
                    "fornecedor": "nao_extraido",
                    "cnpj_fornecedor": "nao_extraido",
                    "descricao_servico": "nao_extraido",
                    "valor_bruto": 0.0,
                    "data_pagamento": "nao_extraido",
                    "data_emissao_nf": "nao_extraido",
                    "aprovado_por": "nao_extraido",
                    "banco_destino": "nao_extraido",
                    "status": "nao_extraido",
                    "hash_verificacao": "nao_extraido",
                },
                "provider_error": None,
            }
        }

    monkeypatch.setattr(
        file_processor.llm_service,
        "analyze_invoices_batch",
        fake_analyze_invoices_batch,
    )

    with TestClient(app) as client:
        upload_response = client.post(
            "/api/v1/nf-audits/uploads",
            files=[("files", ("DOC_0027.txt", document_payload.encode("utf-8"), "text/plain"))],
            data={"batch_name": "Lote fora de escopo"},
        )

        assert upload_response.status_code == 202
        batch_id = upload_response.json()["batch_id"]

        batch_payload = _wait_for_batch_completion(client, batch_id)
        assert batch_payload["status"] == "completed"

        documents_response = client.get(
            f"/api/v1/nf-audits/batches/{batch_id}/documents?skip=0&limit=10",
        )
        assert documents_response.status_code == 200
        item = documents_response.json()["items"][0]
        assert item["file_name"] == "DOC_0027.txt"
        assert item["status"] == "done"
        assert item["extraction_status"] == "partial"
        assert item["error_code"] is None
        assert item["error_message"] is None
        assert item["extracted_data"]["tipo_documento"] == "FATURA"
        assert item["extracted_data"]["numero_documento"] == "NF-98039"
        assert item["extracted_data"]["fornecedor"] == "Limpeza & Facilities"
        assert item["extracted_data"]["valor_bruto"] == 12000.0
        assert item["missing_fields"] == []

        anomalies_response = client.get(
            f"/api/v1/nf-audits/batches/{batch_id}/anomalies?skip=0&limit=20",
        )
        assert anomalies_response.status_code == 200
        anomaly_codes = {row["rule_code"] for row in anomalies_response.json()["items"]}
        assert "TIPO_DOCUMENTO_FORA_ESCOPO" in anomaly_codes
        assert "ARQUIVO_NAO_PROCESSAVEL" not in anomaly_codes


def test_nf_audit_should_reject_invalid_extension() -> None:
    init_db()

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/nf-audits/uploads",
            files=[("files", ("malware.pdf", b"123", "application/pdf"))],
        )
        assert response.status_code == 400


def test_nf_audit_end_to_end_main_flow() -> None:
    init_db()
    invoice = b"TIPO_DOCUMENTO: NOTA_FISCAL\nNUMERO_DOCUMENTO: NF-321\nFORNECEDOR: Main Flow Supplier\nCNPJ_FORNECEDOR: 22222222000190\nVALOR_BRUTO: R$ 99,90\nSTATUS: PAGO\nHASH_VERIFICACAO: TEST321"

    with TestClient(app) as client:
        health_response = client.get("/health")
        assert health_response.status_code == 200
        assert health_response.headers.get("x-content-type-options") == "nosniff"

        upload_response = client.post(
            "/api/v1/nf-audits/uploads",
            files=[("files", ("nota-main.txt", invoice, "text/plain"))],
            data={"batch_name": "Fluxo principal"},
            headers={"Origin": "http://localhost:3000"},
        )
        assert upload_response.status_code == 202
        assert upload_response.headers.get("access-control-allow-origin") == "http://localhost:3000"

        batch_id = upload_response.json()["batch_id"]
        batch_payload = _wait_for_batch_completion(client, batch_id)
        assert batch_payload["total_files"] == 1

        documents_response = client.get(
            f"/api/v1/nf-audits/batches/{batch_id}/documents?skip=0&limit=10",
        )
        assert documents_response.status_code == 200
        assert documents_response.json()["total"] == 1

        results_export = client.post(f"/api/v1/nf-audits/batches/{batch_id}/exports/results.csv")
        audit_export = client.post(f"/api/v1/nf-audits/batches/{batch_id}/exports/audit.csv")
        anomalies_export = client.post(f"/api/v1/nf-audits/batches/{batch_id}/exports/anomalies.csv")
        assert results_export.status_code == 200
        assert audit_export.status_code == 200
        assert anomalies_export.status_code == 200
        assert Path(results_export.json()["csv_path"]).exists()
        assert Path(audit_export.json()["csv_path"]).exists()
        assert Path(anomalies_export.json()["csv_path"]).exists()
        assert client.get(
            f"/api/v1/nf-audits/reports/{results_export.json()['report_id']}/download",
        ).status_code == 200
        assert client.get(
            f"/api/v1/nf-audits/reports/{audit_export.json()['report_id']}/download",
        ).status_code == 200
        assert client.get(
            f"/api/v1/nf-audits/reports/{anomalies_export.json()['report_id']}/download",
        ).status_code == 200


def test_nf_audit_should_allow_batch_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    init_db()
    original_process_single = file_processor._process_single

    def slow_process_single(pending):
        time.sleep(0.25)
        return original_process_single(pending)

    monkeypatch.setattr(file_processor, "_process_single", slow_process_single)

    invoice = b"TIPO_DOCUMENTO: NOTA_FISCAL\nNUMERO_DOCUMENTO: NF-CANCEL\nFORNECEDOR: Cancel Supplier\nCNPJ_FORNECEDOR: 33333333000190\nVALOR_BRUTO: R$ 199,90\nSTATUS: PAGO\nHASH_VERIFICACAO: CANCEL001"

    with TestClient(app) as client:
        upload_response = client.post(
            "/api/v1/nf-audits/uploads",
            files=[
                ("files", ("nota-1.txt", invoice, "text/plain")),
                ("files", ("nota-2.txt", invoice, "text/plain")),
                ("files", ("nota-3.txt", invoice, "text/plain")),
                ("files", ("nota-4.txt", invoice, "text/plain")),
            ],
        )
        assert upload_response.status_code == 202
        batch_id = upload_response.json()["batch_id"]

        cancel_response = client.post(f"/api/v1/nf-audits/batches/{batch_id}/cancel")
        assert cancel_response.status_code == 200
        assert cancel_response.json()["status"] in {"cancelling", "cancelled"}

        batch_payload = _wait_for_batch_status(client, batch_id, {"cancelled"}, timeout_seconds=10.0)
        assert batch_payload["status"] == "cancelled"
        assert batch_payload["processed_files"] < batch_payload["total_files"]

        progress_response = client.get(f"/api/v1/nf-audits/batches/{batch_id}/progress")
        assert progress_response.status_code == 200
        progress_payload = progress_response.json()
        assert progress_payload["status"] == "cancelled"
        assert progress_payload["progress"]["processing_files"] == 0


def test_public_batch_access_is_allowed() -> None:
    init_db()
    invoice = b"TIPO_DOCUMENTO: NOTA_FISCAL\nNUMERO_DOCUMENTO: NF-9\nFORNECEDOR: Public Supplier\nCNPJ_FORNECEDOR: 11111111000191\nVALOR_BRUTO: R$ 10,00\nSTATUS: PAGO\nHASH_VERIFICACAO: X1"

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/nf-audits/uploads",
            files=[("files", ("nota-public.txt", invoice, "text/plain"))],
        )
        assert response.status_code == 202
        batch_id = response.json()["batch_id"]

        batch_payload = _wait_for_batch_completion(client, batch_id)
        assert batch_payload["total_files"] == 1

        public_access = client.get(f"/api/v1/nf-audits/batches/{batch_id}")
        assert public_access.status_code == 200
