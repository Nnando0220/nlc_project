from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models.audit_log import AuditLog


class AuditLogRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        *,
        batch_id: str,
        stage: str,
        status: str,
        message: str,
        document_id: str | None = None,
        payload_ref: str | None = None,
    ) -> AuditLog:
        audit_log = AuditLog(
            batch_id=batch_id,
            document_id=document_id,
            stage=stage,
            status=status,
            message=message,
            payload_ref=payload_ref,
        )
        self.db.add(audit_log)
        self.db.commit()
        self.db.refresh(audit_log)
        return audit_log

    def list_by_batch_id(self, batch_id: str) -> list[AuditLog]:
        return (
            self.db.query(AuditLog)
            .filter(AuditLog.batch_id == batch_id)
            .order_by(AuditLog.created_at.asc())
            .all()
        )
