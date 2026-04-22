"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  Activity,
  ArrowRight,
  BadgeCheck,
  Download,
  FileSearch,
  FolderClock,
  Sparkles,
  Trash2,
  Upload,
} from "lucide-react";

import { MetricCard } from "@/components/app/metric-card";
import { PageShell } from "@/components/app/page-shell";
import { StatusBadge } from "@/components/app/status-badge";
import { RecentBatch, listRecentBatches, removeRecentBatch } from "@/lib/recent-batches";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

function formatRelativeDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "agora";
  }
  return date.toLocaleString("pt-BR");
}

export default function HomePage() {
  const [recentBatches, setRecentBatches] = useState<RecentBatch[]>([]);

  useEffect(() => {
    setRecentBatches(listRecentBatches());
  }, []);

  const latestBatch = recentBatches[0] ?? null;

  return (
    <PageShell
      title="Auditoria publica de documentos com IA"
      description="Uma jornada guiada para enviar arquivos, acompanhar a analise, revisar dados e anomalias, e exportar tudo para BI."
      navItems={[
        { href: "/", label: "Inicio", active: true },
        { href: "/upload", label: "Enviar arquivos" },
        { href: "/dashboard", label: "Acompanhar" },
        { href: "/reports", label: "Exportar" },
      ]}
      actions={
        <>
          <Button asChild>
            <Link href="/upload">
              Enviar arquivos
              <ArrowRight className="size-4" />
            </Link>
          </Button>
          {latestBatch ? (
            <Button asChild variant="outline">
              <Link href={`/dashboard?batchId=${latestBatch.batchId}`}>Continuar ultimo lote</Link>
            </Button>
          ) : null}
        </>
      }
    >
      <section className="grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
        <Card className="overflow-hidden border-border/70 shadow-sm">
          <CardHeader className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline">Fluxo guiado</Badge>
              <Badge variant="outline">TXT e ZIP</Badge>
              <Badge variant="outline">CSV para BI</Badge>
            </div>
            <div className="space-y-3">
              <CardTitle className="text-3xl leading-tight md:text-4xl">
                O usuario sabe o que fazer antes, durante e depois da analise.
              </CardTitle>
              <CardDescription className="max-w-3xl text-base leading-7">
                O sistema recebe o lote, acompanha o progresso, mostra os dados analisados e
                deixa a exportacao pronta sem depender do `batch_id` como etapa principal da
                navegacao.
              </CardDescription>
            </div>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <MetricCard
                label="1. Envio"
                value="Arquivos"
                helper="TXT avulsos ou ZIP com multiplos documentos."
                icon={<Upload className="size-4" />}
              />
              <MetricCard
                label="2. Acompanhamento"
                value="Progresso"
                helper="Leitura local, IA externa, anomalias e ETA."
                icon={<Activity className="size-4" />}
              />
              <MetricCard
                label="3. Revisao"
                value="Dados"
                helper="Campos extraidos, alertas e documentos impactados."
                icon={<FileSearch className="size-4" />}
              />
              <MetricCard
                label="4. Exportacao"
                value="CSV"
                helper="Resultados, anomalias e auditoria prontos para BI."
                icon={<Download className="size-4" />}
              />
            </div>

            <div className="grid gap-3 text-sm text-muted-foreground md:grid-cols-2">
              <div className="rounded-3xl border bg-muted/20 p-4">
                <p className="font-medium text-foreground">O `batch_id` continua existindo</p>
                <p className="mt-1">
                  Ele segue como referencia tecnica e opcao manual de reabertura, mas os lotes
                  recentes ficam salvos no navegador para o usuario continuar de onde parou.
                </p>
              </div>
              <div className="rounded-3xl border bg-muted/20 p-4">
                <p className="font-medium text-foreground">Falhas externas ficam rastreaveis</p>
                <p className="mt-1">
                  Limites, indisponibilidade ou respostas invalidas da IA passam a ser
                  registradas com mais clareza, sem transformar o upload em falso erro.
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

        <div className="grid gap-6">
          <Card className="border-border/70 bg-linear-to-br from-primary/8 via-background to-background shadow-sm">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-xl">
                <FolderClock className="size-5 text-primary" />
                Continuar de onde parou
              </CardTitle>
              <CardDescription>
                Os ultimos lotes ficam salvos neste navegador para reabrir sem digitar codigo.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {recentBatches.length > 0 ? (
                recentBatches.slice(0, 3).map((item) => (
                  <div key={item.batchId} className="rounded-3xl border bg-background/80 p-4 shadow-xs">
                    <div className="flex items-start justify-between gap-3">
                      <div className="space-y-1">
                        <p className="font-medium">{item.batchName}</p>
                        <p className="text-xs text-muted-foreground">
                          {item.totalFiles} arquivo(s) - visto em {formatRelativeDate(item.lastViewedAt)}
                        </p>
                      </div>
                      <StatusBadge value={item.status} />
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Button asChild size="sm" variant="outline">
                        <Link href={`/dashboard?batchId=${item.batchId}`}>Abrir lote</Link>
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
                <div className="rounded-3xl border border-dashed bg-muted/15 p-4 text-sm text-muted-foreground">
                  Nenhum lote recente salvo neste navegador ainda.
                </div>
              )}
            </CardContent>
          </Card>

          <Card className="border-border/70 shadow-sm">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-xl">
                <BadgeCheck className="size-5 text-primary" />
                Atalhos do fluxo
              </CardTitle>
              <CardDescription>
                Entre direto na etapa que faz mais sentido agora.
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3">
              <Button asChild className="justify-between" variant="outline">
                <Link href="/upload">
                  Passo 1. Enviar arquivos
                  <Upload className="size-4" />
                </Link>
              </Button>
              <Button asChild className="justify-between" variant="outline">
                <Link href={latestBatch ? `/dashboard?batchId=${latestBatch.batchId}` : "/dashboard"}>
                  Passo 2. Acompanhar analise
                  <FileSearch className="size-4" />
                </Link>
              </Button>
              <Button asChild className="justify-between" variant="outline">
                <Link href={latestBatch ? `/reports?batchId=${latestBatch.batchId}` : "/reports"}>
                  Passo 4. Exportar resultados
                  <Download className="size-4" />
                </Link>
              </Button>
              <div className="rounded-3xl border bg-muted/20 p-4 text-sm text-muted-foreground">
                <p className="flex items-center gap-2 font-medium text-foreground">
                  <Sparkles className="size-4 text-primary" />
                  Revisao dos dados analisados
                </p>
                <p className="mt-1">
                  Depois que o lote estiver em andamento, o dashboard mostra os documentos, os
                  campos extraidos, as anomalias e as ocorrencias da IA externa.
                </p>
              </div>
            </CardContent>
          </Card>
        </div>
      </section>
    </PageShell>
  );
}
