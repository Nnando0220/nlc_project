from pydantic import BaseModel, Field


class NFAuditProviderIssueSummary(BaseModel):
    error_code: str
    count: int
    retryable: bool
    user_message: str
    provider: str | None
    http_status: int | None


class NFAuditProgressSummary(BaseModel):
    pending_files: int
    processing_files: int
    completed_files: int
    progress_percent: float
    estimated_remaining_seconds: int | None
    current_stage: str
    throughput_files_per_minute: float | None
    average_seconds_per_file: float | None
    local_parsed_files: int
    llm_queued_files: int
    llm_processing_files: int
    llm_completed_files: int
    llm_skipped_files: int
    llm_request_count: int
    llm_request_failures: int
    llm_fallback_count: int
    average_llm_request_seconds: float | None
    provider_issues: list[NFAuditProviderIssueSummary] = Field(default_factory=list)


class NFAuditUploadResponse(BaseModel):
    batch_id: str
    batch_name: str
    status: str
    total_files: int
    processed_files: int
    error_files: int
    anomaly_count: int
    progress: NFAuditProgressSummary


class NFAuditBatchResponse(BaseModel):
    batch_id: str
    batch_name: str
    status: str
    total_files: int
    processed_files: int
    successful_files: int
    error_files: int
    anomaly_count: int
    started_at: str | None
    finished_at: str | None
    progress: NFAuditProgressSummary


class NFAuditBatchProgressDocument(BaseModel):
    document_id: str
    file_name: str
    status: str
    current_stage: str
    decode_status: str
    parse_status: str
    extraction_status: str
    error_code: str | None
    processed_at: str | None


class NFAuditBatchProgressResponse(BaseModel):
    batch_id: str
    batch_name: str
    status: str
    total_files: int
    processed_files: int
    successful_files: int
    error_files: int
    anomaly_count: int
    started_at: str | None
    finished_at: str | None
    progress: NFAuditProgressSummary
    documents: list[NFAuditBatchProgressDocument]


class NFAuditAnomalyResponse(BaseModel):
    id: str
    document_id: str
    file_name: str
    rule_code: str
    rule_name: str
    severity: str
    confidence: str
    evidence_fields: list[str]
    evidence_values: dict
    details: str | None
    created_at: str


class NFAuditDocumentResponse(BaseModel):
    id: str
    file_name: str
    file_path: str
    source_type: str
    mime_type: str | None
    file_size_bytes: int
    status: str
    decode_status: str
    parse_status: str
    extraction_status: str
    error_code: str | None
    error_message: str | None
    processed_at: str | None
    extracted_data: dict
    missing_fields: list[str]
    truncated_fields: list[str]
    anomalies: list[NFAuditAnomalyResponse]
    analysis_summary: str | None
    llm_provider: str | None
    llm_model: str | None
    llm_requested_model: str | None
    llm_fallback_used: bool | None
    llm_attempted_models: list[str]
    prompt_version: str | None


class NFAuditDocumentListResponse(BaseModel):
    items: list[NFAuditDocumentResponse]
    total: int
    skip: int
    limit: int


class NFAuditAnomalyListResponse(BaseModel):
    items: list[NFAuditAnomalyResponse]
    total: int
    skip: int
    limit: int
