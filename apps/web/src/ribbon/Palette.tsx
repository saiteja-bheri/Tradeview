import { Command } from "cmdk";
import { useEffect } from "react";
import { ticker } from "../format";
import type { Holding } from "../api/types";
import { useStore } from "../state/store";

const NONE: Holding[] = [];
const BENCHMARKS = [
  ["^NSEI", "NIFTY 50"], ["^BSESN", "SENSEX"], ["^CRSLDX", "NIFTY 500"], ["^NSEBANK", "NIFTY BANK"],
  ["^NSMIDCP", "NIFTY NEXT 50"], ["NIFTYMIDCAP150.NS", "NIFTY MIDCAP 150"], ["BSE-500.BO", "BSE 500"],
] as const;

export function Palette() {
  const open = useStore((s) => s.paletteOpen);
  const setOpen = useStore((s) => s.setPalette);
  const holdings = useStore((s) => s.portfolio?.holdings) ?? NONE;
  const { select, setParam, refreshPrices, resetLayout } = useStore.getState();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen(!useStore.getState().paletteOpen);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setOpen]);

  const run = (fn: () => void) => () => {
    setOpen(false);
    fn();
  };
  const item =
    "flex cursor-pointer items-center justify-between px-3 py-1.5 data-[selected=true]:bg-amber data-[selected=true]:text-black";
  const group = "[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:tracking-widest [&_[cmdk-group-heading]]:text-dim";

  return (
    <Command.Dialog
      open={open}
      onOpenChange={setOpen}
      label="Command palette"
      overlayClassName="fixed inset-0 z-40 bg-black/60"
      contentClassName="fixed left-1/2 top-24 z-50 w-[460px] max-w-[92vw] -translate-x-1/2 border border-amber bg-panel shadow-2xl"
    >
      <Command.Input
        placeholder="Type a command or ticker…"
        className="w-full border-b border-line bg-transparent px-3 py-2.5 text-amber outline-none placeholder:text-dim"
      />
      <Command.List className="max-h-80 overflow-auto py-1">
        <Command.Empty className="px-3 py-3 text-dim">No matching command.</Command.Empty>
        {holdings.length > 0 && (
          <Command.Group heading="HOLDINGS" className={group}>
            {holdings.map((h) => (
              <Command.Item key={h.symbol} value={`chart ${ticker(h.symbol)}`} className={item}
                            onSelect={run(() => select(h.symbol))}>
                <span>Chart {ticker(h.symbol)}</span>
              </Command.Item>
            ))}
          </Command.Group>
        )}
        <Command.Group heading="RISK PARAMETERS" className={group}>
          {BENCHMARKS.map(([symbol, name]) => (
            <Command.Item key={symbol} className={item}
                          onSelect={run(() => setParam({ benchmark: symbol, benchmark_name: name }))}>
              Benchmark: {name}
            </Command.Item>
          ))}
          <Command.Item className={item} onSelect={run(() => setParam({ confidence: 0.95 }))}>VaR confidence: 95%</Command.Item>
          <Command.Item className={item} onSelect={run(() => setParam({ confidence: 0.99 }))}>VaR confidence: 99%</Command.Item>
          {[1, 2, 3, 5, 10].map((d) => (
            <Command.Item key={`v${d}`} className={item} onSelect={run(() => setParam({ horizon_days: d }))}>
              VaR horizon: {d} day{d > 1 ? "s" : ""}
            </Command.Item>
          ))}
          {([[1, "1 day"], [5, "1 week"], [10, "2 weeks"], [21, "1 month"], [63, "3 months"], [126, "6 months"],
             [252, "1 year"]] as const).map(([d, label]) => (
            <Command.Item key={`c${d}`} className={item} onSelect={run(() => setParam({ cov_horizon_days: d }))}>
              Covariance horizon: {label}
            </Command.Item>
          ))}
        </Command.Group>
        <Command.Group heading="WORKSPACE" className={group}>
          <Command.Item className={item}
                        onSelect={run(() => useStore.getState().setImportOpen(true))}>
            Import trades (CSV or Excel, any broker)
          </Command.Item>
          <Command.Item className={item} onSelect={run(() => useStore.getState().exportCsv())}>
            Export ledger as CSV
          </Command.Item>
          <Command.Item className={item}
                        onSelect={run(() => useStore.getState().setConnectOpen(true))}>
            Connect brokers and price sources
          </Command.Item>
          <Command.Item className={item}
                        onSelect={run(() => useStore.getState().setBondsOpen(true))}>
            Add or edit bonds
          </Command.Item>
          <Command.Item className={item}
                        onSelect={run(() => useStore.getState().setReviewOpen(true))}>
            Check splits and bonus issues against uploaded trades
          </Command.Item>
          <Command.Item className={item} onSelect={run(() => refreshPrices())}>Refresh prices</Command.Item>
          <Command.Item className={item} onSelect={run(() => resetLayout())}>Reset layout</Command.Item>
        </Command.Group>
      </Command.List>
    </Command.Dialog>
  );
}
