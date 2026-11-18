import { useCallback, useEffect } from "react";
import { create } from "zustand";
import { api } from "../api/client";
import type { MarketsOverview, MoversUniverse } from "../api/types";
import { useStore } from "./store";

export type MarketsWindow = 21 | 63 | 252;
const REFRESH_MS = 5 * 60_000;

function saved<T>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    const v = (typeof fallback === "number" ? Number(raw) : raw) as T;
    return allowed.includes(v) ? v : fallback;
  } catch {
    return fallback;
  }
}

function keep(key: string, v: string | number) {
  try { localStorage.setItem(key, String(v)); } catch { /* optional */ }
}

interface MarketsState {
  universe: MoversUniverse;
  window: MarketsWindow;
  data: MarketsOverview | null;
  loading: boolean;
  error: string | null;
  setUniverse: (u: MoversUniverse) => void;
  setWindow: (w: MarketsWindow) => void;
  load: () => Promise<void>;
  /** Loads unless a load started in the last 30 s: several cards share one request. */
  loadIfStale: () => void;
}

let startedAt = 0;

let seq = 0;

/** One shared copy of the Markets page data for all its cards. */
export const useMarketsStore = create<MarketsState>((set, get) => ({
  universe: saved<MoversUniverse>("qt.markets.universe", ["nifty50", "nifty500", "mine"], "nifty50"),
  window: saved<MarketsWindow>("qt.markets.window", [21, 63, 252], 63),
  data: null,
  loading: false,
  error: null,
  setUniverse: (universe) => { keep("qt.markets.universe", universe); set({ universe }); get().load(); },
  setWindow: (window) => { keep("qt.markets.window", window); set({ window }); get().load(); },
  loadIfStale: () => {
    if (Date.now() - startedAt > 30_000) get().load();
  },
  load: async () => {
    startedAt = Date.now();
    const mine = ++seq;
    set({ loading: true });
    try {
      const data = await api.marketsOverview(get().universe, get().window);
      if (mine === seq) set({ data, error: null });
    } catch (e) {
      if (mine === seq) set({ error: (e as Error).message });
    } finally {
      if (mine === seq) set({ loading: false });
    }
  },
}));

/** Loads the Markets data when the page is shown, then every five minutes while it stays shown. */
export function useMarkets() {
  const state = useMarketsStore();
  const visible = useStore((s) => s.page === "markets" && s.status === "ok");
  const load = useMarketsStore((s) => s.load);
  const loadIfStale = useMarketsStore((s) => s.loadIfStale);
  useEffect(() => {
    if (!visible) return;
    loadIfStale();
    const t = setInterval(loadIfStale, REFRESH_MS);
    return () => clearInterval(t);
  }, [visible, loadIfStale]);
  const retry = useCallback(() => load(), [load]);
  return { ...state, retry };
}
