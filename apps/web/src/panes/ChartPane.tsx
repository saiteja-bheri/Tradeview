import { useEffect, useState } from "react";
import { bseListing, embedHasData, tradingViewSymbol } from "../chartSymbol";
import { ticker } from "../format";
import { useStore } from "../state/store";
import { Empty } from "../ui";
import { PriceChart } from "./PriceChart";

type Source = "yahoo" | "tradingview";

/** Price chart for the selected symbol.
 *  * YAHOO: interactive chart of daily closes (pan, zoom, pick any date window).
 *    Held, watched and starred stocks come from the local cache.
 *  * TRADINGVIEW: TradingView's embed on the listing's own exchange, where its free
 *    embed has data (BSE, US, XETRA, Euronext, TSX). Downloads nothing into the cache.
 *  Default: Yahoo for stocks whose prices are kept; TradingView for stocks you only
 *  looked at, when it covers them, so browsing costs no downloads. */
export function ChartPane() {
  const selected = useStore((s) => s.selected);
  const exchange = useStore((s) => {
    const sym = s.selected;
    if (!sym) return undefined;
    return s.exchanges[sym] || s.history.find((h) => h.symbol === sym)?.exchange
      || s.watch.find((w) => w.symbol === sym)?.exchange || undefined;
  });
  const kept = useStore((s) => {
    const sym = s.selected;
    if (!sym) return false;
    return (s.portfolio?.holdings.some((h) => h.symbol === sym) ?? false)
      || s.watch.some((w) => w.symbol === sym && (w.watched || w.starred));
  });
  const tv = selected ? tradingViewSymbol(selected, exchange) : "";
  const canEmbed = !!selected && !selected.startsWith("MF:") && embedHasData(tv);
  // NSE stocks: TradingView only has the BSE listing, so it is an opt-in, labelled view.
  const bse = selected && !canEmbed ? bseListing(selected) : null;
  const tvShown = canEmbed ? tv : bse;
  const nse = !!selected && selected.toUpperCase().endsWith(".NS");
  const [source, setSource] = useState<Source>("yahoo");

  useEffect(() => {
    setSource(!kept && canEmbed ? "tradingview" : "yahoo");
  }, [selected, kept, canEmbed]);

  if (!selected) return <Empty title="No symbol selected" hint="Pick a holding or search a stock by name in the top bar." />;
  if (selected.startsWith("BOND:"))
    return <Empty title="No market chart for this bond"
                  hint="Bonds tracked by hand are valued at the price you set under Add or edit bonds." />;

  const tab = (s: Source, label: string) => (
    <button onClick={() => setSource(s)} aria-pressed={source === s}
            className={`-ml-px border px-1.5 py-0.5 first:ml-0 ${source === s ? "relative z-10 border-accent bg-accent text-black" : "border-line text-dim hover:text-ink"}`}>
      {label}
    </button>
  );

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between gap-2 border-b border-line px-3 py-1 text-[10px] tracking-widest text-dim">
        <span className="truncate">
          {source === "tradingview" && tvShown
            ? bse
              ? <>TRADINGVIEW · {bse} · <span className="text-amber">BSE LISTING (TRADINGVIEW HAS NO NSE DATA)</span></>
              : `TRADINGVIEW · ${tv}`
            : `YAHOO FINANCE · ${ticker(selected)}${nse ? " · NSE" : ""}`}
        </span>
        {tvShown && (
          <span className="flex shrink-0">
            {tab("yahoo", bse ? "NSE · YAHOO" : "YAHOO")}
            {tab("tradingview", bse ? "BSE · TRADINGVIEW" : "TRADINGVIEW")}
          </span>
        )}
      </div>
      <div className="min-h-0 flex-1">
        {source === "tradingview" && tvShown
          ? <TradingView key={tvShown} symbol={tvShown} />
          : <PriceChart key={selected} symbol={selected} />}
      </div>
    </div>
  );
}

function TradingView({ symbol }: { symbol: string }) {
  const params = new URLSearchParams({
    symbol,
    interval: "D",
    theme: "dark",
    style: "1",
    timezone: "Asia/Kolkata",
    locale: "en",
    withdateranges: "1",
    hide_side_toolbar: "0",
    allow_symbol_change: "1",
    save_image: "0",
    toolbar_bg: "#12161b",
  });
  return (
    <iframe
      title={`${symbol} chart`}
      src={`https://s.tradingview.com/widgetembed/?${params}`}
      className="h-full w-full border-0"
      sandbox="allow-scripts allow-same-origin allow-popups"
      referrerPolicy="no-referrer"
    />
  );
}
