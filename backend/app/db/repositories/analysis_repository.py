from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.db.models.analysis import AIAnalysis


class AnalysisRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_document_id(self, document_id: str) -> AIAnalysis | None:
        return self.db.query(AIAnalysis).filter(AIAnalysis.document_id == document_id).first()

    def upsert(self, document_id: str, **fields: object) -> AIAnalysis:
        analysis = self.get_by_document_id(document_id)
        serialized_fields: dict[str, object] = {}
        for key, value in fields.items():
            if key in {"inconsistencies", "missing_fields", "truncated_fields", "attempted_models"} and value is not None and not isinstance(value, str):
                serialized_fields[key] = json.dumps(value, ensure_ascii=False)
            else:
                serialized_fields[key] = value

        if analysis is None:
            analysis = AIAnalysis(document_id=document_id, **serialized_fields)
            self.db.add(analysis)
        else:
            for key, value in serialized_fields.items():
                setattr(analysis, key, value)
            self.db.add(analysis)

        self.db.commit()
        self.db.refresh(analysis)
        return analysis
