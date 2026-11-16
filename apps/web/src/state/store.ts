import { create } from "zustand";
import { api, openTicks } from "../api/client";
import { setDisplay } from "../format";
import type { WatchItem, CorporateAction, LiveSnapshot, Portfolio, Settings, Trade, TradeInput } from "../api/types";

type Status = "connecting" | "ok" | "down";

interface State {
  status: Status;
  busy: boolean;
  error: string | null;
  notice: string | null;
  portfolio: Portfolio | null;
  live: LiveSnapshot | null;
  trades: Trade[];
  actions: CorporateAction[];
  selected: string | null;
  paletteOpen: boolean;
  connectOpen: boolean;
  reviewOpen: boolean;
  watch: WatchItem[];
  setReviewOpen: (open: boolean) => void;
  loadWatchlist: () => Promise<void>;
  toggleStar: (symbol: string, name?: string) => Promise<void>;
  toggleWatch: (symbol: string, name?: string) => Promise<void>;
  history: WatchItem[];
  loadHistory: () => Promise<void>;
  openSymbol: (symbol: string, name?: string, exchange?: string) => void;
  /** Exchange each symbol was picked from in the search (NASDAQ, NYSE...), for the chart. */
  exchanges: Record<string, string>;
  bondsOpen: boolean;
  layoutEpoch: number;
  init: () => Promise<void>;
  reload: (refresh?: boolean) => Promise<void>;
  setParam: (patch: Partial<Settings>) => Promise<void>;
  importCsv: (file: File, columns?: Record<string, string | null>, headerRow?: number, broker?: string) => Promise<void>;
  importEverything: (file: File) => Promise<string[]>;
  importOpen: boolean;
  setImportOpen: (open: boolean) => void;
  exportCsv: () => Promise<void>;
  saveTrade: (input: TradeInput, id?: number) => Promise<boolean>;
  removeTrade: (id: number) => Promise<void>;
  refreshPrices: () => Promise<void>;
  select: (symbol: string | null) => void;
  setPalette: (open: boolean) => void;
  setConnectOpen: (open: boolean) => void;
  setBondsOpen: (open: boolean) => void;
  resetLayout: () => void;
  dismiss: () => void;
}

let ticksOpen = false;
let promptedReviews = 0;
let seq = 0; // drops responses that arrive after a newer request was sent

export const useStore = create<State>((set, get) => ({
  status: "connecting",
  busy: false,
  error: null,
  notice: null,
  portfolio: null,
  live: null,
  trades: [],
  actions: [],
  selected: null,
  paletteOpen: false,
  connectOpen: false,
  reviewOpen: false,
  importOpen: false,
  setImportOpen: (open) => set({ importOpen: open }),
  watch: [],
  setReviewOpen: (open) => set({ reviewOpen: open }),
  loadWatchlist: async () => {
    try {
      set({ watch: await api.watchlist() });
    } catch {
      /* the watchlist is optional */
    }
  },
  toggleStar: async (symbol, name) => {
    const starred = get().watch.some((w) => w.symbol === symbol && w.starred);
    try {
      const r = await api.mark(symbol, { starred: !starred }, name);
      set({ watch: r.watchlist, notice: r.warning ?? (starred ? `${symbol} removed from the optimizer list` : `${symbol} starred for the optimizer`) });
    } catch (e) {
      set({ error: (e as Error).message });
    }
  },
  toggleWatch: async (symbol, name) => {
    const watched = get().watch.some((w) => w.symbol === symbol && w.watched);
    try {
      const r = await api.mark(symbol, { watched: !watched }, name);
      set({ watch: r.watchlist, notice: r.warning ?? (watched ? `${symbol} removed from the watchlist` : `${symbol} added to the watchlist; prices cached`) });
      get().loadHistory();
    } catch (e) {
      set({ error: (e as Error).message });
    }
  },
  history: [],
  loadHistory: async () => {
    try {
      set({ history: await api.history() });
    } catch {
      /* history is optional */
    }
  },
  exchanges: {},
  openSymbol: (symbol, name, exchange) => {
    set((s) => ({ selected: symbol, exchanges: exchange ? { ...s.exchanges, [symbol]: exchange } : s.exchanges }));
    // Recorded in History only: nothing is downloaded for a stock you just look at.
    api.viewed(symbol, name, exchange).then(() => get().loadHistory()).catch(() => {});
  },
  bondsOpen: false,
  layoutEpoch: 0,

  init: async () => {
    for (let attempt = 0; attempt < 40; attempt++) {
      try {
        await api.health();
        set({ status: "ok" });
        if (!ticksOpen) {
          ticksOpen = true;
          openTicks(
            (live) => set({ live }),
            () => set((s) => (s.live ? { live: { ...s.live, status: { ...s.live.status, state: "connecting" } } } : {})),
          );
        }
        await get().reload(true);
        get().loadWatchlist();
        get().loadHistory();
        return;
      } catch {
        await new Promise((r) => setTimeout(r, 500));
      }
    }
    set({ status: "down", error: "Engine is not reachable" });
  },

  reload: async (refresh = true) => {
    const mine = ++seq;
    set({ busy: true });
    try {
      const portfolio = await api.metrics(refresh);
      const [trades, actions] = await Promise.all([api.trades(), api.actions()]);
      if (mine !== seq) return;
      const selected = get().selected ?? portfolio.holdings[0]?.symbol ?? null;
      setDisplay(portfolio.display);
      set({ portfolio, trades, actions, selected, status: "ok", error: null });
      // New splits or bonuses to confirm: open the check once per new batch.
      const pending = portfolio.pending_reviews ?? 0;
      if (pending > promptedReviews) set({ reviewOpen: true });
      promptedReviews = pending;
    } catch (e) {
      if (mine === seq) set({ error: (e as Error).message });
    } finally {
      if (mine === seq) set({ busy: false });
    }
  },

  setParam: async (patch) => {
    const current = get().portfolio;
    if (current) set({ portfolio: { ...current, params: { ...current.params, ...patch } } });
    try {
      await api.saveSettings(patch);
      await get().reload(true);
    } catch (e) {
      set({ error: (e as Error).message });
      await get().reload(false);
    }
  },

  importCsv: async (file, columns, headerRow, broker) => {
    set({ busy: true, error: null });
    try {
      const r = await api.importCsv(file, columns, headerRow, broker);
      const from = r.broker ? ` from ${r.broker[0].toUpperCase()}${r.broker.slice(1)}` : "";
      const parts = [`${r.imported} trades imported${from}`];
      if (r.updated) parts.push(`${r.updated} updated from the file`);
      if (r.duplicates) parts.push(`${r.duplicates} already in ledger`);
      if (r.skipped.length) parts.push(`${r.skipped.length} rows skipped`);
      set({ notice: parts.join(" · ") });
      await get().reload(true);
    } catch (e) {
      set({ error: (e as Error).message, busy: false });
    }
  },

  importEverything: async (file) => {
    set({ busy: true, error: null });
    try {
      const r = await api.importEverything(file);
      const t = r.totals;
      const parts = [`${t.trades} trades`, `${t.bonds} bonds`, `${t.wealth} wealth items imported or updated`];
      if (t.trade_duplicates) parts.push(`${t.trade_duplicates} trades already in ledger`);
      if (r.skipped.length) parts.push(`${r.skipped.length} rows skipped`);
      set({ notice: parts.join(" · ") });
      await get().reload(true);
      return r.skipped;
    } catch (e) {
      set({ error: (e as Error).message, busy: false });
      return [];
    }
  },

  exportCsv: async () => {
    try {
      const { blob, name } = await api.exportCsv();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
      set({ notice: `Ledger exported as ${name}` });
    } catch (e) {
      set({ error: (e as Error).message });
    }
  },

  saveTrade: async (input, id) => {
    try {
      if (id == null) await api.recordTrade(input);
      else await api.amendTrade(id, input);
      set({ notice: id == null ? "Trade recorded in the ledger" : "Trade updated", error: null });
      await get().reload(true);
      return true;
    } catch (e) {
      set({ error: (e as Error).message });
      return false;
    }
  },

  removeTrade: async (id) => {
    try {
      await api.removeTrade(id);
      set({ notice: "Trade removed from the ledger", error: null });
      await get().reload(true);
    } catch (e) {
      set({ error: (e as Error).message });
    }
  },

  refreshPrices: async () => {
    set({ busy: true });
    try {
      await api.refreshMarket();
      await get().reload(false);
    } catch (e) {
      set({ error: (e as Error).message, busy: false });
    }
  },

  select: (symbol) => set({ selected: symbol }),
  setPalette: (open) => set({ paletteOpen: open }),
  setConnectOpen: (open) => set({ connectOpen: open }),
  setBondsOpen: (open) => set({ bondsOpen: open }),
  resetLayout: () => set((s) => ({ layoutEpoch: s.layoutEpoch + 1 })),
  dismiss: () => set({ error: null, notice: null }),
}));
