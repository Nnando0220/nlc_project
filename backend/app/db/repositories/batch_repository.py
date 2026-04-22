from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models.batch import DocumentBatch


class BatchRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, batch_id: str) -> DocumentBatch | None:
        return self.db.query(DocumentBatch).filter(DocumentBatch.id == batch_id).first()

    def create(self, batch_name: str, total_files: int) -> DocumentBatch:
        batch = DocumentBatch(batch_name=batch_name, total_files=total_files, status="pending")
        self.db.add(batch)
        self.db.commit()
        self.db.refresh(batch)
        return batch

    def update(self, batch: DocumentBatch, **fields: object) -> DocumentBatch:
        for key, value in fields.items():
            setattr(batch, key, value)
        self.db.add(batch)
        self.db.commit()
        self.db.refresh(batch)
        return batch

    def mark_processing_started(self, batch: DocumentBatch) -> DocumentBatch:
        return self.update(
            batch,
            status="processing",
            started_at=batch.started_at or datetime.now(timezone.utc),
        )

    def mark_cancelling(self, batch: DocumentBatch) -> DocumentBatch:
        return self.update(batch, status="cancelling")

    def mark_cancelled(
        self,
        batch: DocumentBatch,
        *,
        processed_files: int,
        successful_files: int,
        error_files: int,
        anomaly_count: int,
    ) -> DocumentBatch:
        return self.update(
            batch,
            processed_files=processed_files,
            successful_files=successful_files,
            error_files=error_files,
            anomaly_count=anomaly_count,
            status="cancelled",
            finished_at=datetime.now(timezone.utc),
        )

    def finalize(
        self,
        batch: DocumentBatch,
        *,
        processed_files: int,
        successful_files: int,
        error_files: int,
        anomaly_count: int,
        status: str,
    ) -> DocumentBatch:
        return self.update(
            batch,
            processed_files=processed_files,
            successful_files=successful_files,
            error_files=error_files,
            anomaly_count=anomaly_count,
            status=status,
            finished_at=datetime.now(timezone.utc),
        )
