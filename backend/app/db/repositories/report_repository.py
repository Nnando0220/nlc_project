from sqlalchemy.orm import Session

from app.db.models.report import Report


class ReportRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, report_id: str) -> Report | None:
        return self.db.query(Report).filter(Report.id == report_id).first()

    def create(self, batch_id: str, csv_path: str, report_type: str = "results") -> Report:
        report = Report(batch_id=batch_id, csv_path=csv_path, report_type=report_type)
        self.db.add(report)
        self.db.commit()
        self.db.refresh(report)
        return report
