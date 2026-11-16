import type { PortfolioCash, Timeline, NewsSource, EverythingPreview, EverythingResult, ProjectionResult, WealthInput, WealthItemRow, WealthOverview, NewsFeed, ImportFormats, ImportPreview, StressResult, ActionReview, CacheStatus, OptimizerResult, WatchItem, AssetClass, BenchmarkOption, Bond, BondInput, BseSyncResult, ConnectionsState, CorporateAction, TradeInput, ImportResult, InsightState, Memo, LiveSnapshot, Portfolio, PriceSource, SearchResponse, Settings, SourceId, SyncResult, Trade } from "./types";

declare global {
  interface Window {
    qt?: { engineUrl: string; token: string; platform: string };
  }
}

const BASE = window.qt?.engineUrl ?? import.meta.env.VITE_ENGINE_URL ?? "http://127.0.0.1:8765";
const TOKEN = window.qt?.token ?? "";

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (TOKEN) headers.set("X-QT-Token", TOKEN);
  let res: Response;
  try {
    res = await fetch(BASE + path, { ...init, headers });
  } catch {
    throw new Error("Engine is not reachable");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : `Engine error ${res.status}`);
  }
  return res.json() as Promise<T>;
}

function json<T>(method: string, path: string, body: unknown): Promise<T> {
  return call<T>(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export const api = {
  health: () => call<{ status: string }>("/health"),
  settings: () => call<Settings>("/api/settings"),
  saveSettings: (patch: Partial<Settings>) =>
    call<Settings>("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }),
  metrics: (refresh: boolean) => call<Portfolio>(`/api/metrics?refresh=${refresh}`),
  search: (q: string, market = "ALL") =>
    call<SearchResponse>(`/api/search?q=${encodeURIComponent(q)}&market=${market}`),
  trades: () => call<Trade[]>("/api/ledger/trades"),
  benchmarks: (q: string) =>
    call<{ results: BenchmarkOption[]; online: boolean }>(`/api/benchmarks?q=${encodeURIComponent(q)}`),
  recordTrade: (t: TradeInput) =>
    call<Trade>("/api/ledger/trades", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(t),
    }),
  amendTrade: (id: number, t: TradeInput) =>
    call<Trade>(`/api/ledger/trades/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(t),
    }),
  removeTrade: (id: number) => call<{ deleted: number }>(`/api/ledger/trades/${id}`, { method: "DELETE" }),
  exportCsv: async () => {
    const headers = new Headers();
    if (TOKEN) headers.set("X-QT-Token", TOKEN);
    const res = await fetch(`${BASE}/api/ledger/export`, { headers }).catch(() => null);
    if (!res?.ok) throw new Error("Could not export the ledger");
    const d = new Date();
    const stamp = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    return { blob: await res.blob(), name: `quant-terminal-ledger-${stamp}.csv` };
  },
  actions: () => call<CorporateAction[]>("/api/corporate-actions"),
  refreshMarket: () => call<{ warnings: string[] }>("/api/market/refresh", { method: "POST" }),
  connections: () => call<ConnectionsState>("/api/connections"),
  setPriceSource: (source: PriceSource) => json<ConnectionsState>("PUT", "/api/connections/price-source", { source }),
  saveCredentials: (id: SourceId, values: Record<string, string>) =>
    json<ConnectionsState>("PUT", `/api/connections/${id}/credentials`, { values }),
  removeCredentials: (id: SourceId) =>
    call<ConnectionsState>(`/api/connections/${id}/credentials`, { method: "DELETE" }),
  loginUrl: (id: SourceId) => call<{ url: string }>(`/api/connections/${id}/login-url`),
  openSession: (id: SourceId, value?: string) =>
    json<ConnectionsState>("POST", `/api/connections/${id}/session`, { value: value || null }),
  closeSession: (id: SourceId) => call<ConnectionsState>(`/api/connections/${id}/session`, { method: "DELETE" }),
  sync: (id: SourceId) => call<SyncResult>(`/api/connections/${id}/sync`, { method: "POST" }),
  bonds: () => call<Bond[]>("/api/bonds"),
  saveBond: (id: string, bond: BondInput) => json<Bond>("PUT", `/api/bonds/${encodeURIComponent(id)}`, bond),
  deleteBond: (symbol: string) => call<{ deleted: string }>(`/api/bonds/${encodeURIComponent(symbol)}`, { method: "DELETE" }),
  setAssetClass: (symbol: string, asset_class: AssetClass | "") =>
    json<{ symbol: string; asset_class: AssetClass }>("PUT", `/api/instruments/${encodeURIComponent(symbol)}/asset-class`, { asset_class }),
  bseSync: () => call<BseSyncResult>("/api/corporate-actions/bse-sync", { method: "POST" }),
  reviews: () => call<ActionReview[]>("/api/corporate-actions/review"),
  decideReview: (id: number, decision: "apply" | "skip") =>
    json<{ id: number; review: string }>("POST", `/api/corporate-actions/${id}/review`, { decision }),
  acceptSuggestions: () =>
    call<{ decided: { id: number; decision: string }[]; remaining: number }>(
      "/api/corporate-actions/review/accept-suggestions", { method: "POST" }),
  watchlist: () => call<WatchItem[]>("/api/watchlist"),
  mark: (symbol: string, marks: { starred?: boolean; watched?: boolean }, name?: string) =>
    json<{ watchlist: WatchItem[]; warning: string | null }>("PUT", `/api/watchlist/${encodeURIComponent(symbol)}`, { ...marks, name }),
  history: () => call<WatchItem[]>("/api/history"),
  clearHistory: () => call<WatchItem[]>("/api/history", { method: "DELETE" }),
  forgetVisit: (symbol: string) => call<WatchItem[]>(`/api/history/${encodeURIComponent(symbol)}`, { method: "DELETE" }),
  unwatch: (symbol: string) => call<WatchItem[]>(`/api/watchlist/${encodeURIComponent(symbol)}`, { method: "DELETE" }),
  viewed: (symbol: string, name?: string, exchange?: string) =>
    json<{ symbol: string; tracked: boolean }>("POST", `/api/watchlist/${encodeURIComponent(symbol)}/view`, { name, exchange }),
  cache: () => call<CacheStatus>("/api/cache"),
  prices: (symbol: string, days = 730, fetch = false) =>
    call<{ symbol: string; currency: string; warning: string | null; tracked: boolean; saved: boolean;
           bars: { date: string; close: number; adj_close: number }[] }>(
      `/api/prices/${encodeURIComponent(symbol)}?days=${days}&fetch=${fetch}`),
  pricesCsv: async (symbol: string) => {
    const headers = new Headers();
    if (TOKEN) headers.set("X-QT-Token", TOKEN);
    const res = await fetch(`${BASE}/api/prices/${encodeURIComponent(symbol)}/csv`, { headers });
    if (!res.ok) throw new Error("Nothing cached for this symbol yet");
    return res.blob();
  },
  optimize: (body: { scope?: "portfolio" | "starred" | "both"; symbols?: string[]; lookback_days?: number; max_weight?: number }) =>
    json<OptimizerResult>("POST", "/api/optimizer", body),
  insight: () => call<InsightState>("/api/insight"),
  saveInsightKey: (key: string) =>
    call<InsightState>("/api/insight/key", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key }),
    }),
  removeInsightKey: () => call<InsightState>("/api/insight/key", { method: "DELETE" }),
  insightPreview: () => call<Record<string, unknown>>("/api/insight/preview"),
  createMemo: () => call<Memo>("/api/insight/memo", { method: "POST" }),
  memos: () => call<Memo[]>("/api/insight/memos"),
  importCsv: (file: File, columns?: Record<string, string | null>, headerRow?: number, broker?: string) => {
    const form = new FormData();
    form.append("file", file);
    if (columns) form.append("columns", JSON.stringify(columns));
    if (headerRow != null) form.append("header_row", String(headerRow));
    const q = broker ? `?broker=${encodeURIComponent(broker)}` : "";
    return call<ImportResult>(`/api/ledger/import${q}`, { method: "POST", body: form });
  },
  importPreview: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return call<ImportPreview>("/api/ledger/import/preview", { method: "POST", body: form });
  },
  importFormats: () => call<ImportFormats>("/api/ledger/import/formats"),
  everythingPreview: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return call<EverythingPreview>("/api/import/everything/preview", { method: "POST", body: form });
  },
  importEverything: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return call<EverythingResult>("/api/import/everything", { method: "POST", body: form });
  },
  everythingTemplate: async () => {
    const headers = new Headers();
    if (TOKEN) headers.set("X-QT-Token", TOKEN);
    const res = await fetch(`${BASE}/api/import/everything/template`, { headers });
    return res.blob();
  },
  importTemplate: async () => {
    const headers = new Headers();
    if (TOKEN) headers.set("X-QT-Token", TOKEN);
    const res = await fetch(`${BASE}/api/ledger/import/template`, { headers });
    return res.blob();
  },
  news: (opts: { scope?: "all" | "portfolio" | "watchlist"; symbol?: string; force?: boolean } = {}) => {
    const q = new URLSearchParams({ scope: opts.scope ?? "all" });
    if (opts.symbol) q.set("symbol", opts.symbol);
    if (opts.force) q.set("force", "true");
    return call<NewsFeed>(`/api/news?${q}`);
  },
  newsSources: () => call<NewsSource[]>("/api/news/sources"),
  setNewsSources: (enabled: string[]) => json<NewsSource[]>("PUT", "/api/news/sources", { enabled }),
  wealth: () => call<WealthOverview>("/api/wealth"),
  timeline: () => call<Timeline>("/api/timeline"),
  portfolioCash: () => call<PortfolioCash>("/api/portfolio-cash"),
  withdraw: (date: string, amount: number, note: string) =>
    json<PortfolioCash>("POST", "/api/portfolio-cash/withdrawals", { date, amount, note }),
  deleteWithdrawal: (id: number) => call<PortfolioCash>(`/api/portfolio-cash/withdrawals/${id}`, { method: "DELETE" }),
  addWealth: (item: WealthInput) => json<WealthItemRow>("POST", "/api/wealth", item),
  editWealth: (id: number, item: WealthInput) => json<WealthItemRow>("PUT", `/api/wealth/${id}`, item),
  deleteWealth: (id: number) => call<{ deleted: number }>(`/api/wealth/${id}`, { method: "DELETE" }),
  projection: (body: { mode: "continue" | "fresh"; monthly_sip: number; step_up_pct: number; years: number;
                       interval: "monthly" | "quarterly" | "yearly"; outlook: "past" | "cautious" | "neutral" | "optimistic";
                       include_wealth: boolean; tax_gains_pct: number; gains_exemption: number;
                       tax_interest_pct: number; renew_deposits: boolean }) =>
    json<ProjectionResult>("POST", "/api/projection", body),
  stress: (body: { shock_pct?: number; horizon_days?: number; simulations?: number; history?: boolean }) =>
    json<StressResult>("POST", "/api/stress", body),
};

/** Opens the live tick stream and reconnects on its own if it drops. Returns a stop function. */
export function openTicks(onSnapshot: (s: LiveSnapshot) => void, onDrop: () => void): () => void {
  let ws: WebSocket | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let stopped = false;
  const url = `${BASE.replace(/^http/, "ws")}/ws/ticks${TOKEN ? `?token=${encodeURIComponent(TOKEN)}` : ""}`;
  const connect = () => {
    ws = new WebSocket(url);
    ws.onmessage = (e) => {
      try {
        onSnapshot(JSON.parse(e.data) as LiveSnapshot);
      } catch {
        /* ignore a malformed frame */
      }
    };
    ws.onclose = () => {
      if (stopped) return;
      onDrop();
      timer = setTimeout(connect, 2000);
    };
  };
  connect();
  return () => {
    stopped = true;
    clearTimeout(timer);
    ws?.close();
  };
}
