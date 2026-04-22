from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime
from statistics import median

from app.core.config import settings
from app.db.models.document import Document

HIGH = "high"
MEDIUM = "medium"
SUPPORTED_DOCUMENT_TYPES = {"NOTA_FISCAL"}


# Carrega JSON salvo no banco sem quebrar a avaliacao.
def _load_json(value: str | None, default: object) -> object:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


# Padroniza o nome do fornecedor para comparacoes.
def _canonical_supplier(value: str) -> str:
    return " ".join(value.upper().split())


# Mantem apenas os digitos do CNPJ para comparacao.
def _canonical_cnpj(value: str) -> str:
    return "".join(char for char in value if char.isdigit())


# Converte uma data textual no formato interno do sistema.
def _parse_date(value: object) -> datetime | None:
    if not isinstance(value, str) or value in {"", "nao_extraido"}:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None


# Converte valores numericos ou textuais para float.
def _parse_number(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str) or value in {"", "nao_extraido"}:
        return None
    try:
        return float(value)
    except ValueError:
        return None


# Calcula Q1 e Q3 para deteccao de outliers por IQR.
def _quartiles(values: list[float]) -> tuple[float, float]:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    lower = ordered[:midpoint]
    upper = ordered[midpoint + (0 if len(ordered) % 2 == 0 else 1) :]
    q1 = median(lower) if lower else ordered[0]
    q3 = median(upper) if upper else ordered[-1]
    return float(q1), float(q3)


class AnomalyService:
    required_fields = {
        "tipo_documento",
        "numero_documento",
        "fornecedor",
        "cnpj_fornecedor",
        "valor_bruto",
        "status",
        "hash_verificacao",
    }

    # Avalia todos os documentos do lote e retorna as anomalias detectadas.
    def evaluate(
        self,
        *,
        batch_id: str,
        batch_documents: list[Document],
    ) -> list[dict[str, object]]:
        batch_records = [self._build_record(document) for document in batch_documents]

        valid_records = [record for record in batch_records if record["is_valid"]]
        supplier_counts = Counter(record["supplier_key"] for record in valid_records if record["supplier_key"])
        approver_counts = Counter(record["approver_key"] for record in valid_records if record["approver_key"])

        canonical_cnpjs: dict[str, str] = {}
        cnpj_counts: dict[str, Counter[str]] = defaultdict(Counter)
        supplier_values: dict[str, list[float]] = defaultdict(list)
        duplicate_index: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)

        for record in valid_records:
            if record["supplier_key"] and record["cnpj_key"]:
                cnpj_counts[record["supplier_key"]][record["cnpj_key"]] += 1
            if record["supplier_key"] and record["value"] is not None:
                supplier_values[record["supplier_key"]].append(record["value"])
            if record["document_number"] and record["supplier_key"]:
                duplicate_index[(record["document_number"], record["supplier_key"])].append(record)

        for supplier_key, counts in cnpj_counts.items():
            canonical_cnpjs[supplier_key] = counts.most_common(1)[0][0]

        anomalies: list[dict[str, object]] = []
        known_approvers = {_canonical_supplier(item) for item in settings.known_approvers}

        for record in batch_records:
            anomalies.extend(
                self._evaluate_record(
                    batch_id=batch_id,
                    record=record,
                    supplier_counts=supplier_counts,
                    canonical_cnpjs=canonical_cnpjs,
                    supplier_values=supplier_values,
                    duplicate_index=duplicate_index,
                    approver_counts=approver_counts,
                    known_approvers=known_approvers,
                ),
            )

        return anomalies

    # Monta um registro normalizado para facilitar as regras de negocio.
    def _build_record(self, document: Document) -> dict[str, object]:
        extracted_data = _load_json(document.extracted_data, {})
        missing_fields = _load_json(document.missing_fields, [])
        if not isinstance(extracted_data, dict):
            extracted_data = {}
        if not isinstance(missing_fields, list):
            missing_fields = []

        supplier = str(extracted_data.get("fornecedor", ""))
        cnpj = str(extracted_data.get("cnpj_fornecedor", ""))
        approver = str(extracted_data.get("aprovado_por", ""))

        return {
            "document_id": document.id,
            "batch_id": document.batch_id,
            "file_name": document.file_name,
            "status": document.status,
            "decode_status": document.decode_status,
            "parse_status": document.parse_status,
            "extraction_status": document.extraction_status,
            "error_code": document.error_code,
            "error_message": document.error_message,
            "extracted_data": extracted_data,
            "missing_fields": missing_fields,
            "supplier_key": _canonical_supplier(supplier) if supplier and supplier != "nao_extraido" else "",
            "cnpj_key": _canonical_cnpj(cnpj) if cnpj and cnpj != "nao_extraido" else "",
            "approver_key": _canonical_supplier(approver) if approver and approver != "nao_extraido" else "",
            "document_number": str(extracted_data.get("numero_documento", "")).strip().upper(),
            "document_type": str(extracted_data.get("tipo_documento", "")).strip().upper(),
            "value": _parse_number(extracted_data.get("valor_bruto")),
            "payment_date": _parse_date(extracted_data.get("data_pagamento")),
            "invoice_date": _parse_date(extracted_data.get("data_emissao_nf")),
            "status_value": str(extracted_data.get("status", "")).strip().upper(),
            "is_valid": (
                document.status == "done"
                and document.extraction_status in {"success", "partial"}
                and str(extracted_data.get("tipo_documento", "")).strip().upper() in SUPPORTED_DOCUMENT_TYPES
            ),
        }

    # Executa todas as regras de anomalia para um documento normalizado.
    def _evaluate_record(
        self,
        *,
        batch_id: str,
        record: dict[str, object],
        supplier_counts: Counter[str],
        canonical_cnpjs: dict[str, str],
        supplier_values: dict[str, list[float]],
        duplicate_index: dict[tuple[str, str], list[dict[str, object]]],
        approver_counts: Counter[str],
        known_approvers: set[str],
    ) -> list[dict[str, object]]:
        anomalies: list[dict[str, object]] = []
        extracted_data = record["extracted_data"]
        assert isinstance(extracted_data, dict)

        if self._is_unprocessable(record):
            missing_fields = record["missing_fields"] if isinstance(record["missing_fields"], list) else []
            anomalies.append(
                self._build_anomaly(
                    record=record,
                    rule_code="ARQUIVO_NAO_PROCESSAVEL",
                    rule_name="Arquivo nao processavel",
                    severity=MEDIUM,
                    confidence=HIGH,
                    evidence_fields=["decode_status", "parse_status", "missing_fields"],
                    evidence_values={
                        "decode_status": record["decode_status"],
                        "parse_status": record["parse_status"],
                        "missing_fields": missing_fields,
                        "error_code": record["error_code"],
                    },
                    details=str(record["error_message"] or "Falha ao decodificar ou extrair campos obrigatorios."),
                ),
            )

        document_type = str(record["document_type"])
        if (
            record["status"] != "error"
            and document_type
            and document_type != "NAO_EXTRAIDO"
            and document_type not in SUPPORTED_DOCUMENT_TYPES
        ):
            anomalies.append(
                self._build_anomaly(
                    record=record,
                    rule_code="TIPO_DOCUMENTO_FORA_ESCOPO",
                    rule_name="Tipo de documento fora do escopo",
                    severity=MEDIUM,
                    confidence=HIGH,
                    evidence_fields=["tipo_documento"],
                    evidence_values={
                        "tipo_documento": extracted_data.get("tipo_documento"),
                        "tipos_suportados": sorted(SUPPORTED_DOCUMENT_TYPES),
                    },
                    details=f"O documento foi lido, mas o tipo {document_type} nao corresponde ao fluxo principal de NOTA_FISCAL.",
                ),
            )

        duplicate_key = (str(record["document_number"]), str(record["supplier_key"]))
        if duplicate_key[0] and duplicate_key[1] and len(duplicate_index.get(duplicate_key, [])) > 1:
            anomalies.append(
                self._build_anomaly(
                    record=record,
                    rule_code="NF_DUPLICADA",
                    rule_name="NF duplicada",
                    severity=HIGH,
                    confidence=HIGH,
                    evidence_fields=["numero_documento", "fornecedor"],
                    evidence_values={
                        "numero_documento": extracted_data.get("numero_documento"),
                        "fornecedor": extracted_data.get("fornecedor"),
                    },
                    details="Mesmo numero de NF encontrado para o mesmo fornecedor.",
                ),
            )

        supplier_key = str(record["supplier_key"])
        cnpj_key = str(record["cnpj_key"])
        canonical_cnpj = canonical_cnpjs.get(supplier_key)
        if supplier_key and cnpj_key and canonical_cnpj and cnpj_key != canonical_cnpj:
            anomalies.append(
                self._build_anomaly(
                    record=record,
                    rule_code="CNPJ_DIVERGENTE",
                    rule_name="CNPJ divergente",
                    severity=HIGH,
                    confidence=HIGH,
                    evidence_fields=["fornecedor", "cnpj_fornecedor"],
                    evidence_values={
                        "fornecedor": extracted_data.get("fornecedor"),
                        "cnpj_fornecedor": extracted_data.get("cnpj_fornecedor"),
                        "cnpj_canonico": canonical_cnpj,
                    },
                    details="CNPJ diverge do padrao mais frequente para o fornecedor.",
                ),
            )

        if supplier_key and supplier_counts.get(supplier_key, 0) == 1 and record["is_valid"]:
            anomalies.append(
                self._build_anomaly(
                    record=record,
                    rule_code="FORNECEDOR_SEM_HISTORICO",
                    rule_name="Fornecedor sem historico",
                    severity=HIGH,
                    confidence=MEDIUM,
                    evidence_fields=["fornecedor"],
                    evidence_values={"fornecedor": extracted_data.get("fornecedor")},
                    details="Fornecedor apareceu uma unica vez no universo processado.",
                ),
            )

        payment_date = record["payment_date"]
        invoice_date = record["invoice_date"]
        if isinstance(payment_date, datetime) and isinstance(invoice_date, datetime) and invoice_date > payment_date:
            anomalies.append(
                self._build_anomaly(
                    record=record,
                    rule_code="EMISSAO_APOS_PAGAMENTO",
                    rule_name="NF emitida apos pagamento",
                    severity=HIGH,
                    confidence=HIGH,
                    evidence_fields=["data_emissao_nf", "data_pagamento"],
                    evidence_values={
                        "data_emissao_nf": extracted_data.get("data_emissao_nf"),
                        "data_pagamento": extracted_data.get("data_pagamento"),
                    },
                    details="A data de emissao da NF eh posterior a data de pagamento.",
                ),
            )

        values = supplier_values.get(supplier_key, [])
        current_value = record["value"]
        if len(values) >= 3 and isinstance(current_value, float):
            q1, q3 = _quartiles(values)
            iqr = q3 - q1
            lower_bound = q1 - (1.5 * iqr)
            upper_bound = q3 + (1.5 * iqr)
            if current_value < lower_bound or current_value > upper_bound:
                anomalies.append(
                    self._build_anomaly(
                        record=record,
                        rule_code="VALOR_FORA_FAIXA",
                        rule_name="Valor fora da faixa do fornecedor",
                        severity=MEDIUM,
                        confidence=MEDIUM,
                        evidence_fields=["fornecedor", "valor_bruto"],
                        evidence_values={
                            "fornecedor": extracted_data.get("fornecedor"),
                            "valor_bruto": extracted_data.get("valor_bruto"),
                            "q1": q1,
                            "q3": q3,
                        },
                        details="Valor fora da faixa esperada usando IQR por fornecedor.",
                    ),
                )

        approver_key = str(record["approver_key"])
        if approver_key and approver_key not in known_approvers and approver_counts.get(approver_key, 0) < settings.approver_min_occurrences:
            anomalies.append(
                self._build_anomaly(
                    record=record,
                    rule_code="APROVADOR_NAO_RECONHECIDO",
                    rule_name="Aprovador nao reconhecido",
                    severity=MEDIUM,
                    confidence=MEDIUM,
                    evidence_fields=["aprovado_por"],
                    evidence_values={"aprovado_por": extracted_data.get("aprovado_por")},
                    details="Aprovador nao esta na allowlist e nao possui recorrencia minima.",
                ),
            )

        status_value = str(record["status_value"])
        if (status_value == "CANCELADO" and extracted_data.get("data_pagamento") not in {None, "", "nao_extraido"}) or (
            status_value == "PAGO" and extracted_data.get("data_pagamento") in {None, "", "nao_extraido"}
        ) or (status_value == "PENDENTE" and extracted_data.get("data_pagamento") not in {None, "", "nao_extraido"}):
            anomalies.append(
                self._build_anomaly(
                    record=record,
                    rule_code="STATUS_INCONSISTENTE",
                    rule_name="Status inconsistente",
                    severity=MEDIUM,
                    confidence=HIGH,
                    evidence_fields=["status", "data_pagamento"],
                    evidence_values={
                        "status": extracted_data.get("status"),
                        "data_pagamento": extracted_data.get("data_pagamento"),
                    },
                    details="Combinacao invalida entre status e data de pagamento.",
                ),
            )

        return anomalies

    # Decide se o documento deve ser tratado como nao processavel.
    def _is_unprocessable(self, record: dict[str, object]) -> bool:
        missing_fields = record["missing_fields"] if isinstance(record["missing_fields"], list) else []
        return bool(
            record["status"] == "error"
            or record["decode_status"] == "failed"
            or record["parse_status"] == "failed"
            or record["extraction_status"] == "failed"
            or any(field in self.required_fields for field in missing_fields)
        )

    # Monta o payload padrao persistido para uma anomalia.
    def _build_anomaly(
        self,
        *,
        record: dict[str, object],
        rule_code: str,
        rule_name: str,
        severity: str,
        confidence: str,
        evidence_fields: list[str],
        evidence_values: dict[str, object],
        details: str,
    ) -> dict[str, object]:
        return {
            "batch_id": record["batch_id"],
            "document_id": record["document_id"],
            "rule_code": rule_code,
            "rule_name": rule_name,
            "severity": severity,
            "confidence": confidence,
            "evidence_fields": evidence_fields,
            "evidence_values": evidence_values,
            "details": details,
        }
