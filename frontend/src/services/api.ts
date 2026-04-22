// No servidor, o Next.js pode usar a URL interna da API; no navegador,
// o frontend precisa usar a URL publica exposta ao usuario.
export const API_BASE_URL =
  (typeof window === "undefined"
    ? process.env.INTERNAL_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL
    : process.env.NEXT_PUBLIC_API_BASE_URL) ?? "http://localhost:8000/api/v1";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export interface ProviderIssueSummary {
  error_code: string;
  count: number;
  retryable: boolean;
  user_message: string;
  provider: string | null;
  http_status: number | null;
}

export interface ProgressSummary {
  pending_files: number;
  processing_files: number;
  completed_files: number;
  progress_percent: number;
  estimated_remaining_seconds: number | null;
  current_stage: string;
  throughput_files_per_minute: number | null;
  average_seconds_per_file: number | null;
  local_parsed_files: number;
  llm_queued_files: number;
  llm_processing_files: number;
  llm_completed_files: number;
  llm_skipped_files: number;
  llm_request_count: number;
  llm_request_failures: number;
  llm_fallback_count: number;
  average_llm_request_seconds: number | null;
  provider_issues: ProviderIssueSummary[];
}

export interface UploadBatchResponse {
  batch_id: string;
  batch_name: string;
  status: string;
  total_files: number;
  processed_files: number;
  error_files: number;
  anomaly_count: number;
  progress: ProgressSummary;
}

export interface BatchResponse {
  batch_id: string;
  batch_name: string;
  status: string;
  total_files: number;
  processed_files: number;
  successful_files: number;
  error_files: number;
  anomaly_count: number;
  started_at: string | null;
  finished_at: string | null;
  progress: ProgressSummary;
}

export interface BatchProgressDocument {
  document_id: string;
  file_name: string;
  status: string;
  current_stage: string;
  decode_status: string;
  parse_status: string;
  extraction_status: string;
  error_code: string | null;
  processed_at: string | null;
}

export interface BatchProgressResponse extends BatchResponse {
  documents: BatchProgressDocument[];
}

export interface AnomalyItem {
  id: string;
  document_id: string;
  file_name: string;
  rule_code: string;
  rule_name: string;
  severity: string;
  confidence: string;
  evidence_fields: string[];
  evidence_values: Record<string, unknown>;
  details: string | null;
  created_at: string;
}

export interface DocumentItem {
  id: string;
  file_name: string;
  file_path: string;
  source_type: string;
  mime_type: string | null;
  file_size_bytes: number;
  status: string;
  decode_status: string;
  parse_status: string;
  extraction_status: string;
  error_code: string | null;
  error_message: string | null;
  processed_at: string | null;
  extracted_data: Record<string, unknown>;
  missing_fields: string[];
  truncated_fields: string[];
  anomalies: AnomalyItem[];
  analysis_summary: string | null;
  llm_provider: string | null;
  llm_model: string | null;
  llm_requested_model: string | null;
  llm_fallback_used: boolean | null;
  llm_attempted_models: string[];
  prompt_version: string | null;
}

export interface DocumentFilters {
  search?: string;
  status?: string;
  extractionStatus?: string;
  decodeStatus?: string;
  hasAnomaly?: boolean | null;
}

export interface AnomalyFilters {
  search?: string;
  ruleCode?: string;
  severity?: string;
}

export interface PagedResponse<T> {
  items: T[];
  total: number;
  skip: number;
  limit: number;
}

export interface ReportResponse {
  report_id: string;
  batch_id: string;
  csv_path: string;
  report_type: string;
}

function buildUrl(path: string): string {
  return `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

async function request(path: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(buildUrl(path), init);
  } catch {
    throw new ApiError(
      "Nao foi possivel se comunicar com a API. Verifique se o backend esta online e se esta origem foi liberada no CORS.",
      0,
    );
  }
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (response.ok) {
    if (response.headers.get("content-type")?.includes("application/json")) {
      return (await response.json()) as T;
    }
    return {} as T;
  }

  let detail = `Erro HTTP: ${response.status}`;
  try {
    const payload = (await response.json()) as { detail?: string };
    if (payload?.detail) {
      detail = payload.detail;
    }
  } catch {
    // Ignora respostas sem corpo JSON.
  }
  throw new ApiError(detail, response.status);
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await request(path, { cache: "no-store" });
  return parseResponse<T>(response);
}

export async function apiPost<T>(path: string): Promise<T> {
  const response = await request(path, { method: "POST" });
  return parseResponse<T>(response);
}

export async function apiUploadBatch(
  files: File[],
  batchName?: string,
): Promise<UploadBatchResponse> {
  const form = new FormData();
  if (batchName?.trim()) {
    form.append("batch_name", batchName.trim());
  }
  files.forEach((file) => form.append("files", file));

  const response = await request("/nf-audits/uploads", {
    method: "POST",
    body: form,
  });
  return parseResponse<UploadBatchResponse>(response);
}

export function getBatch(batchId: string): Promise<BatchResponse> {
  return apiGet<BatchResponse>(`/nf-audits/batches/${batchId}`);
}

export function getBatchProgress(batchId: string): Promise<BatchProgressResponse> {
  return apiGet<BatchProgressResponse>(`/nf-audits/batches/${batchId}/progress`);
}

export function getBatchDocuments(
  batchId: string,
  skip = 0,
  limit = 20,
  filters: DocumentFilters = {},
): Promise<PagedResponse<DocumentItem>> {
  const params = new URLSearchParams({
    skip: String(skip),
    limit: String(limit),
  });
  if (filters.search?.trim()) {
    params.set("search", filters.search.trim());
  }
  if (filters.status?.trim()) {
    params.set("status", filters.status.trim());
  }
  if (filters.extractionStatus?.trim()) {
    params.set("extraction_status", filters.extractionStatus.trim());
  }
  if (filters.decodeStatus?.trim()) {
    params.set("decode_status", filters.decodeStatus.trim());
  }
  if (filters.hasAnomaly !== undefined && filters.hasAnomaly !== null) {
    params.set("has_anomaly", String(filters.hasAnomaly));
  }
  return apiGet<PagedResponse<DocumentItem>>(`/nf-audits/batches/${batchId}/documents?${params.toString()}`);
}

export function getBatchAnomalies(
  batchId: string,
  skip = 0,
  limit = 20,
  filters: AnomalyFilters = {},
): Promise<PagedResponse<AnomalyItem>> {
  const params = new URLSearchParams({
    skip: String(skip),
    limit: String(limit),
  });
  if (filters.ruleCode?.trim()) {
    params.set("rule_code", filters.ruleCode.trim());
  }
  if (filters.severity?.trim()) {
    params.set("severity", filters.severity.trim());
  }
  if (filters.search?.trim()) {
    params.set("search", filters.search.trim());
  }
  return apiGet<PagedResponse<AnomalyItem>>(
    `/nf-audits/batches/${batchId}/anomalies?${params.toString()}`,
  );
}

export function cancelBatch(batchId: string): Promise<BatchResponse> {
  return apiPost<BatchResponse>(`/nf-audits/batches/${batchId}/cancel`);
}

export function exportResults(batchId: string): Promise<ReportResponse> {
  return apiPost<ReportResponse>(`/nf-audits/batches/${batchId}/exports/results.csv`);
}

export function exportAudit(batchId: string): Promise<ReportResponse> {
  return apiPost<ReportResponse>(`/nf-audits/batches/${batchId}/exports/audit.csv`);
}

export function exportAnomalies(batchId: string): Promise<ReportResponse> {
  return apiPost<ReportResponse>(`/nf-audits/batches/${batchId}/exports/anomalies.csv`);
}

export function buildReportDownloadUrl(reportId: string): string {
  return buildUrl(`/nf-audits/reports/${reportId}/download`);
}

export function isBatchActive(status: string): boolean {
  return ["pending", "processing", "cancelling"].includes(status);
}
