import { Badge } from "@/components/ui/badge";

type StatusBadgeProps = {
  value: string | null | undefined;
};

const STATUS_LABELS: Record<string, string> = {
  pending: "aguardando",
  processing: "processando",
  queued: "na fila",
  local_parsing: "leitura local",
  llm_validation: "validacao por IA",
  rule_evaluation: "checando anomalias",
  completed: "concluido",
  completed_with_errors: "concluido com alertas",
  cancelling: "cancelando",
  cancelled: "cancelado",
  failed: "falhou",
  error: "erro",
  done: "concluido",
  success: "sucesso",
  partial: "parcial",
  fallback: "fallback local",
  skipped: "nao acionado",
  local_ready: "pronto no parser local",
  queued_llm: "na fila da IA",
  llm_processing: "IA em andamento",
  high: "alta",
  medium: "media",
  low: "baixa",
};

function resolveVariant(value: string): "default" | "secondary" | "outline" | "destructive" {
  const normalized = value.toLowerCase();

  if (["error", "failed", "cancelled", "destructive", "high"].includes(normalized)) {
    return "destructive";
  }

  if (["cancelling", "completed_with_errors", "partial", "warn", "warning", "medium"].includes(normalized)) {
    return "secondary";
  }

  if (["pending", "processing", "queued", "local_parsing", "llm_validation", "rule_evaluation", "low"].includes(normalized)) {
    return "outline";
  }

  return "default";
}

export function StatusBadge({ value }: StatusBadgeProps) {
  const rawValue = value?.trim() || "desconhecido";
  const normalized = rawValue.toLowerCase();
  const label =
    STATUS_LABELS[normalized] ??
    normalized
      .replaceAll("_", " ")
      .trim();

  return <Badge variant={resolveVariant(rawValue)}>{label}</Badge>;
}
