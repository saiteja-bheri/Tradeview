import { Layout, Model, type TabNode } from "flexlayout-react";
import { useMemo } from "react";
import { ActionsPane } from "../panes/ActionsPane";
import { ChartPane } from "../panes/ChartPane";
import { CovariancePane } from "../panes/CovariancePane";
import { FactorsPane } from "../panes/FactorsPane";
import { GlobalMarketsCard } from "../panes/GlobalMarketsCard";
import { HeatmapPane } from "../panes/HeatmapPane";
import { HistoryPane } from "../panes/HistoryPane";
import { HoldingsPane } from "../panes/HoldingsPane";
import { IndexesCard } from "../panes/IndexesCard";
import { InsightPane } from "../panes/InsightPane";
import { MoversCard } from "../panes/MoversCard";
import { NewsPane } from "../panes/NewsPane";
import { OptimizerPane } from "../panes/OptimizerPane";
import { PerformancePane } from "../panes/PerformancePane";
import { PlanPane } from "../panes/PlanPane";
import { PriceUpdates } from "../panes/PriceUpdates";
import { RiskPane } from "../panes/RiskPane";
import { StockPanel } from "../panes/StockPanel";
import { StressPane } from "../panes/StressPane";
import { TradesPane } from "../panes/TradesPane";
import { WatchlistPane } from "../panes/WatchlistPane";
import { WealthPane } from "../panes/WealthPane";
import { type PageId, useStore } from "../state/store";
import { DEFAULT_LAYOUTS, layoutKey } from "./pages";

export const PANES: Record<string, () => React.JSX.Element> = {
  holdings: HoldingsPane, trades: TradesPane, actions: ActionsPane, watchlist: WatchlistPane, history: HistoryPane,
  chart: ChartPane, stock: StockPanel, updates: PriceUpdates,
  indexes: IndexesCard, global: GlobalMarketsCard, movers: MoversCard, heatmap: HeatmapPane, news: NewsPane,
  risk: RiskPane, stress: StressPane, performance: PerformancePane, covariance: CovariancePane,
  optimizer: OptimizerPane, insight: InsightPane, plan: PlanPane, wealth: WealthPane, factors: FactorsPane,
};

type DockPage = Exclude<PageId, "settings">;

/** The saved arrangement, or the default when there is none, it is unreadable,
 *  or it names a pane this version does not have. */
export function loadModel(page: DockPage, fresh: boolean): Model {
  if (!fresh) {
    try {
      const saved = localStorage.getItem(layoutKey(page));
      if (saved) {
        const m = Model.fromJson(JSON.parse(saved));
        let known = true;
        m.visitNodes((n) => {
          if (n.getType() === "tab" && !PANES[(n as TabNode).getComponent() ?? ""]) known = false;
        });
        if (known) return m;
      }
    } catch {
      /* corrupt or unavailable storage: fall back to the default */
    }
  }
  return Model.fromJson(DEFAULT_LAYOUTS[page]);
}

/** One page's dockable cards. */
export function PageWorkspace({ page }: { page: DockPage }) {
  const epoch = useStore((s) => s.layoutEpochs[page] ?? 0);
  const model = useMemo(() => loadModel(page, epoch > 0), [page, epoch]);
  return (
    <div className="relative h-full min-h-0 p-2">
      <div className="relative h-full">
        <Layout
          key={epoch}
          model={model}
          factory={(node: TabNode) => {
            const Pane = PANES[node.getComponent() ?? ""];
            return Pane ? <Pane /> : null;
          }}
          onModelChange={(m) => {
            try {
              localStorage.setItem(layoutKey(page), JSON.stringify(m.toJson()));
            } catch {
              /* layout just won't persist */
            }
          }}
        />
      </div>
    </div>
  );
}
