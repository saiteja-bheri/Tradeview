import type { Mover, MoversUniverse } from "../api/types";
import { num, ticker } from "../format";
import { useMarkets } from "../state/markets";
import { useStore } from "../state/store";
import { Seg } from "../ui";
import { MarketsLoading, MarketsOffline, changeText, changeTone } from "./marketsShared";

const UNIVERSES: { value: MoversUniverse; label: string }[] = [
  { value: "nifty50", label: "NIFTY 50" }, { value: "nifty500", label: "NIFTY 500" }, { value: "mine", label: "MY STOCKS" },
];

/** The day's biggest gainers and losers, from the NIFTY 50, the NIFTY 500 or your own stocks. */
export function MoversCard() {
  const { data, loading, error, retry, universe, setUniverse } = useMarkets();
  const openSymbol = useStore((s) => s.openSymbol);

  const table = (title: string, rows: Mover[], empty: string) => (
    <div>
      <div className="px-3 pb-1 pt-2 text-[10.5px] tracking-widest text-dim">{title}</div>
      {rows.length === 0 ? (
        <div className="px-3 py-1 text-[11px] text-dim/70">{empty}</div>
      ) : (
        <table className="grid-table">
          <tbody>
            {rows.map((m) => (
              <tr key={m.symbol} className="cursor-pointer hover:bg-raise" onClick={() => openSymbol(m.symbol, m.name)}>
                <td className="l text-cyan">{ticker(m.symbol)}</td>
                <td className="l max-w-[140px] truncate text-dim" title={m.name}>{m.name !== ticker(m.symbol) ? m.name : ""}</td>
                <td className="r">{num(m.last)}</td>
                <td className={`r ${changeTone(m.change_pct)}`}>{changeText(m.change_pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );

  let body;
  if (!data) body = error ? <MarketsOffline error={error} retry={retry} loading={loading} /> : <MarketsLoading />;
  else if (!data.online) body = <MarketsOffline error={null} retry={retry} loading={loading} />;
  else if (data.movers.universe !== universe)   // switched lists: the new one is still loading
    body = (
      <div className="px-3 py-3 text-[11px] text-dim">
        Loading {UNIVERSES.find((u) => u.value === universe)?.label}…
        {universe === "nifty500" && " The first load of 500 prices takes about 10 seconds."}
      </div>
    );
  else if (data.movers.note)
    body = <div className="px-3 py-3 text-[11px] text-amber">⚠ {data.movers.note}</div>;
  else
    body = (
      <>
        {table("TOP GAINERS", data.movers.gainers, "Nothing is up today.")}
        {table("TOP LOSERS", data.movers.losers, "Nothing is down today.")}
        {universe === "mine" && !data.movers.gainers.length && !data.movers.losers.length && (
          <div className="px-3 py-2 text-[11px] text-dim">Hold, watch or star stocks to see them here.</div>
        )}
      </>
    );

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-end px-3 pt-2">
        <Seg<MoversUniverse> label="UNIVERSE" value={universe} options={UNIVERSES} onChange={setUniverse} hideLabel />
      </div>
      <div className="min-h-0 flex-1 overflow-auto">{body}</div>
    </div>
  );
}
