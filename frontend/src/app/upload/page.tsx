"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  FileArchive,
  FileSearch,
  FileText,
  Info,
  Send,
  Sparkles,
  Upload,
} from "lucide-react";

import { PageShell } from "@/components/app/page-shell";
import { StatusBadge } from "@/components/app/status-badge";
import { saveRecentBatch } from "@/lib/recent-batches";
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
import { Separator } from "@/components/ui/separator";
import { ApiError, UploadBatchResponse, apiUploadBatch } from "@/services/api";

const ALLOWED_EXTENSIONS = [".txt", ".zip"];
const MAX_FILE_SIZE_BYTES = Number(process.env.NEXT_PUBLIC_UPLOAD_MAX_FILE_SIZE_BYTES ?? 5_242_880);
const MAX_TOTAL_SIZE_BYTES = Number(process.env.NEXT_PUBLIC_UPLOAD_MAX_TOTAL_SIZE_BYTES ?? 31_457_280);

function formatBytes(totalBytes: number): string {
  if (totalBytes < 1024) return `${totalBytes} B`;
  if (totalBytes < 1024 * 1024) return `${(totalBytes / 1024).toFixed(1)} KB`;
  return `${(totalBytes / (1024 * 1024)).toFixed(2)} MB`;
}

function validateSelectedFiles(nextFiles: File[]): string | null {
  let totalBytes = 0;

  for (const file of nextFiles) {
    const lowerName = file.name.toLowerCase();
    const isAllowed = ALLOWED_EXTENSIONS.some((extension) => lowerName.endsWith(extension));
    if (!isAllowed) {
      return `O arquivo ${file.name} nao e suportado. Envie apenas .txt ou .zip.`;
    }
    if (file.size === 0) {
      return `O arquivo ${file.name} esta vazio e nao pode ser enviado.`;
    }
    if (file.size > MAX_FILE_SIZE_BYTES) {
      return `O arquivo ${file.name} excede o limite de ${formatBytes(MAX_FILE_SIZE_BYTES)} por arquivo.`;
    }
    totalBytes += file.size;
  }

  if (totalBytes > MAX_TOTAL_SIZE_BYTES) {
    return `O lote selecionado excede o limite total de ${formatBytes(MAX_TOTAL_SIZE_BYTES)}.`;
  }

  return null;
}

export default function UploadPage() {
  const router = useRouter();
  const [batchName, setBatchName] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [loading, setLoading] = useState(false);
  const [redirecting, setRedirecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<UploadBatchResponse | null>(null);

  const fileCount = files.length;
  const totalBytes = useMemo(
    () => files.reduce((sum, file) => sum + file.size, 0),
    [files],
  );

  useEffect(() => {
    if (!result) {
      return;
    }

    setRedirecting(true);
    saveRecentBatch({
      batchId: result.batch_id,
      batchName: result.batch_name,
      status: result.status,
      totalFiles: result.total_files,
    });

    const timer = window.setTimeout(() => {
      router.push(`/dashboard?batchId=${result.batch_id}`);
    }, 1200);

    return () => window.clearTimeout(timer);
  }, [result, router]);

  function resetUploadState() {
    setFiles([]);
    setBatchName("");
    setError(null);
    setResult(null);
    setRedirecting(false);
  }

  function handleFileSelection(nextFiles: File[]) {
    // Valida na selecao para o usuario receber feedback antes do envio.
    const validationError = validateSelectedFiles(nextFiles);
    setResult(null);
    setRedirecting(false);
    if (validationError) {
      setFiles([]);
      setError(validationError);
      return;
    }
    setError(null);
    setFiles(nextFiles);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setResult(null);
    setRedirecting(false);

    if (files.length === 0) {
      setError("Selecione ao menos um arquivo .txt ou .zip.");
      return;
    }
    const validationError = validateSelectedFiles(files);
    if (validationError) {
      setError(validationError);
      return;
    }

    setLoading(true);
    try {
      const response = await apiUploadBatch(files, batchName);
      setResult(response);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Falha ao enviar o lote.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <PageShell
      title="Passo 1. Enviar arquivos"
      description="Envie um lote de documentos e deixe o sistema abrir automaticamente a tela de acompanhamento quando o upload for aceito."
      navItems={[
        { href: "/", label: "Inicio" },
        { href: "/upload", label: "Enviar arquivos", active: true },
        { href: "/dashboard", label: "Acompanhar" },
        { href: "/reports", label: "Exportar" },
      ]}
    >
      <section className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
        <Card className="border-border/70 shadow-sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-xl">
              <Upload className="size-5 text-primary" />
              Envio do lote
            </CardTitle>
            <CardDescription>
              Aceita multiplos `.txt` ou um `.zip` com entradas `.txt`. O processamento segue em
              background depois do aceite.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-5" onSubmit={handleSubmit}>
              <div className="space-y-2">
                <Label htmlFor="batch-name">Nome do lote</Label>
                <Input
                  id="batch-name"
                  placeholder="Ex: Lote fornecedor abril"
                  value={batchName}
                  onChange={(event) => setBatchName(event.target.value)}
                />
                <p className="text-sm text-muted-foreground">
                  Opcional. Use um nome facil de reconhecer depois no acompanhamento.
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="batch-files">Arquivos</Label>
                <Input
                  id="batch-files"
                  type="file"
                  accept=".txt,.zip,text/plain,application/zip"
                  multiple
                  onChange={(event) => handleFileSelection(Array.from(event.target.files ?? []))}
                />
                <p className="text-sm text-muted-foreground">
                  Depois do envio, voce sera levado para a tela de acompanhamento do lote.
                  Limites atuais: {formatBytes(MAX_FILE_SIZE_BYTES)} por arquivo e{" "}
                  {formatBytes(MAX_TOTAL_SIZE_BYTES)} por lote.
                </p>
              </div>

              {fileCount > 0 ? (
                <div className="rounded-3xl border bg-muted/20 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <p className="font-medium text-foreground">
                        {fileCount} arquivo(s) selecionado(s)
                      </p>
                      <p className="text-sm text-muted-foreground">
                        Tamanho total: {formatBytes(totalBytes)}
                      </p>
                    </div>
                    <StatusBadge value="queued" />
                  </div>

                  <Separator className="my-4" />

                  <div className="grid gap-2">
                    {files.slice(0, 8).map((file) => {
                      const isZip = file.name.toLowerCase().endsWith(".zip");
                      const Icon = isZip ? FileArchive : FileText;
                      return (
                        <div
                          key={`${file.name}-${file.size}`}
                          className="flex items-center justify-between gap-3 rounded-2xl border bg-background px-3 py-2"
                        >
                          <div className="flex min-w-0 items-center gap-3">
                            <Icon className="size-4 shrink-0 text-primary" />
                            <span className="truncate text-sm font-medium">{file.name}</span>
                          </div>
                          <span className="shrink-0 text-xs text-muted-foreground">
                            {formatBytes(file.size)}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ) : null}

              {error ? (
                <Alert variant="destructive">
                  <Info className="size-4" />
                  <AlertTitle>Falha no envio</AlertTitle>
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              ) : null}

              <div className="flex flex-wrap gap-3">
                <Button disabled={loading || redirecting} type="submit">
                  <Send className="size-4" />
                  {loading ? "Enviando..." : redirecting ? "Abrindo acompanhamento..." : "Enviar lote"}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={resetUploadState}
                >
                  Limpar
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>

        <div className="grid gap-6">
          <Card className="border-border/70 bg-linear-to-br from-primary/8 via-background to-background shadow-sm">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-xl">
                <Sparkles className="size-5 text-primary" />
                O que acontece depois
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm text-muted-foreground">
              <div className="rounded-3xl border bg-background/90 p-4">
                <p className="font-medium text-foreground">1. O lote e aceito</p>
                <p className="mt-1">
                  O sistema registra o lote e guarda o `batch_id` como referencia tecnica.
                </p>
              </div>
              <div className="rounded-3xl border bg-background/90 p-4">
                <p className="font-medium text-foreground">2. A leitura comeca</p>
                <p className="mt-1">
                  Parser local, validacao por IA e regras de anomalia seguem em background.
                </p>
              </div>
              <div className="rounded-3xl border bg-background/90 p-4">
                <p className="font-medium text-foreground">3. Voce acompanha tudo</p>
                <p className="mt-1">
                  O dashboard mostra progresso, documentos, dados extraidos e ocorrencias da IA.
                </p>
              </div>
              <div className="rounded-3xl border bg-background/90 p-4">
                <p className="font-medium text-foreground">4. Exporta quando fizer sentido</p>
                <p className="mt-1">
                  Quando quiser, gere `results.csv`, `anomalies.csv` e `audit.csv`.
                </p>
              </div>
            </CardContent>
          </Card>

          {result ? (
            <Card className="border-border/70 shadow-sm">
              <CardHeader>
                <CardTitle className="text-xl">Lote aceito</CardTitle>
                <CardDescription>
                  O upload deu certo e o acompanhamento sera aberto automaticamente.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="rounded-3xl border bg-muted/20 p-4">
                  <p className="text-xs font-medium uppercase tracking-[0.24em] text-muted-foreground">
                    referencia tecnica
                  </p>
                  <p className="mt-2 break-all font-mono text-sm">{result.batch_id}</p>
                </div>
                <div className="flex flex-wrap items-center gap-3">
                  <StatusBadge value={result.status} />
                  <span className="text-sm text-muted-foreground">
                    {result.total_files} arquivo(s) agendado(s)
                  </span>
                </div>
                <div className="flex flex-wrap gap-3">
                  <Button onClick={() => router.push(`/dashboard?batchId=${result.batch_id}`)}>
                    <FileSearch className="size-4" />
                    Abrir acompanhamento agora
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => router.push(`/reports?batchId=${result.batch_id}`)}
                  >
                    Abrir exportacoes
                  </Button>
                </div>
              </CardContent>
            </Card>
          ) : (
            <Card className="border-dashed border-border/80 shadow-none">
              <CardHeader>
                <CardTitle className="text-xl">Precisa continuar um lote?</CardTitle>
                <CardDescription>
                  Se voce ja enviou um lote antes, pode retomar o acompanhamento ou ir direto para a exportacao.
                </CardDescription>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-3">
                <Button asChild variant="outline">
                  <Link href="/dashboard">Abrir acompanhamento</Link>
                </Button>
                <Button asChild variant="outline">
                  <Link href="/reports">Abrir exportacoes</Link>
                </Button>
              </CardContent>
            </Card>
          )}
        </div>
      </section>
    </PageShell>
  );
}
