import type { IJsonModel } from "flexlayout-react";
import type { PageId } from "../state/store";

type Tab = { type: "tab"; name: string; component: string };
const tab = (name: string, component: string): Tab => ({ type: "tab", name, component });
const tabs = (weight: number, ...children: Tab[]) => ({ type: "tabset" as const, weight, children });

/** Shared settings for every page. The gaps between cards are the splitters,
 *  sized by --fl-splitter-size in index.css. */
const GLOBAL: IJsonModel["global"] = {
  tabEnableClose: false, tabSetEnableMaximize: true, tabSetMinWidth: 200, tabSetMinHeight: 140,
};

const model = (layout: IJsonModel["layout"]): IJsonModel => ({ global: GLOBAL, layout });

/** Default arrangement of each dockable page; the user's own arrangement is
 *  saved per page and these are only the starting point. */
export const DEFAULT_LAYOUTS: Record<Exclude<PageId, "settings">, IJsonModel> = {
  markets: model({
    type: "row",
    children: [{
      type: "row", weight: 100,
      children: [
        { type: "row", weight: 48, children: [tabs(55, tab("INDEXES", "indexes")), tabs(45, tab("GLOBAL MARKETS", "global"))] },
        { type: "row", weight: 52, children: [
          tabs(40, tab("HEAT MAP", "heatmap")), tabs(35, tab("NEWS", "news")), tabs(25, tab("TOP MOVERS", "movers")),
        ] },
      ],
    }],
  }),
  portfolio: model({
    type: "row",
    children: [
      tabs(65, tab("HOLDINGS", "holdings")),
      tabs(35, tab("TRADES", "trades"), tab("CORP ACTIONS", "actions"), tab("WATCHLIST", "watchlist"), tab("HISTORY", "history")),
    ],
  }),
  chart: model({
    type: "row",
    children: [
      tabs(70, tab("CHART", "chart")),
      { type: "row", weight: 30, children: [tabs(55, tab("STOCK", "stock")), tabs(45, tab("PRICE UPDATES", "updates"))] },
    ],
  }),
  analytics: model({
    type: "row",
    children: [
      tabs(28, tab("RISK", "risk"), tab("STRESS TEST", "stress")),
      tabs(48, tab("PERFORMANCE", "performance"), tab("COVARIANCE", "covariance"), tab("OPTIMIZER", "optimizer")),
      tabs(24, tab("AI INSIGHT", "insight")),
    ],
  }),
  plan: model({
    type: "row",
    children: [tabs(50, tab("PLAN (SIP)", "plan")), tabs(50, tab("WEALTH", "wealth"))],
  }),
};

export interface PageDef {
  id: PageId;
  label: string;
}

/** Rail order. Settings sits apart at the bottom of the rail. */
export const PAGES: PageDef[] = [
  { id: "markets", label: "Markets" },
  { id: "portfolio", label: "Portfolio" },
  { id: "chart", label: "Chart" },
  { id: "analytics", label: "Analytics" },
  { id: "plan", label: "Plan" },
  { id: "settings", label: "Settings" },
];

export const layoutKey = (page: PageId) => `qt.layout.${page}.v1`;
