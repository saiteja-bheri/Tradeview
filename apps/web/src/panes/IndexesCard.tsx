import { ColorType, CrosshairMode, createChart, type Time } from "lightweight-charts";
import { useEffect, useRef } from "react";
import { num } from "../format";
import { type MarketsWindow, useMarkets } from "../state/markets";
import { Seg } from "../ui";
import { MarketsLoading, MarketsOffline, changeText, changeTone, cssVar } from "./marketsShared";

const LINE_COLOURS = ["#14d9a5", "#9b8cff", "#f5c76a", "#55c8f2"];
const WINDOWS: { value: MarketsWindow; label: string }[] = [
  { value: 21, label: "1M" }, { value: 63, label: "3M" }, { value: 252, label: "1Y" },
];

/** Indian index levels and their path over the chosen window, as % change so they share one axis. */
export function IndexesCard() {
  const { data, loading, error, retry, window, setWindow } = useMarkets();
  const box = useRef<HTMLDivElement>(null);
  const indexes = data?.indexes ?? [];

  useEffect(() => {
    if (!box.current || !indexes.length) return;
    const dim = cssVar("--color-dim", "#8a94a3"), line = cssVar("--color-line", "#232a33");
    const bg = cssVar("--color-panel", "#12161b");
    const chart = createChart(box.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: bg }, textColor: dim, fontSize: 11 },
      grid: { vertLines: { visible: false }, horzLines: { color: line } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, fixLeftEdge: true, fixRightEdge: true },
      crosshair: { mode: CrosshairMode.Normal },
      localization: { priceFormatter: (v: number) => `${v > 0 ? "+" : ""}${(v * 100).toFixed(1)}%` },
    });
    indexes.forEach((ix, i) => {
      const s = chart.addLineSeries({ color: LINE_COLOURS[i % LINE_COLOURS.length], lineWidth: 2,
                                      priceLineVisible: false, lastValueVisible: false });
      s.setData((ix.series ?? []).map((p) => ({ time: p.date as Time, value: p.pct })));
    });
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [indexes]);

  if (!data) return error ? <MarketsOffline error={error} retry={retry} loading={loading} /> : <MarketsLoading />;
  if (!data.online) return <MarketsOffline error={null} retry={retry} loading={loading} />;

  return (
    <div className="flex h-full flex-col p-3">
      <div className="mb-2 flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-wrap gap-x-5 gap-y-1">
          {indexes.map((ix, i) => (
            <div key={ix.symbol} className="min-w-0">
              <div className="flex items-center gap-1.5 text-[11px] text-dim">
                <span className="inline-block h-2.5 w-0.5 rounded" style={{ background: LINE_COLOURS[i % LINE_COLOURS.length] }} />
                {ix.name}
              </div>
              <div className="font-mono">
                {num(ix.last)} <span className={changeTone(ix.change_pct)}>{changeText(ix.change_pct)}</span>
              </div>
            </div>
          ))}
        </div>
        <Seg<MarketsWindow> label="WINDOW" value={window} options={WINDOWS} onChange={setWindow} hideLabel />
      </div>
      <div ref={box} className="min-h-0 flex-1" />
    </div>
  );
}
