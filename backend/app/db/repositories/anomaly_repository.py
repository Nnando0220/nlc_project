from __future__ import annotations

import json

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.models.anomaly import Anomaly
from app.db.models.document import Document


class AnomalyRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_by_batch_id(
        self,
        batch_id: str,
        *,
        rule_code: str | None = None,
        severity: str | None = None,
        search: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Anomaly]:
        query = self.db.query(Anomaly).filter(Anomaly.batch_id == batch_id)
        if rule_code:
            query = query.filter(Anomaly.rule_code == rule_code)
        if severity:
            query = query.filter(Anomaly.severity == severity)
        if search:
            pattern = f"%{search.strip()}%"
            query = query.join(Document, Document.id == Anomaly.document_id).filter(
                or_(
                    Anomaly.rule_code.ilike(pattern),
                    Anomaly.rule_name.ilike(pattern),
                    Anomaly.details.ilike(pattern),
                    Document.file_name.ilike(pattern),
                    Document.extracted_data.ilike(pattern),
                )
            )
        return query.order_by(Anomaly.created_at.asc()).offset(skip).limit(limit).all()

    def count_by_batch_id(
        self,
        batch_id: str,
        *,
        rule_code: str | None = None,
        severity: str | None = None,
        search: str | None = None,
    ) -> int:
        query = self.db.query(Anomaly).filter(Anomaly.batch_id == batch_id)
        if rule_code:
            query = query.filter(Anomaly.rule_code == rule_code)
        if severity:
            query = query.filter(Anomaly.severity == severity)
        if search:
            pattern = f"%{search.strip()}%"
            query = query.join(Document, Document.id == Anomaly.document_id).filter(
                or_(
                    Anomaly.rule_code.ilike(pattern),
                    Anomaly.rule_name.ilike(pattern),
                    Anomaly.details.ilike(pattern),
                    Document.file_name.ilike(pattern),
                    Document.extracted_data.ilike(pattern),
                )
            )
        return query.count()

    def delete_by_batch_id(self, batch_id: str) -> None:
        self.db.query(Anomaly).filter(Anomaly.batch_id == batch_id).delete(synchronize_session=False)
        self.db.commit()

    def create_many(self, batch_id: str, anomalies: list[dict[str, object]]) -> list[Anomaly]:
        items: list[Anomaly] = []
        for item in anomalies:
            anomaly = Anomaly(
                batch_id=batch_id,
                document_id=str(item["document_id"]),
                rule_code=str(item["rule_code"]),
                rule_name=str(item["rule_name"]),
                severity=str(item["severity"]),
                confidence=str(item["confidence"]),
                evidence_fields=json.dumps(item.get("evidence_fields", []), ensure_ascii=False),
                evidence_values=json.dumps(item.get("evidence_values", {}), ensure_ascii=False),
                details=str(item.get("details", "")),
            )
            self.db.add(anomaly)
            items.append(anomaly)
        self.db.commit()
        for anomaly in items:
            self.db.refresh(anomaly)
        return items

    def list_by_document_id(self, document_id: str) -> list[Anomaly]:
        return self.db.query(Anomaly).filter(Anomaly.document_id == document_id).order_by(Anomaly.created_at.asc()).all()
