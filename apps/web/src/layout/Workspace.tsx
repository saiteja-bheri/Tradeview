import { Layout, Model, type IJsonModel, type TabNode } from "flexlayout-react";
import { useMemo } from "react";
import { ActionsPane } from "../panes/ActionsPane";
import { ChartPane } from "../panes/ChartPane";
import { CovariancePane } from "../panes/CovariancePane";
import { HistoryPane } from "../panes/HistoryPane";
import { HoldingsPane } from "../panes/HoldingsPane";
import { InsightPane } from "../panes/InsightPane";
import { NewsPane } from "../panes/NewsPane";
import { PerformancePane } from "../panes/PerformancePane";
import { PlanPane } from "../panes/PlanPane";
import { OptimizerPane } from "../panes/OptimizerPane";
import { RiskPane } from "../panes/RiskPane";
import { StressPane } from "../panes/StressPane";
import { TradesPane } from "../panes/TradesPane";
import { WatchlistPane } from "../panes/WatchlistPane";
import { WealthPane } from "../panes/WealthPane";
import { useStore } from "../state/store";

const KEY = "qt.layout.v8"; // v8 adds PERFORMANCE

const DEFAULT: IJsonModel = {
  global: { tabEnableClose: false, tabSetEnableMaximize: true, tabSetMinWidth: 180, tabSetMinHeight: 120 },
  layout: {
    type: "row",
    children: [
      {
        type: "tabset", weight: 28,
        children: [
          { type: "tab", name: "HOLDINGS", component: "holdings" },
          { type: "tab", name: "WEALTH", component: "wealth" },
          { type: "tab", name: "TRADES", component: "trades" },
          { type: "tab", name: "CORP ACTIONS", component: "actions" },
          { type: "tab", name: "WATCHLIST", component: "watchlist" },
          { type: "tab", name: "HISTORY", component: "history" },
        ],
      },
      {
        type: "tabset", weight: 48,
        children: [
          { type: "tab", name: "PERFORMANCE", component: "performance" },
          { type: "tab", name: "CHART", component: "chart" },
          { type: "tab", name: "NEWS", component: "news" },
          { type: "tab", name: "COVARIANCE", component: "covariance" },
          { type: "tab", name: "OPTIMIZER", component: "optimizer" },
          { type: "tab", name: "PLAN (SIP)", component: "plan" },
        ],
      },
      {
        type: "tabset", weight: 24,
        children: [
          { type: "tab", name: "RISK", component: "risk" },
          { type: "tab", name: "STRESS TEST", component: "stress" },
          { type: "tab", name: "AI INSIGHT", component: "insight" },
        ],
      },
    ],
  },
};

const PANES: Record<string, () => React.JSX.Element> = {
  holdings: HoldingsPane,
  trades: TradesPane,
  actions: ActionsPane,
  chart: ChartPane,
  covariance: CovariancePane,
  risk: RiskPane,
  insight: InsightPane,
  watchlist: WatchlistPane,
  history: HistoryPane,
  news: NewsPane,
  wealth: WealthPane,
  plan: PlanPane,
  performance: PerformancePane,
  optimizer: OptimizerPane,
  stress: StressPane,
};

function loadModel(fresh: boolean): Model {
  if (!fresh) {
    try {
      const saved = localStorage.getItem(KEY);
      if (saved) return Model.fromJson(JSON.parse(saved));
    } catch {
      /* corrupt or unavailable storage: fall back to the default layout */
    }
  }
  return Model.fromJson(DEFAULT);
}

export function Workspace() {
  const epoch = useStore((s) => s.layoutEpoch);
  const model = useMemo(() => loadModel(epoch > 0), [epoch]);
  return (
    <div className="relative min-h-0 flex-1">
      <Layout
        key={epoch}
        model={model}
        factory={(node: TabNode) => {
          const Pane = PANES[node.getComponent() ?? ""];
          return Pane ? <Pane /> : null;
        }}
        onModelChange={(m) => {
          try {
            localStorage.setItem(KEY, JSON.stringify(m.toJson()));
          } catch {
            /* layout just won't persist */
          }
        }}
      />
    </div>
  );
}
