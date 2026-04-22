from pydantic import BaseModel


class GenerateReportResponse(BaseModel):
    report_id: str
    batch_id: str
    csv_path: str
    report_type: str = "results"
