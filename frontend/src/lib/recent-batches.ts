export type RecentBatch = {
  batchId: string;
  batchName: string;
  status: string;
  totalFiles: number;
  createdAt: string;
  lastViewedAt: string;
};

type RecentBatchInput = {
  batchId: string;
  batchName?: string;
  status?: string;
  totalFiles?: number;
  createdAt?: string;
};

const STORAGE_KEY = "nlc-recent-batches";
// Um lote removido sai apenas do historico deste navegador. Ele continua
// existindo no backend e pode reaparecer se o usuario abri-lo novamente.
const DISMISSED_STORAGE_KEY = "nlc-dismissed-recent-batches";
const MAX_RECENT_BATCHES = 6;

// Confere se o ambiente atual permite usar localStorage.
function hasStorage(): boolean {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

// Valida e normaliza o objeto salvo localmente antes de usa-lo na interface.
function normalizeRecentBatch(value: unknown): RecentBatch | null {
  if (!value || typeof value !== "object") {
    return null;
  }

  const candidate = value as Partial<RecentBatch>;
  if (typeof candidate.batchId !== "string" || !candidate.batchId.trim()) {
    return null;
  }

  return {
    batchId: candidate.batchId.trim(),
    batchName:
      typeof candidate.batchName === "string" && candidate.batchName.trim()
        ? candidate.batchName.trim()
        : "Lote recente",
    status:
      typeof candidate.status === "string" && candidate.status.trim()
        ? candidate.status.trim()
        : "processing",
    totalFiles:
      typeof candidate.totalFiles === "number" && Number.isFinite(candidate.totalFiles)
        ? candidate.totalFiles
        : 0,
    createdAt:
      typeof candidate.createdAt === "string" && candidate.createdAt.trim()
        ? candidate.createdAt
        : new Date().toISOString(),
    lastViewedAt:
      typeof candidate.lastViewedAt === "string" && candidate.lastViewedAt.trim()
        ? candidate.lastViewedAt
        : new Date().toISOString(),
  };
}

// Lista os lotes que o usuario decidiu esconder do historico local.
function listDismissedBatchIds(): string[] {
  if (!hasStorage()) {
    return [];
  }

  try {
    const rawValue = window.localStorage.getItem(DISMISSED_STORAGE_KEY);
    if (!rawValue) {
      return [];
    }

    const parsedValue = JSON.parse(rawValue);
    if (!Array.isArray(parsedValue)) {
      return [];
    }

    return parsedValue
      .filter((item): item is string => typeof item === "string" && item.trim().length > 0)
      .map((item) => item.trim());
  } catch {
    return [];
  }
}

// Persiste a lista de lotes escondidos apenas no navegador atual.
function saveDismissedBatchIds(batchIds: string[]): void {
  if (!hasStorage()) {
    return;
  }

  window.localStorage.setItem(DISMISSED_STORAGE_KEY, JSON.stringify(batchIds));
}

// Le os lotes recentes salvos no navegador e remove entradas invalidas.
export function listRecentBatches(): RecentBatch[] {
  if (!hasStorage()) {
    return [];
  }

  try {
    const rawValue = window.localStorage.getItem(STORAGE_KEY);
    if (!rawValue) {
      return [];
    }

    const parsedValue = JSON.parse(rawValue);
    if (!Array.isArray(parsedValue)) {
      return [];
    }

    const dismissedBatchIds = new Set(listDismissedBatchIds());

    return parsedValue
      .map(normalizeRecentBatch)
      .filter((item): item is RecentBatch => item !== null)
      .filter((item) => !dismissedBatchIds.has(item.batchId));
  } catch {
    return [];
  }
}

// Atualiza ou adiciona um lote recente sem duplicar entradas no historico.
export function saveRecentBatch(input: RecentBatchInput): RecentBatch[] {
  if (!hasStorage() || !input.batchId.trim()) {
    return [];
  }

  const normalizedBatchId = input.batchId.trim();
  if (listDismissedBatchIds().includes(normalizedBatchId)) {
    return listRecentBatches();
  }

  const now = new Date().toISOString();
  const existingItems = listRecentBatches();
  const currentItem = existingItems.find((item) => item.batchId === normalizedBatchId);
  const nextItem: RecentBatch = {
    batchId: normalizedBatchId,
    batchName: input.batchName?.trim() || currentItem?.batchName || "Lote recente",
    status: input.status?.trim() || currentItem?.status || "processing",
    totalFiles: input.totalFiles ?? currentItem?.totalFiles ?? 0,
    createdAt: input.createdAt || currentItem?.createdAt || now,
    lastViewedAt: now,
  };

  const nextItems = currentItem
    ? existingItems.map((item) => (item.batchId === normalizedBatchId ? nextItem : item))
    : [nextItem, ...existingItems].slice(0, MAX_RECENT_BATCHES);

  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(nextItems));
  return nextItems;
}

// Retorna o lote mais recente visivel para retomar a navegacao.
export function getMostRecentBatch(): RecentBatch | null {
  return listRecentBatches()[0] ?? null;
}

// Remove um lote apenas do historico local e marca como oculto.
export function removeRecentBatch(batchId: string): RecentBatch[] {
  const normalizedBatchId = batchId.trim();
  if (!hasStorage() || !normalizedBatchId) {
    return listRecentBatches();
  }

  const nextItems = listRecentBatches().filter((item) => item.batchId !== normalizedBatchId);
  const nextDismissedBatchIds = [
    normalizedBatchId,
    ...listDismissedBatchIds().filter((item) => item !== normalizedBatchId),
  ];

  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(nextItems));
  saveDismissedBatchIds(nextDismissedBatchIds);
  return nextItems;
}

// Reverte a ocultacao local de um lote quando ele e aberto novamente.
export function restoreRecentBatch(batchId: string): void {
  const normalizedBatchId = batchId.trim();
  if (!hasStorage() || !normalizedBatchId) {
    return;
  }

  saveDismissedBatchIds(listDismissedBatchIds().filter((item) => item !== normalizedBatchId));
}
