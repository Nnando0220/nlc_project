"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import {
  Activity,
  Bot,
  Clock3,
  Download,
  FileSearch,
  Gauge,
  LoaderCircle,
  RefreshCcw,
  Search,
  ShieldAlert,
  Trash2,
  XCircle,
} from "lucide-react";

import { MetricCard } from "@/components/app/metric-card";
import { PageShell } from "@/components/app/page-shell";
import { StatusBadge } from "@/components/app/status-badge";
import { RecentBatch, getMostRecentBatch, listRecentBatches, removeRecentBatch, restoreRecentBatch, saveRecentBatch } from "@/lib/recent-batches";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  AnomalyItem,
  ApiError,
  BatchProgressResponse,
  DocumentItem,
  cancelBatch,
  getBatchAnomalies,
  getBatchDocuments,
  getBatchProgress,
  isBatchActive,
} from "@/services/api";

const PAGE_SIZE = 20;
const JOURNEY_STEPS = [
  {
    key: "queued",
    title: "1. Lote recebido",
    description: "Arquivos aceitos e preparados para o processamento.",
  },
  {
    key: "local_parsing",
    title: "2. Leitura local",
    description: "Campos basicos e estrutura do documento sendo lidos.",
  },
  {
    key: "llm_validation",
    title: "3. Validacao por IA",
    description: "Modelos externos revisam, normalizam e complementam o que for necessario.",
  },
  {
    key: "completed",
    title: "4. Revisao e entrega",
    description: "Documentos, anomalias e exportacoes ficam disponiveis.",
  },
];

function toBooleanFilter(value: string): boolean | null {
  if (value === "true") return true;
  if (value === "false") return false;
  return null;
}

function formatDate(value: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("pt-BR");
}

function formatNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return "-";
  return value.toLocaleString("pt-BR", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits > 0 ? 0 : 0,
  });
}

function formatSeconds(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return "-";
  }
  if (value < 60) {
    return `${value}s`;
  }
  const minutes = Math.floor(value / 60);
  const seconds = value % 60;
  return `${minutes}min ${seconds}s`;
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  if (typeof value === "number") {
    return value.toLocaleString("pt-BR");
  }
  if (typeof value === "boolean") {
    return value ? "Sim" : "Nao";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function formatCurrency(value: unknown): string | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
    }
  }
  return null;
}

function describeAnomaly(anomaly: AnomalyItem): string {
  if (anomaly.rule_code === "VALOR_FORA_FAIXA") {
    const supplier = formatValue(anomaly.evidence_values.fornecedor);
    const currentValue = formatCurrency(anomaly.evidence_values.valor_bruto);
    const q1 = formatCurrency(anomaly.evidence_values.q1);
    const q3 = formatCurrency(anomaly.evidence_values.q3);

    if (supplier !== "-" && currentValue && q1 && q3) {
      return `${supplier} costuma operar entre ${q1} e ${q3}; este documento veio com ${currentValue}, por isso entrou como valor fora da faixa.`;
    }

    return "O valor deste documento ficou fora do comportamento historico esperado para esse fornecedor.";
  }

  return anomaly.details ?? "-";
}

function EmptyState({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="flex min-h-52 flex-col items-center justify-center gap-3 rounded-3xl border border-dashed bg-muted/20 px-6 text-center">
      <div className="rounded-full border bg-background p-3">
        <Search className="size-5 text-muted-foreground" />
      </div>
      <div className="space-y-1">
        <p className="font-medium text-foreground">{title}</p>
        <p className="max-w-xl text-sm text-muted-foreground">{description}</p>
      </div>
    </div>
  );
}

function DocumentDetails({ document }: { document: DocumentItem | null }) {
  if (!document) {
    return (
      <Card className="border-border/70 shadow-sm">
        <CardHeader>
          <CardTitle className="text-xl">Detalhe do documento</CardTitle>
          <CardDescription>
            Selecione um documento na tabela para ver os campos extraidos, alertas e resumo da analise.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const extractedEntries = Object.entries(document.extracted_data ?? {});

  return (
    <Card className="border-border/70 shadow-sm">
      <CardHeader>
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div>
            <CardTitle className="text-xl">Detalhe do documento</CardTitle>
            <CardDescription>{document.file_name}</CardDescription>
          </div>
          <div className="flex flex-wrap gap-2">
            <StatusBadge value={document.status} />
            <StatusBadge value={document.extraction_status} />
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        {document.error_message ? (
          <Alert variant="destructive">
            <ShieldAlert className="size-4" />
            <AlertTitle>Documento com alerta</AlertTitle>
            <AlertDescription>{document.error_message}</AlertDescription>
          </Alert>
        ) : null}

        <div className="grid gap-4 xl:grid-cols-[0.8fr_1.2fr]">
          <div className="grid gap-4">
            <div className="rounded-3xl border bg-muted/20 p-4 text-sm">
              <p className="text-xs font-medium uppercase tracking-[0.24em] text-muted-foreground">
                resumo da analise
              </p>
              <p className="mt-2 text-sm text-foreground">
                {document.analysis_summary || "Sem resumo adicional."}
              </p>
            </div>
            <div className="rounded-3xl border bg-muted/20 p-4 text-sm">
              <p className="text-xs font-medium uppercase tracking-[0.24em] text-muted-foreground">
                metadados operacionais
              </p>
              <div className="mt-3 grid gap-2 text-muted-foreground">
                <p>Processado em: {formatDate(document.processed_at)}</p>
                <p>Fonte: {document.source_type}</p>
                <p>Arquivo: {document.file_size_bytes.toLocaleString("pt-BR")} bytes</p>
                <p>IA: {document.llm_model ?? document.llm_provider ?? "parser local"}</p>
                <p>Prompt: {document.prompt_version ?? "-"}</p>
              </div>
            </div>
            <div className="rounded-3xl border bg-muted/20 p-4 text-sm">
              <p className="text-xs font-medium uppercase tracking-[0.24em] text-muted-foreground">
                campos com alerta
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                {document.missing_fields.length > 0 ? (
                  document.missing_fields.map((field) => (
                    <Badge key={`missing-${field}`} variant="secondary">
                      ausente: {field}
                    </Badge>
                  ))
                ) : (
                  <Badge variant="outline">Sem campos ausentes</Badge>
                )}
                {document.truncated_fields.map((field) => (
                  <Badge key={`truncated-${field}`} variant="secondary">
                    truncado: {field}
                  </Badge>
                ))}
              </div>
            </div>
          </div>

          <div className="rounded-3xl border bg-background">
            <div className="border-b px-4 py-3">
              <p className="font-medium text-foreground">Campos extraidos</p>
              <p className="text-sm text-muted-foreground">
                Estes sao os dados que o usuario pode revisar antes de exportar.
              </p>
            </div>
            <div className="grid gap-3 p-4 md:grid-cols-2">
              {extractedEntries.map(([field, value]) => (
                <div key={field} className="rounded-2xl border bg-muted/15 p-3">
                  <p className="text-xs font-medium uppercase tracking-[0.24em] text-muted-foreground">
                    {field}
                  </p>
                  <p className="mt-2 text-sm text-foreground">{formatValue(value)}</p>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="rounded-3xl border bg-muted/20 p-4">
          <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="font-medium text-foreground">Anomalias do documento</p>
              <p className="text-sm text-muted-foreground">
                Regras disparadas especificamente para este item.
              </p>
            </div>
            <Badge variant="outline">{document.anomalies.length} registro(s)</Badge>
          </div>
          <div className="mt-4 grid gap-3">
            {document.anomalies.length > 0 ? (
              document.anomalies.map((anomaly) => (
                <div key={anomaly.id} className="rounded-2xl border bg-background p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-medium text-foreground">{anomaly.rule_name}</p>
                    <StatusBadge value={anomaly.severity} />
                    <Badge variant="outline">confianca {anomaly.confidence}</Badge>
                  </div>
                  <p className="mt-2 text-sm text-muted-foreground">{describeAnomaly(anomaly)}</p>
                </div>
              ))
            ) : (
              <p className="text-sm text-muted-foreground">
                Nenhuma anomalia registrada para o documento selecionado.
              </p>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function DashboardPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialBatchId = searchParams.get("batchId") ?? "";

  const [batchIdInput, setBatchIdInput] = useState("");
  const [activeBatchId, setActiveBatchId] = useState("");
  const [batch, setBatch] = useState<BatchProgressResponse | null>(null);
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [documentsTotal, setDocumentsTotal] = useState(0);
  const [anomalies, setAnomalies] = useState<AnomalyItem[]>([]);
  const [anomaliesTotal, setAnomaliesTotal] = useState(0);
  const [documentsSkip, setDocumentsSkip] = useState(0);
  const [anomaliesSkip, setAnomaliesSkip] = useState(0);
  const [documentSearchFilter, setDocumentSearchFilter] = useState("");
  const [documentStatusFilter, setDocumentStatusFilter] = useState("");
  const [documentExtractionFilter, setDocumentExtractionFilter] = useState("");
  const [documentDecodeFilter, setDocumentDecodeFilter] = useState("");
  const [documentHasAnomalyFilter, setDocumentHasAnomalyFilter] = useState("all");
  const [appliedDocumentSearchFilter, setAppliedDocumentSearchFilter] = useState("");
  const [appliedDocumentStatusFilter, setAppliedDocumentStatusFilter] = useState("");
  const [appliedDocumentExtractionFilter, setAppliedDocumentExtractionFilter] = useState("");
  const [appliedDocumentDecodeFilter, setAppliedDocumentDecodeFilter] = useState("");
  const [appliedDocumentHasAnomalyFilter, setAppliedDocumentHasAnomalyFilter] = useState("all");
  const [anomalySearchFilter, setAnomalySearchFilter] = useState("");
  const [severityFilter, setSeverityFilter] = useState("");
  const [ruleCodeFilter, setRuleCodeFilter] = useState("");
  const [appliedAnomalySearchFilter, setAppliedAnomalySearchFilter] = useState("");
  const [appliedSeverityFilter, setAppliedSeverityFilter] = useState("");
  const [appliedRuleCodeFilter, setAppliedRuleCodeFilter] = useState("");
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [recentBatches, setRecentBatches] = useState<RecentBatch[]>([]);
  const [selectedDocumentId, setSelectedDocumentId] = useState<string | null>(null);
  const [activePanel, setActivePanel] = useState<"overview" | "documents" | "details" | "anomalies">("overview");
  const [recentHydrated, setRecentHydrated] = useState(false);

  async function loadBatchProgress(
    targetBatchId: string,
    options: { showLoading?: boolean; clearError?: boolean } = {},
  ) {
    if (!targetBatchId.trim()) return;

    const showLoading = options.showLoading ?? true;
    const clearError = options.clearError ?? true;
    if (showLoading) {
      setLoading(true);
    }
    if (clearError) {
      setError(null);
    }
    try {
      const batchResponse = await getBatchProgress(targetBatchId);
      setBatch(batchResponse);
      setLastUpdated(new Date().toLocaleTimeString("pt-BR"));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Falha ao consultar o lote.");
    } finally {
      if (showLoading) {
        setLoading(false);
      }
    }
  }

  async function loadDocumentsPanel(
    targetBatchId: string,
    options: { showLoading?: boolean; clearError?: boolean } = {},
  ) {
    if (!targetBatchId.trim()) return;

    const showLoading = options.showLoading ?? true;
    const clearError = options.clearError ?? false;
    if (showLoading) {
      setLoading(true);
    }
    if (clearError) {
      setError(null);
    }
    try {
      const documentsResponse = await getBatchDocuments(targetBatchId, documentsSkip, PAGE_SIZE, {
        search: appliedDocumentSearchFilter,
        status: appliedDocumentStatusFilter,
        extractionStatus: appliedDocumentExtractionFilter,
        decodeStatus: appliedDocumentDecodeFilter,
        hasAnomaly: toBooleanFilter(appliedDocumentHasAnomalyFilter),
      });
      setDocuments(documentsResponse.items);
      setDocumentsTotal(documentsResponse.total);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Falha ao consultar os documentos do lote.");
    } finally {
      if (showLoading) {
        setLoading(false);
      }
    }
  }

  async function loadAnomaliesPanel(
    targetBatchId: string,
    options: { showLoading?: boolean; clearError?: boolean } = {},
  ) {
    if (!targetBatchId.trim()) return;

    const showLoading = options.showLoading ?? true;
    const clearError = options.clearError ?? false;
    if (showLoading) {
      setLoading(true);
    }
    if (clearError) {
      setError(null);
    }
    try {
      const anomaliesResponse = await getBatchAnomalies(
        targetBatchId,
        anomaliesSkip,
        PAGE_SIZE,
        {
          search: appliedAnomalySearchFilter,
          ruleCode: appliedRuleCodeFilter,
          severity: appliedSeverityFilter,
        },
      );
      setAnomalies(anomaliesResponse.items);
      setAnomaliesTotal(anomaliesResponse.total);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Falha ao consultar as anomalias do lote.");
    } finally {
      if (showLoading) {
        setLoading(false);
      }
    }
  }

  async function refreshActiveView(
    targetBatchId: string,
    options: { showLoading?: boolean; clearError?: boolean } = {},
  ) {
    // O polling de progresso fica leve: atualiza primeiro o resumo do lote
    // e so busca tabelas maiores quando a aba correspondente estiver aberta.
    await loadBatchProgress(targetBatchId, options);
    if (activePanel === "documents" || activePanel === "details") {
      await loadDocumentsPanel(targetBatchId, { showLoading: false, clearError: false });
    }
    if (activePanel === "anomalies") {
      await loadAnomaliesPanel(targetBatchId, { showLoading: false, clearError: false });
    }
  }

  useEffect(() => {
    const nextBatchId = initialBatchId.trim();
    if (nextBatchId) {
      setBatchIdInput(nextBatchId);
      setActiveBatchId(nextBatchId);
      setRecentHydrated(true);
      return;
    }

    const recent = getMostRecentBatch();
    setRecentBatches(listRecentBatches());
    if (recent) {
      setBatchIdInput(recent.batchId);
      setActiveBatchId(recent.batchId);
      router.replace(`/dashboard?batchId=${recent.batchId}`);
    }
    setRecentHydrated(true);
  }, [initialBatchId, router]);

  useEffect(() => {
    if (!activeBatchId) return;
    void loadBatchProgress(activeBatchId);
  }, [
    activeBatchId,
  ]);

  useEffect(() => {
    if (!activeBatchId || !batch || !autoRefresh || !isBatchActive(batch.status)) return;
    // O auto-refresh consulta apenas /progress para evitar varias leituras
    // de documentos e anomalias enquanto o usuario so acompanha o andamento.
    const timer = window.setInterval(() => {
      void loadBatchProgress(activeBatchId, { showLoading: false, clearError: false });
    }, 4000);
    return () => window.clearInterval(timer);
  }, [
    activeBatchId,
    batch,
    autoRefresh,
  ]);

  useEffect(() => {
    if (!activeBatchId) return;
    if (activePanel !== "documents" && activePanel !== "details") return;
    // Documentos sao carregados sob demanda ao abrir a aba ou trocar filtros.
    void loadDocumentsPanel(activeBatchId);
  }, [
    activeBatchId,
    documentsSkip,
    appliedDocumentExtractionFilter,
    appliedDocumentHasAnomalyFilter,
    appliedDocumentSearchFilter,
    appliedDocumentDecodeFilter,
    appliedDocumentStatusFilter,
    activePanel,
  ]);

  useEffect(() => {
    if (!activeBatchId) return;
    if (activePanel !== "anomalies") return;
    // Anomalias tambem ficam sob demanda para evitar leituras desnecessarias.
    void loadAnomaliesPanel(activeBatchId);
  }, [
    activeBatchId,
    anomaliesSkip,
    appliedAnomalySearchFilter,
    appliedRuleCodeFilter,
    appliedSeverityFilter,
    activePanel,
  ]);

  useEffect(() => {
    if (!batch) return;
    setRecentBatches(
      saveRecentBatch({
        batchId: batch.batch_id,
        batchName: batch.batch_name,
        status: batch.status,
        totalFiles: batch.total_files,
        createdAt: batch.started_at ?? undefined,
      }),
    );
  }, [batch]);

  useEffect(() => {
    if (documents.length === 0) {
      setSelectedDocumentId(null);
      return;
    }
    if (!selectedDocumentId || !documents.some((item) => item.id === selectedDocumentId)) {
      setSelectedDocumentId(documents[0].id);
    }
  }, [documents, selectedDocumentId]);

  const documentRange = useMemo(() => {
    if (documentsTotal === 0) return "0-0";
    return `${documentsSkip + 1}-${Math.min(documentsSkip + PAGE_SIZE, documentsTotal)}`;
  }, [documentsSkip, documentsTotal]);

  const anomalyRange = useMemo(() => {
    if (anomaliesTotal === 0) return "0-0";
    return `${anomaliesSkip + 1}-${Math.min(anomaliesSkip + PAGE_SIZE, anomaliesTotal)}`;
  }, [anomaliesSkip, anomaliesTotal]);

  const selectedDocument = useMemo(
    () => documents.find((item) => item.id === selectedDocumentId) ?? null,
    [documents, selectedDocumentId],
  );

  const encodingErrorCount = useMemo(
    () =>
      batch?.documents.filter(
        (item) => item.decode_status === "failed" || item.error_code === "invalid_encoding",
      ).length ?? 0,
    [batch],
  );

  function activateBatch(batchId: string) {
    const nextBatchId = batchId.trim();
    if (!nextBatchId) return;
    restoreRecentBatch(nextBatchId);
    setDocumentsSkip(0);
    setAnomaliesSkip(0);
    setDocuments([]);
    setDocumentsTotal(0);
    setAnomalies([]);
    setAnomaliesTotal(0);
    setSelectedDocumentId(null);
    setActivePanel("overview");
    setBatchIdInput(nextBatchId);
    setActiveBatchId(nextBatchId);
    router.replace(`/dashboard?batchId=${nextBatchId}`);
  }

  function openDocumentDetails(documentId: string) {
    setSelectedDocumentId(documentId);
    setActivePanel("details");
  }

  async function openDocumentFromAnomaly(anomaly: AnomalyItem) {
    const existingDocument = documents.find((item) => item.id === anomaly.document_id);
    if (existingDocument) {
      openDocumentDetails(existingDocument.id);
      return;
    }
    if (!activeBatchId) {
      return;
    }

    setError(null);
    setLoading(true);
    try {
      // Reaproveita o nome do arquivo como busca direta, evitando paginar
      // varias telas ate encontrar o documento vinculado a anomalia.
      const nextSearch = anomaly.file_name.trim();
      const response = await getBatchDocuments(activeBatchId, 0, PAGE_SIZE, {
        search: nextSearch,
      });
      setDocumentSearchFilter(nextSearch);
      setDocumentStatusFilter("");
      setDocumentExtractionFilter("");
      setDocumentDecodeFilter("");
      setDocumentHasAnomalyFilter("all");
      setAppliedDocumentSearchFilter(nextSearch);
      setAppliedDocumentStatusFilter("");
      setAppliedDocumentExtractionFilter("");
      setAppliedDocumentDecodeFilter("");
      setAppliedDocumentHasAnomalyFilter("all");
      setDocumentsSkip(0);
      setDocuments(response.items);
      setDocumentsTotal(response.total);

      const nextDocument =
        response.items.find((item) => item.id === anomaly.document_id) ?? response.items[0] ?? null;
      if (!nextDocument) {
        setError("Nao foi possivel localizar o documento vinculado a esta anomalia.");
        return;
      }
      openDocumentDetails(nextDocument.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Falha ao abrir o documento da anomalia.");
    } finally {
      setLoading(false);
    }
  }

  function applyDocumentPreset({
    search = "",
    status = "",
    extractionStatus = "",
    decodeStatus = "",
    hasAnomaly = "all",
    nextPanel = "documents",
  }: {
    search?: string;
    status?: string;
    extractionStatus?: string;
    decodeStatus?: string;
    hasAnomaly?: string;
    nextPanel?: "documents" | "details";
  }) {
    setDocumentSearchFilter(search);
    setDocumentStatusFilter(status);
    setDocumentExtractionFilter(extractionStatus);
    setDocumentDecodeFilter(decodeStatus);
    setDocumentHasAnomalyFilter(hasAnomaly);
    setAppliedDocumentSearchFilter(search);
    setAppliedDocumentStatusFilter(status);
    setAppliedDocumentExtractionFilter(extractionStatus);
    setAppliedDocumentDecodeFilter(decodeStatus);
    setAppliedDocumentHasAnomalyFilter(hasAnomaly);
    setDocumentsSkip(0);
    setSelectedDocumentId(null);
    setActivePanel(nextPanel);
  }

  function applyAnomalyPreset({
    search = "",
    ruleCode = "",
    severity = "",
  }: {
    search?: string;
    ruleCode?: string;
    severity?: string;
  } = {}) {
    setAnomalySearchFilter(search);
    setRuleCodeFilter(ruleCode);
    setSeverityFilter(severity);
    setAppliedAnomalySearchFilter(search);
    setAppliedRuleCodeFilter(ruleCode);
    setAppliedSeverityFilter(severity);
    setAnomaliesSkip(0);
    setActivePanel("anomalies");
  }

  function applyCurrentDocumentFilters() {
    setAppliedDocumentSearchFilter(documentSearchFilter.trim());
    setAppliedDocumentStatusFilter(documentStatusFilter.trim());
    setAppliedDocumentExtractionFilter(documentExtractionFilter.trim());
    setAppliedDocumentDecodeFilter(documentDecodeFilter.trim());
    setAppliedDocumentHasAnomalyFilter(documentHasAnomalyFilter);
    setDocumentsSkip(0);
  }

  function clearCurrentDocumentFilters() {
    setDocumentSearchFilter("");
    setDocumentStatusFilter("");
    setDocumentExtractionFilter("");
    setDocumentDecodeFilter("");
    setDocumentHasAnomalyFilter("all");
    setAppliedDocumentSearchFilter("");
    setAppliedDocumentStatusFilter("");
    setAppliedDocumentExtractionFilter("");
    setAppliedDocumentDecodeFilter("");
    setAppliedDocumentHasAnomalyFilter("all");
    setDocumentsSkip(0);
  }

  function applyCurrentAnomalyFilters() {
    setAppliedAnomalySearchFilter(anomalySearchFilter.trim());
    setAppliedRuleCodeFilter(ruleCodeFilter.trim());
    setAppliedSeverityFilter(severityFilter.trim());
    setAnomaliesSkip(0);
  }

  function clearCurrentAnomalyFilters() {
    setAnomalySearchFilter("");
    setRuleCodeFilter("");
    setSeverityFilter("");
    setAppliedAnomalySearchFilter("");
    setAppliedRuleCodeFilter("");
    setAppliedSeverityFilter("");
    setAnomaliesSkip(0);
  }

  const documentsPanelActive = activePanel === "documents" || activePanel === "details";
  const completedFilterActive =
    documentsPanelActive &&
    appliedDocumentStatusFilter === "done" &&
    !appliedDocumentSearchFilter &&
    !appliedDocumentExtractionFilter &&
    !appliedDocumentDecodeFilter &&
    appliedDocumentHasAnomalyFilter === "all";
  const errorFilterActive =
    documentsPanelActive &&
    appliedDocumentStatusFilter === "error" &&
    !appliedDocumentSearchFilter &&
    !appliedDocumentExtractionFilter &&
    !appliedDocumentDecodeFilter &&
    appliedDocumentHasAnomalyFilter === "all";
  const encodingFilterActive =
    documentsPanelActive &&
    !appliedDocumentSearchFilter &&
    !appliedDocumentStatusFilter &&
    !appliedDocumentExtractionFilter &&
    appliedDocumentDecodeFilter === "failed" &&
    appliedDocumentHasAnomalyFilter === "all";
  const documentsWithAnomalyActive =
    documentsPanelActive &&
    !appliedDocumentSearchFilter &&
    !appliedDocumentStatusFilter &&
    !appliedDocumentExtractionFilter &&
    !appliedDocumentDecodeFilter &&
    appliedDocumentHasAnomalyFilter === "true";
  const anomaliesViewActive =
    activePanel === "anomalies" &&
    !appliedAnomalySearchFilter &&
    !appliedRuleCodeFilter &&
    !appliedSeverityFilter;

  return (
    <PageShell
      title="Passo 2. Acompanhar analise"
      description="Continue um lote recente ou informe o codigo manualmente. Aqui voce acompanha o progresso, revisa os documentos e abre o detalhe do documento quando precisar."
      navItems={[
        { href: "/", label: "Inicio" },
        { href: "/upload", label: "Enviar arquivos" },
        { href: "/dashboard", label: "Acompanhar", active: true },
        { href: "/reports", label: "Exportar" },
      ]}
    >
      <section className="grid gap-6">
        <Card className="border-border/70 shadow-sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-xl">
              <Search className="size-5 text-primary" />
              Escolher lote
            </CardTitle>
            <CardDescription>
              O lote mais recente fica salvo neste navegador. O codigo manual continua disponivel como referencia tecnica.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {recentBatches.length > 0 ? (
                recentBatches.slice(0, 3).map((item) => (
                  <div
                    key={item.batchId}
                    className={`rounded-3xl border p-4 ${
                      item.batchId === activeBatchId
                        ? "border-primary/40 bg-linear-to-br from-primary/10 via-background to-background"
                        : "bg-muted/15"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="space-y-1">
                        <p className="font-medium">{item.batchName}</p>
                        <p className="text-xs text-muted-foreground">{item.totalFiles} arquivo(s)</p>
                      </div>
                      <StatusBadge value={item.status} />
                    </div>
                    {item.batchId === activeBatchId && batch ? (
                      <div className="mt-3 space-y-2">
                        <div className="flex items-center justify-between text-xs text-muted-foreground">
                          <span>Progresso deste lote</span>
                          <span>{formatNumber(batch.progress.progress_percent)}%</span>
                        </div>
                        <Progress className="h-2" value={Math.min(batch.progress.progress_percent, 100)} />
                      </div>
                    ) : null}
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        className={
                          item.batchId === activeBatchId
                            ? "border-primary/40 bg-primary/10 text-foreground hover:bg-primary/15"
                            : ""
                        }
                        onClick={() => activateBatch(item.batchId)}
                      >
                        Abrir lote
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => setRecentBatches(removeRecentBatch(item.batchId))}
                      >
                        <Trash2 className="size-4" />
                        Excluir do historico
                      </Button>
                    </div>
                  </div>
                ))
              ) : (
                <div className="rounded-3xl border border-dashed bg-muted/15 p-4 text-sm text-muted-foreground xl:col-span-3">
                  Nenhum lote recente salvo ainda. Assim que um upload for aceito, ele aparece aqui automaticamente.
                </div>
              )}
            </div>

            <div className="grid gap-4 lg:grid-cols-[1fr_auto_auto]">
              <div className="space-y-2">
                <Label htmlFor="batch-id-input">Abrir pelo codigo manual</Label>
                <Input
                  id="batch-id-input"
                  placeholder="Cole o batch_id apenas se precisar abrir um lote especifico"
                  value={batchIdInput}
                  onChange={(event) => setBatchIdInput(event.target.value)}
                />
              </div>
              <div className="flex items-end">
                <Button className="w-full lg:w-auto" onClick={() => activateBatch(batchIdInput)}>
                  <Search className="size-4" />
                  Abrir lote
                </Button>
              </div>
              <div className="flex items-end">
                <Button
                  className="w-full lg:w-auto"
                  disabled={!activeBatchId || loading}
                      variant="outline"
                      onClick={() => activeBatchId && void refreshActiveView(activeBatchId)}
                    >
                      <RefreshCcw className="size-4" />
                      Atualizar
                </Button>
              </div>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-4 rounded-3xl border bg-muted/20 px-4 py-3">
              <div className="flex items-center gap-3">
                <Switch
                  checked={autoRefresh}
                  id="auto-refresh"
                  onCheckedChange={setAutoRefresh}
                />
                <div className="space-y-0.5">
                  <Label htmlFor="auto-refresh">Atualizacao automatica</Label>
                  <p className="text-sm text-muted-foreground">
                    Mantem o acompanhamento ativo enquanto o lote ainda estiver em andamento.
                  </p>
                </div>
              </div>
              {activeBatchId ? (
                <div className="flex flex-wrap gap-3">
                  <Button asChild variant="outline">
                    <Link href={`/reports?batchId=${activeBatchId}`}>Ir para exportacoes</Link>
                  </Button>
                  <Button asChild variant="outline">
                    <Link href="/upload">Enviar novo lote</Link>
                  </Button>
                  <Button
                    disabled={!batch || !isBatchActive(batch.status)}
                    variant="destructive"
                    onClick={async () => {
                      try {
                        await cancelBatch(activeBatchId);
                        await refreshActiveView(activeBatchId);
                      } catch (err) {
                        setError(err instanceof ApiError ? err.message : "Falha ao cancelar o lote.");
                      }
                    }}
                  >
                    <XCircle className="size-4" />
                    Cancelar lote
                  </Button>
                </div>
              ) : null}
            </div>

            {error ? (
              <Alert variant="destructive">
                <ShieldAlert className="size-4" />
                <AlertTitle>Falha na consulta</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}

            {batch ? (
              <div className="rounded-3xl border bg-muted/20 p-4">
                <div className="flex flex-col gap-4">
                  <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                    <div>
                      <p className="font-medium text-foreground">{batch.batch_name}</p>
                      <p className="text-sm text-muted-foreground">
                        Referencia tecnica: <span className="font-mono">{batch.batch_id}</span>
                      </p>
                    </div>
                    <StatusBadge value={batch.status} />
                  </div>
                  <div>
                    <div className="flex items-center justify-between gap-3 text-sm text-muted-foreground">
                      <span>Andamento do lote selecionado</span>
                      <span>{formatNumber(batch.progress.progress_percent)}%</span>
                    </div>
                    <Progress className="mt-2 h-2.5" value={Math.min(batch.progress.progress_percent, 100)} />
                  </div>
                </div>
              </div>
            ) : null}

            {lastUpdated ? (
              <Alert>
                <Clock3 className="size-4" />
                <AlertTitle>Ultima atualizacao</AlertTitle>
                <AlertDescription>{lastUpdated}</AlertDescription>
              </Alert>
            ) : null}
          </CardContent>
        </Card>

        {!batch && loading ? (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {Array.from({ length: 4 }).map((_, index) => (
              <Card key={index}>
                <CardHeader className="space-y-3">
                  <Skeleton className="h-4 w-24" />
                  <Skeleton className="h-10 w-20" />
                </CardHeader>
              </Card>
            ))}
          </div>
        ) : null}

        {batch ? (
          <>
            <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
              <MetricCard
                label="Status do lote"
                value={<StatusBadge value={batch.status} />}
                helper={
                  <>
                    <span className="block">{batch.batch_name}</span>
                    <span className="block">{batch.total_files} arquivo(s) neste lote.</span>
                  </>
                }
                icon={<Activity className="size-4" />}
                active={activePanel === "overview"}
                onClick={() => setActivePanel("overview")}
              />
              <MetricCard
                label="Concluidos"
                value={batch.successful_files}
                helper="Abra os documentos finalizados para revisar antes de exportar."
                icon={<Gauge className="size-4" />}
                active={completedFilterActive}
                onClick={() => applyDocumentPreset({ status: "done" })}
              />
              <MetricCard
                label="Anomalias"
                value={batch.anomaly_count}
                helper="Abra a aba de anomalias ou va direto para os documentos afetados."
                icon={<ShieldAlert className="size-4" />}
                active={anomaliesViewActive}
                actions={[
                  {
                    label: "Ver anomalias",
                    onClick: () => applyAnomalyPreset(),
                    active: anomaliesViewActive,
                  },
                  {
                    label: "Documentos com anomalia",
                    onClick: () => applyDocumentPreset({ hasAnomaly: "true" }),
                    active: documentsWithAnomalyActive,
                  },
                ]}
                onClick={() => applyAnomalyPreset()}
              />
              <MetricCard
                label="Arquivos com alerta"
                value={batch.error_files}
                helper="Mostra os documentos que terminaram com erro e precisam de revisao."
                icon={<XCircle className="size-4" />}
                active={errorFilterActive}
                onClick={() => applyDocumentPreset({ status: "error" })}
              />
              <MetricCard
                label="Erros de encoding"
                value={encodingErrorCount}
                helper="Filtra os arquivos que tiveram problema de leitura de caracteres."
                icon={<FileSearch className="size-4" />}
                active={encodingFilterActive}
                onClick={() => applyDocumentPreset({ decodeStatus: "failed" })}
              />
              <MetricCard
                label="Falhas de IA externa"
                value={batch.progress.llm_request_failures}
                helper="Abre a visao geral com o bloco de ocorrencias da validacao por IA."
                icon={<Bot className="size-4" />}
                active={activePanel === "overview" && batch.progress.llm_request_failures > 0}
                onClick={() => setActivePanel("overview")}
              />
            </section>

            <Card className="border-border/70 shadow-sm">
              <CardHeader>
                <CardTitle className="text-xl">Navegacao da revisao</CardTitle>
                <CardDescription>
                  Troque de aba para acompanhar o lote sem precisar descer a pagina inteira.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                  <Button
                    variant="outline"
                    className={`h-auto justify-between py-3 text-left ${
                      activePanel === "overview"
                        ? "border-primary/40 bg-primary/10 text-foreground hover:bg-primary/15"
                        : "hover:bg-muted/40"
                    }`}
                    onClick={() => setActivePanel("overview")}
                  >
                    <span>Visao geral</span>
                    <Badge variant="secondary">{formatNumber(batch.progress.progress_percent)}%</Badge>
                  </Button>
                  <Button
                    variant="outline"
                    className={`h-auto justify-between py-3 text-left ${
                      activePanel === "documents"
                        ? "border-primary/40 bg-primary/10 text-foreground hover:bg-primary/15"
                        : "hover:bg-muted/40"
                    }`}
                    onClick={() => setActivePanel("documents")}
                    >
                      <span>Documentos</span>
                      <Badge variant="secondary">{batch.total_files}</Badge>
                    </Button>
                  <Button
                    variant="outline"
                    className={`h-auto justify-between py-3 text-left ${
                      activePanel === "details"
                        ? "border-primary/40 bg-primary/10 text-foreground hover:bg-primary/15"
                        : "hover:bg-muted/40"
                    }`}
                    onClick={() => setActivePanel("details")}
                  >
                    <span>Detalhe do documento</span>
                    <Badge variant="secondary">{selectedDocument ? "1 selecionado" : "escolha 1"}</Badge>
                  </Button>
                  <Button
                    variant="outline"
                    className={`h-auto justify-between py-3 text-left ${
                      activePanel === "anomalies"
                        ? "border-primary/40 bg-primary/10 text-foreground hover:bg-primary/15"
                        : "hover:bg-muted/40"
                    }`}
                    onClick={() => setActivePanel("anomalies")}
                    >
                      <span>Anomalias</span>
                      <Badge variant="secondary">{batch.anomaly_count}</Badge>
                    </Button>
                </div>
              </CardContent>
            </Card>

            {activePanel === "overview" ? (
              <>
                <Card className="border-border/70 shadow-sm">
                  <CardHeader>
                    <CardTitle className="text-xl">Jornada do lote</CardTitle>
                    <CardDescription>
                      Veja em qual etapa o lote esta e o que ja pode ser feito agora.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                    {JOURNEY_STEPS.map((step) => {
                      const isCurrent =
                        batch.progress.current_stage === step.key ||
                        (step.key === "completed" &&
                          ["completed", "completed_with_errors", "failed", "cancelled"].includes(batch.status));

                      return (
                        <div
                          key={step.key}
                          className={`rounded-3xl border p-4 ${
                            isCurrent ? "border-primary/40 bg-primary/5" : "bg-muted/15"
                          }`}
                        >
                          <div className="flex flex-wrap items-start justify-between gap-3">
                            <p className="min-w-0 break-words font-medium text-foreground">{step.title}</p>
                            <Badge className="shrink-0" variant={isCurrent ? "default" : "outline"}>
                              {isCurrent ? "agora" : "etapa"}
                            </Badge>
                          </div>
                          <p className="mt-2 break-words text-sm text-muted-foreground">{step.description}</p>
                        </div>
                      );
                    })}
                  </CardContent>
                </Card>

                <Card className="border-border/70 shadow-sm">
                  <CardHeader>
                    <CardTitle className="text-xl">Progresso da analise</CardTitle>
                    <CardDescription>
                      Quanto do lote ja foi processado e quanto tempo ainda deve levar.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-5">
                    <Progress
                      className="h-3"
                      value={Math.min(batch.progress.progress_percent, 100)}
                    />
                    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-6">
                      <div className="rounded-3xl border bg-muted/20 p-4">
                        <p className="text-xs uppercase tracking-[0.24em] text-muted-foreground">
                          Concluido
                        </p>
                        <p className="mt-2 text-2xl font-semibold">
                          {formatNumber(batch.progress.progress_percent)}%
                        </p>
                      </div>
                      <div className="rounded-3xl border bg-muted/20 p-4">
                        <p className="text-xs uppercase tracking-[0.24em] text-muted-foreground">
                          ETA
                        </p>
                        <p className="mt-2 text-2xl font-semibold">
                          {formatSeconds(batch.progress.estimated_remaining_seconds)}
                        </p>
                      </div>
                      <div className="rounded-3xl border bg-muted/20 p-4">
                        <p className="text-xs uppercase tracking-[0.24em] text-muted-foreground">
                          Em processamento
                        </p>
                        <p className="mt-2 text-2xl font-semibold">
                          {batch.progress.processing_files}
                        </p>
                      </div>
                      <div className="rounded-3xl border bg-muted/20 p-4">
                        <p className="text-xs uppercase tracking-[0.24em] text-muted-foreground">
                          Throughput
                        </p>
                        <p className="mt-2 text-2xl font-semibold">
                          {formatNumber(batch.progress.throughput_files_per_minute)}
                        </p>
                      </div>
                      <div className="rounded-3xl border bg-muted/20 p-4">
                        <p className="text-xs uppercase tracking-[0.24em] text-muted-foreground">
                          Tempo medio
                        </p>
                        <p className="mt-2 text-2xl font-semibold">
                          {formatNumber(batch.progress.average_seconds_per_file)}s
                        </p>
                      </div>
                      <div className="rounded-3xl border bg-muted/20 p-4">
                        <p className="text-xs uppercase tracking-[0.24em] text-muted-foreground">
                          Fallbacks
                        </p>
                        <p className="mt-2 text-2xl font-semibold">
                          {batch.progress.llm_fallback_count}
                        </p>
                      </div>
                    </div>
                  </CardContent>
                </Card>

                {batch.progress.llm_request_failures > 0 ? (
                  <Card className="border-border/70 shadow-sm">
                    <CardHeader>
                      <CardTitle className="text-xl">Ocorrencias de processamento</CardTitle>
                      <CardDescription>
                        O upload foi aceito, mas parte do lote apresentou instabilidade de processamento.
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      <Alert>
                        <Bot className="size-4" />
                        <AlertTitle>Problema de processamento identificado</AlertTitle>
                        <AlertDescription>
                          Alguns documentos podem aparecer com analise parcial. O sistema manteve o lote
                          disponivel para revisao e exportacao.
                        </AlertDescription>
                      </Alert>

                      <div className="rounded-3xl border bg-muted/20 p-4 text-sm text-muted-foreground">
                        Detalhes tecnicos de falhas internas ficam restritos para auditoria operacional.
                        Para o usuario final, o lote segue disponivel para revisao dos documentos impactados.
                      </div>
                    </CardContent>
                  </Card>
                ) : null}

                <Card className="border-border/70 shadow-sm">
                  <CardHeader>
                    <CardTitle className="text-xl">O que fazer agora</CardTitle>
                    <CardDescription>
                      O proximo passo depende do estado atual do lote.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="flex flex-wrap gap-3">
                    <Button asChild>
                      <Link href={`/reports?batchId=${batch.batch_id}`}>
                        <Download className="size-4" />
                        Exportar resultados
                      </Link>
                    </Button>
                    <Button variant="outline" onClick={() => void refreshActiveView(batch.batch_id)}>
                      <RefreshCcw className="size-4" />
                      Atualizar leitura
                    </Button>
                    <Button asChild variant="outline">
                      <Link href="/upload">Enviar novo lote</Link>
                    </Button>
                    <div className="w-full rounded-3xl border bg-muted/20 p-4 text-sm text-muted-foreground">
                      {isBatchActive(batch.status)
                        ? "O lote ainda esta em andamento. Ja e possivel acompanhar progresso e revisar documentos concluidos."
                        : batch.status === "completed_with_errors"
                          ? "O lote terminou com alertas. Revise os documentos impactados e siga para a exportacao se os dados estiverem suficientes."
                          : "O lote terminou. Revise os documentos, abra o detalhe do documento e confirme as anomalias antes de exportar."}
                    </div>
                  </CardContent>
                </Card>
              </>
            ) : null}

            {activePanel === "documents" ? (
              <Card className="border-border/70 shadow-sm">
              <CardHeader className="gap-4">
                <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                  <div>
                    <CardTitle className="text-xl">Documentos do lote</CardTitle>
                    <CardDescription>
                      Mostrando {documentRange} de {documentsTotal}. Clique em um item para abrir o detalhe do documento.
                    </CardDescription>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      disabled={documentsSkip === 0}
                      size="sm"
                      variant="outline"
                      onClick={() => setDocumentsSkip((current) => Math.max(current - PAGE_SIZE, 0))}
                    >
                      Pagina anterior
                    </Button>
                    <Button
                      disabled={documentsSkip + PAGE_SIZE >= documentsTotal}
                      size="sm"
                      variant="outline"
                      onClick={() => setDocumentsSkip((current) => current + PAGE_SIZE)}
                    >
                      Proxima pagina
                    </Button>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
                  <div className="space-y-2 xl:col-span-2">
                    <Label htmlFor="document-search-filter">Buscar documento, fornecedor ou NF</Label>
                    <Input
                      id="document-search-filter"
                      placeholder="Ex: nota-001, TechSoft, NF-100, CNPJ ou motivo do erro"
                      value={documentSearchFilter}
                      onChange={(event) => setDocumentSearchFilter(event.target.value)}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>Status do documento</Label>
                    <Select
                      value={documentStatusFilter || "all"}
                      onValueChange={(value) => setDocumentStatusFilter(value === "all" ? "" : value)}
                    >
                      <SelectTrigger className="w-full">
                        <SelectValue placeholder="Todos status" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">Todos status</SelectItem>
                        <SelectItem value="pending">Pendente</SelectItem>
                        <SelectItem value="processing">Em processamento</SelectItem>
                        <SelectItem value="done">Concluido</SelectItem>
                        <SelectItem value="error">Com erro</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label>Extracao</Label>
                    <Select
                      value={documentExtractionFilter || "all"}
                      onValueChange={(value) =>
                        setDocumentExtractionFilter(value === "all" ? "" : value)
                      }
                    >
                      <SelectTrigger className="w-full">
                        <SelectValue placeholder="Todas etapas" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">Todas etapas</SelectItem>
                        <SelectItem value="pending">Pendente</SelectItem>
                        <SelectItem value="parsed">Parser local</SelectItem>
                        <SelectItem value="queued_llm">Fila da IA</SelectItem>
                        <SelectItem value="llm_processing">IA processando</SelectItem>
                        <SelectItem value="local_ready">Somente parser local</SelectItem>
                        <SelectItem value="success">Concluida</SelectItem>
                        <SelectItem value="partial">Parcial</SelectItem>
                        <SelectItem value="failed">Falhou</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label>Tratamento de encoding</Label>
                    <Select
                      value={documentDecodeFilter || "all"}
                      onValueChange={(value) => setDocumentDecodeFilter(value === "all" ? "" : value)}
                    >
                      <SelectTrigger className="w-full">
                        <SelectValue placeholder="Todos cenarios" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">Todos cenarios</SelectItem>
                        <SelectItem value="pending">Pendente</SelectItem>
                        <SelectItem value="success">Sem problema</SelectItem>
                        <SelectItem value="recovered">Recuperado</SelectItem>
                        <SelectItem value="failed">Erro de encoding</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>

                <div className="grid gap-3 md:grid-cols-[220px_auto]">
                  <div className="space-y-2">
                    <Label>Com anomalia?</Label>
                    <Select
                      value={documentHasAnomalyFilter}
                      onValueChange={setDocumentHasAnomalyFilter}
                    >
                      <SelectTrigger className="w-full">
                        <SelectValue placeholder="Todos" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">Todos</SelectItem>
                        <SelectItem value="true">Somente com anomalia</SelectItem>
                        <SelectItem value="false">Somente sem anomalia</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="flex flex-wrap items-end gap-2">
                    <Button
                      size="sm"
                      onClick={applyCurrentDocumentFilters}
                    >
                      Aplicar filtros
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={clearCurrentDocumentFilters}
                    >
                      Limpar
                    </Button>
                    <p className="text-sm text-muted-foreground">
                      Use a busca para localizar arquivo, fornecedor, NF, CNPJ ou motivo do erro.
                    </p>
                  </div>
                </div>

                <div className="rounded-3xl border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Arquivo</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>Extracao</TableHead>
                        <TableHead>Fornecedor</TableHead>
                        <TableHead>Valor</TableHead>
                        <TableHead>Resumo</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {documents.length > 0 ? (
                        documents.map((document) => (
                          <TableRow
                            key={document.id}
                            className={`cursor-pointer ${selectedDocumentId === document.id ? "bg-muted/30" : ""}`}
                            onClick={() => openDocumentDetails(document.id)}
                          >
                            <TableCell className="max-w-[220px] whitespace-normal">
                              <div className="space-y-1">
                                <p className="font-medium">{document.file_name}</p>
                                <p className="text-xs text-muted-foreground">
                                  {document.llm_fallback_used ? "com fallback" : "fluxo normal"}
                                </p>
                              </div>
                            </TableCell>
                            <TableCell>
                              <StatusBadge value={document.status} />
                            </TableCell>
                            <TableCell>
                              <StatusBadge value={document.extraction_status} />
                            </TableCell>
                            <TableCell className="max-w-[220px] whitespace-normal">
                              {formatValue(document.extracted_data.fornecedor)}
                            </TableCell>
                            <TableCell>{formatValue(document.extracted_data.valor_bruto)}</TableCell>
                            <TableCell className="max-w-[280px] whitespace-normal text-sm text-muted-foreground">
                              {document.analysis_summary ?? "-"}
                            </TableCell>
                          </TableRow>
                        ))
                      ) : (
                        <TableRow>
                          <TableCell className="py-10 text-center text-muted-foreground" colSpan={6}>
                            Nenhum documento para esta pagina.
                          </TableCell>
                        </TableRow>
                      )}
                    </TableBody>
                  </Table>
                </div>
              </CardContent>
              </Card>
            ) : null}

            {activePanel === "details" ? <DocumentDetails document={selectedDocument} /> : null}

            {activePanel === "anomalies" ? (
              <Card className="border-border/70 shadow-sm">
              <CardHeader className="gap-4">
                <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                  <div>
                    <CardTitle className="text-xl">Anomalias do lote</CardTitle>
                    <CardDescription>
                      Mostrando {anomalyRange} de {anomaliesTotal}.
                    </CardDescription>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      disabled={anomaliesSkip === 0}
                      size="sm"
                      variant="outline"
                      onClick={() => setAnomaliesSkip((current) => Math.max(current - PAGE_SIZE, 0))}
                    >
                      Pagina anterior
                    </Button>
                    <Button
                      disabled={anomaliesSkip + PAGE_SIZE >= anomaliesTotal}
                      size="sm"
                      variant="outline"
                      onClick={() => setAnomaliesSkip((current) => current + PAGE_SIZE)}
                    >
                      Proxima pagina
                    </Button>
                  </div>
                </div>
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-[1.1fr_1fr_220px_auto]">
                  <div className="space-y-2">
                    <Label htmlFor="anomaly-search-filter">Buscar fornecedor, arquivo ou detalhe</Label>
                    <Input
                      id="anomaly-search-filter"
                      placeholder="Ex: TechSoft, nota-002, aprovador"
                      value={anomalySearchFilter}
                      onChange={(event) => setAnomalySearchFilter(event.target.value)}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="rule-code-filter">Filtrar por codigo da regra</Label>
                    <Input
                      id="rule-code-filter"
                      placeholder="Ex: NF_DUPLICADA"
                      value={ruleCodeFilter}
                      onChange={(event) => setRuleCodeFilter(event.target.value)}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>Severidade</Label>
                    <Select
                      value={severityFilter || "all"}
                      onValueChange={(value) => setSeverityFilter(value === "all" ? "" : value)}
                    >
                      <SelectTrigger className="w-full">
                        <SelectValue placeholder="Todas severidades" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">Todas severidades</SelectItem>
                        <SelectItem value="high">Alta</SelectItem>
                        <SelectItem value="medium">Media</SelectItem>
                        <SelectItem value="low">Baixa</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="flex items-end gap-2">
                    <Button
                      size="sm"
                      onClick={applyCurrentAnomalyFilters}
                    >
                      Aplicar filtros
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={clearCurrentAnomalyFilters}
                    >
                      Limpar
                    </Button>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                <div className="rounded-3xl border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Regra</TableHead>
                        <TableHead>Arquivo</TableHead>
                        <TableHead>Severidade</TableHead>
                        <TableHead>Confianca</TableHead>
                        <TableHead>Detalhes</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {anomalies.length > 0 ? (
                        anomalies.map((anomaly) => (
                          <TableRow
                            key={anomaly.id}
                            className="cursor-pointer"
                            onClick={() => void openDocumentFromAnomaly(anomaly)}
                          >
                            <TableCell className="max-w-[220px] whitespace-normal">
                              <div className="space-y-1">
                                <p className="font-medium">{anomaly.rule_code}</p>
                                <p className="text-xs text-muted-foreground">{anomaly.rule_name}</p>
                              </div>
                            </TableCell>
                            <TableCell className="max-w-[180px] whitespace-normal">
                              <div className="space-y-1">
                                <p>{anomaly.file_name}</p>
                                <p className="text-xs text-muted-foreground">
                                  Clique para abrir o documento relacionado
                                </p>
                              </div>
                            </TableCell>
                            <TableCell>
                              <StatusBadge value={anomaly.severity} />
                            </TableCell>
                            <TableCell>{anomaly.confidence}</TableCell>
                            <TableCell className="max-w-[340px] whitespace-normal text-sm text-muted-foreground">
                              {describeAnomaly(anomaly)}
                            </TableCell>
                          </TableRow>
                        ))
                      ) : (
                        <TableRow>
                          <TableCell className="py-10 text-center text-muted-foreground" colSpan={5}>
                            Nenhuma anomalia encontrada para os filtros atuais.
                          </TableCell>
                        </TableRow>
                      )}
                    </TableBody>
                  </Table>
                </div>
              </CardContent>
              </Card>
            ) : null}
          </>
        ) : recentHydrated && !loading ? (
          <EmptyState
            title="Nenhum lote aberto"
            description="Abra um lote recente salvo neste navegador ou informe o codigo manualmente para continuar a analise."
          />
        ) : null}
      </section>
    </PageShell>
  );
}

export default function DashboardPage() {
  return (
    <Suspense
      fallback={
        <main className="min-h-screen bg-background">
          <div className="mx-auto max-w-7xl px-4 py-8">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <LoaderCircle className="size-4 animate-spin text-primary" />
                  Carregando acompanhamento
                </CardTitle>
                <CardDescription>
                  Preparando o ultimo lote salvo e sincronizando o estado da URL.
                </CardDescription>
              </CardHeader>
            </Card>
          </div>
        </main>
      }
    >
      <DashboardPageContent />
    </Suspense>
  );
}
