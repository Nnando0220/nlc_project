"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  Download,
  FileSpreadsheet,
  FolderClock,
  ShieldCheck,
  Trash2,
} from "lucide-react";

import { PageShell } from "@/components/app/page-shell";
import { StatusBadge } from "@/components/app/status-badge";
import {
  RecentBatch,
  getMostRecentBatch,
  listRecentBatches,
  removeRecentBatch,
  saveRecentBatch,
} from "@/lib/recent-batches";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
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
import {
  ApiError,
  ReportResponse,
  buildReportDownloadUrl,
  exportAnomalies,
  exportAudit,
  exportResults,
} from "@/services/api";

function ReportCard({
  title,
  description,
  loading,
  report,
  onGenerate,
}: {
  title: string;
  description: string;
  loading: boolean;
  report: ReportResponse | null;
  onGenerate: () => Promise<void>;
}) {
  return (
    <Card className="border-border/70 shadow-sm">
      <CardHeader>
        <CardTitle className="text-xl">{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap gap-3">
          <Button disabled={loading} onClick={() => void onGenerate()}>
            <FileSpreadsheet className="size-4" />
            {loading ? "Gerando..." : "Gerar CSV"}
          </Button>
          {report ? (
            <Button asChild variant="outline">
              <a download href={buildReportDownloadUrl(report.report_id)}>
                <Download className="size-4" />
                Baixar arquivo
              </a>
            </Button>
          ) : null}
        </div>

        {report ? (
          <div className="space-y-2 rounded-3xl border bg-muted/20 p-4 text-sm">
            <p className="text-xs font-medium uppercase tracking-[0.24em] text-muted-foreground">
              relatorio gerado
            </p>
            <p className="break-all font-mono">{report.report_id}</p>
            <p className="break-all text-muted-foreground">{report.csv_path}</p>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function ReportsPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialBatchId = searchParams.get("batchId") ?? "";
  const [batchId, setBatchId] = useState("");
  const [resultsReport, setResultsReport] = useState<ReportResponse | null>(null);
  const [auditReport, setAuditReport] = useState<ReportResponse | null>(null);
  const [anomaliesReport, setAnomaliesReport] = useState<ReportResponse | null>(null);
  const [loadingKind, setLoadingKind] = useState<"results" | "audit" | "anomalies" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [recentBatches, setRecentBatches] = useState<RecentBatch[]>([]);

  useEffect(() => {
    const queryBatchId = initialBatchId.trim();
    const recent = getMostRecentBatch();
    setRecentBatches(listRecentBatches());
    if (queryBatchId) {
      setBatchId(queryBatchId);
      return;
    }
    if (recent) {
      setBatchId(recent.batchId);
    }
  }, [initialBatchId]);

  const activeRecentBatch = useMemo(
    () => recentBatches.find((item) => item.batchId === batchId.trim()) ?? null,
    [batchId, recentBatches],
  );

  async function handleExport(kind: "results" | "audit" | "anomalies") {
    const normalizedBatchId = batchId.trim();
    if (!normalizedBatchId) {
      setError("Informe um lote antes de exportar.");
      return;
    }

    setError(null);
    setLoadingKind(kind);
    try {
      const response =
        kind === "results"
          ? await exportResults(normalizedBatchId)
          : kind === "audit"
            ? await exportAudit(normalizedBatchId)
            : await exportAnomalies(normalizedBatchId);
      if (kind === "results") {
        setResultsReport(response);
      } else if (kind === "audit") {
        setAuditReport(response);
      } else {
        setAnomaliesReport(response);
      }

      setRecentBatches(
        saveRecentBatch({
          batchId: normalizedBatchId,
          batchName: activeRecentBatch?.batchName,
          status: activeRecentBatch?.status ?? "completed",
          totalFiles: activeRecentBatch?.totalFiles,
        }),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Falha ao gerar o relatorio.");
    } finally {
      setLoadingKind(null);
    }
  }

  return (
    <PageShell
      title="Passo 4. Exportar resultados"
      description="Escolha um lote recente ou informe o codigo manualmente para baixar os arquivos que alimentam o BI e a auditoria."
      navItems={[
        { href: "/", label: "Inicio" },
        { href: "/upload", label: "Enviar arquivos" },
        { href: "/dashboard", label: "Acompanhar" },
        { href: "/reports", label: "Exportar", active: true },
      ]}
    >
      <section className="grid gap-6 lg:grid-cols-[0.95fr_1.05fr]">
        <Card className="border-border/70 shadow-sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-xl">
              <FolderClock className="size-5 text-primary" />
              Escolher lote para exportar
            </CardTitle>
            <CardDescription>
              Os lotes recentes ficam salvos neste navegador para facilitar a etapa final do fluxo.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="grid gap-3">
              {recentBatches.length > 0 ? (
                recentBatches.slice(0, 3).map((item) => (
                  <div
                    key={item.batchId}
                    className={`rounded-3xl border p-4 ${
                      item.batchId === batchId.trim() ? "border-primary/40 bg-primary/5" : "bg-muted/15"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="space-y-1">
                        <p className="font-medium">{item.batchName}</p>
                        <p className="text-xs text-muted-foreground">{item.totalFiles} arquivo(s)</p>
                      </div>
                      <StatusBadge value={item.status} />
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        className={
                          item.batchId === batchId.trim()
                            ? "border-primary/40 bg-primary/10 text-foreground hover:bg-primary/15"
                            : ""
                        }
                        onClick={() => setBatchId(item.batchId)}
                      >
                        Selecionar lote
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          const nextRecentBatches = removeRecentBatch(item.batchId);
                          setRecentBatches(nextRecentBatches);
                          if (batchId.trim() === item.batchId) {
                            setBatchId(nextRecentBatches[0]?.batchId ?? "");
                          }
                        }}
                      >
                        <Trash2 className="size-4" />
                        Excluir do historico
                      </Button>
                    </div>
                  </div>
                ))
              ) : (
                <div className="rounded-3xl border border-dashed bg-muted/15 p-4 text-sm text-muted-foreground">
                  Nenhum lote recente salvo neste navegador ainda.
                </div>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="reports-batch-id">Abrir pelo codigo manual</Label>
              <Input
                id="reports-batch-id"
                placeholder="Cole o batch_id apenas se precisar exportar um lote especifico"
                value={batchId}
                onChange={(event) => setBatchId(event.target.value)}
              />
            </div>

            {batchId.trim() ? (
              <div className="rounded-3xl border bg-muted/20 p-4 text-sm">
                <p className="text-xs font-medium uppercase tracking-[0.24em] text-muted-foreground">
                  referencia tecnica
                </p>
                <p className="mt-2 break-all font-mono">{batchId.trim()}</p>
              </div>
            ) : null}

            <div className="flex flex-wrap gap-3">
              <Button
                variant="outline"
                onClick={() =>
                  batchId.trim() && router.push(`/dashboard?batchId=${batchId.trim()}`)
                }
              >
                Ver acompanhamento
                <ArrowRight className="size-4" />
              </Button>
              <Button asChild variant="ghost">
                <Link href="/upload">Enviar novo lote</Link>
              </Button>
            </div>

            {error ? (
              <Alert variant="destructive">
                <ShieldCheck className="size-4" />
                <AlertTitle>Falha na exportacao</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}

            <div className="space-y-3 text-sm text-muted-foreground">
              <div className="rounded-3xl border bg-muted/20 p-4">
                <p className="font-medium text-foreground">results.csv</p>
                <p className="mt-1">
                  Base principal por documento, com campos extraidos, flags e status final.
                </p>
              </div>
              <div className="rounded-3xl border bg-muted/20 p-4">
                <p className="font-medium text-foreground">anomalies.csv</p>
                <p className="mt-1">
                  Uma linha por anomalia, pronta para graficos e filtros no Power BI.
                </p>
              </div>
              <div className="rounded-3xl border bg-muted/20 p-4">
                <p className="font-medium text-foreground">audit.csv</p>
                <p className="mt-1">
                  Log rastreavel do processamento, incluindo ocorrencias da IA externa.
                </p>
              </div>
              <div className="rounded-3xl border bg-muted/20 p-4">
                <p className="font-medium text-foreground">Passo seguinte no BI</p>
                <p className="mt-1">
                  Estes CSVs cobrem a base para cards, tabela detalhada de anomalias,
                  ranking por fornecedor e log de auditoria. O dashboard Power BI ainda
                  precisa ser publicado separadamente como `.pbix` ou link do Power BI Service.
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

        <div className="grid gap-6">
          <ReportCard
            title="CSV principal"
            description="Resultado final do lote para analise operacional e integracao com BI."
            loading={loadingKind === "results"}
            report={resultsReport}
            onGenerate={() => handleExport("results")}
          />
          <ReportCard
            title="CSV de anomalias"
            description="Base granular para dashboards por regra, fornecedor e gravidade."
            loading={loadingKind === "anomalies"}
            report={anomaliesReport}
            onGenerate={() => handleExport("anomalies")}
          />
          <ReportCard
            title="CSV de auditoria"
            description="Historico de verificacoes, estrategias, fallbacks e falhas externas da IA."
            loading={loadingKind === "audit"}
            report={auditReport}
            onGenerate={() => handleExport("audit")}
          />
        </div>
      </section>
    </PageShell>
  );
}

export default function ReportsPage() {
  return (
    <Suspense
      fallback={
        <main className="min-h-screen bg-background">
          <div className="mx-auto max-w-7xl px-4 py-8">
            <Card>
              <CardHeader>
                <CardTitle>Carregando exportacoes</CardTitle>
                <CardDescription>
                  Recuperando o lote mais recente e sincronizando os parametros da URL.
                </CardDescription>
              </CardHeader>
            </Card>
          </div>
        </main>
      }
    >
      <ReportsPageContent />
    </Suspense>
  );
}
