from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.models.document import Document


class DocumentRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, document_id: str) -> Document | None:
        return self.db.query(Document).filter(Document.id == document_id).first()

    def _apply_batch_filters(
        self,
        query,
        *,
        batch_id: str,
        search: str | None = None,
        status: str | None = None,
        extraction_status: str | None = None,
        decode_status: str | None = None,
        has_anomaly: bool | None = None,
    ):
        query = query.filter(Document.batch_id == batch_id)

        if status:
            query = query.filter(Document.status == status)
        if extraction_status:
            query = query.filter(Document.extraction_status == extraction_status)
        if decode_status:
            query = query.filter(Document.decode_status == decode_status)
        if has_anomaly is True:
            query = query.filter(Document.anomalies.any())
        elif has_anomaly is False:
            query = query.filter(~Document.anomalies.any())
        if search:
            pattern = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    Document.file_name.ilike(pattern),
                    Document.error_code.ilike(pattern),
                    Document.error_message.ilike(pattern),
                    Document.extracted_data.ilike(pattern),
                )
            )
        return query

    def list_by_batch_id(
        self,
        batch_id: str,
        *,
        search: str | None = None,
        status: str | None = None,
        extraction_status: str | None = None,
        decode_status: str | None = None,
        has_anomaly: bool | None = None,
        skip: int = 0,
        limit: int = 20,
    ) -> list[Document]:
        query = self._apply_batch_filters(
            self.db.query(Document),
            batch_id=batch_id,
            search=search,
            status=status,
            extraction_status=extraction_status,
            decode_status=decode_status,
            has_anomaly=has_anomaly,
        )
        return query.order_by(Document.created_at.asc(), Document.file_name.asc()).offset(skip).limit(limit).all()

    def list_all_by_batch_id(self, batch_id: str) -> list[Document]:
        return (
            self.db.query(Document)
            .filter(Document.batch_id == batch_id)
            .order_by(Document.created_at.asc(), Document.file_name.asc())
            .all()
        )

    def count_by_batch_id(
        self,
        batch_id: str,
        *,
        search: str | None = None,
        status: str | None = None,
        extraction_status: str | None = None,
        decode_status: str | None = None,
        has_anomaly: bool | None = None,
    ) -> int:
        query = self._apply_batch_filters(
            self.db.query(Document),
            batch_id=batch_id,
            search=search,
            status=status,
            extraction_status=extraction_status,
            decode_status=decode_status,
            has_anomaly=has_anomaly,
        )
        return query.count()

    def create(
        self,
        batch_id: str,
        file_name: str,
        file_path: str,
        extracted_text: str | None = None,
        **extra_fields: object,
    ) -> Document:
        document = Document(
            batch_id=batch_id,
            file_name=file_name,
            file_path=file_path,
            extracted_text=extracted_text,
            **extra_fields,
        )
        self.db.add(document)
        self.db.commit()
        self.db.refresh(document)
        return document

    def update(self, document: Document, **fields: object) -> Document:
        for key, value in fields.items():
            if key in {"extracted_data", "missing_fields", "truncated_fields"} and value is not None and not isinstance(value, str):
                setattr(document, key, json.dumps(value, ensure_ascii=False))
            else:
                setattr(document, key, value)
        self.db.add(document)
        self.db.commit()
        self.db.refresh(document)
        return document

    def update_processing_result(
        self,
        document: Document,
        *,
        raw_text: str | None,
        extracted_text: str | None,
        extracted_data: dict | None,
        missing_fields: list[str],
        truncated_fields: list[str],
        decode_status: str,
        parse_status: str,
        extraction_status: str,
        error_code: str | None,
        error_message: str | None,
        status: str,
    ) -> Document:
        return self.update(
            document,
            raw_text=raw_text,
            extracted_text=extracted_text,
            extracted_data=extracted_data,
            missing_fields=missing_fields,
            truncated_fields=truncated_fields,
            decode_status=decode_status,
            parse_status=parse_status,
            extraction_status=extraction_status,
            error_code=error_code,
            error_message=error_message,
            status=status,
            processed_at=datetime.now(timezone.utc),
        )

    def update_status(self, document: Document, status: str) -> Document:
        processed_at = datetime.now(timezone.utc) if status in {"done", "error"} else document.processed_at
        return self.update(document, status=status, processed_at=processed_at)
