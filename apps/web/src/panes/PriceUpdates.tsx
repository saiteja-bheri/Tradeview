import { num, ticker } from "../format";
import { useStore } from "../state/store";
import { Empty } from "../ui";

function clock(tsSeconds: number): string {
  return new Date(tsSeconds * 1000).toLocaleTimeString("en-IN", { hour12: false });
}

/** Recent live price updates for the selected stock. The feeds deliver price
 *  snapshots, not individual trades, so this is deliberately not called a tape. */
export function PriceUpdates() {
  const selected = useStore((s) => s.selected);
  const ticks = useStore((s) => (s.selected ? s.ticks[s.selected] : undefined));
  const feed = useStore((s) => s.live?.status);
  const held = useStore((s) => !!s.selected && (s.portfolio?.holdings.some((h) => h.symbol === s.selected) ?? false));

  const note = (
    <div className="border-b border-line px-3 py-2 text-[11px] text-dim">
      Live price snapshots for your holdings, not individual trades.
    </div>
  );

  let body;
  if (!selected) body = <Empty title="No stock selected" />;
  else if (!feed || feed.state === "off")
    body = <Empty title="Live feed is off" hint="Choose a price source in Settings → Connections." />;
  else if (!held && !ticks?.length)
    body = <Empty title={`No live updates for ${ticker(selected)}`} hint="Live updates cover the stocks you hold." />;
  else if (!ticks?.length)
    body = <Empty title="Waiting for the first update" hint="Prices appear here as the feed sends them." />;
  else
    body = (
      <table className="grid-table">
        <thead>
          <tr><th className="l">Time</th><th className="r">Price</th><th className="r">Change</th></tr>
        </thead>
        <tbody>
          {ticks.map((t, i) => {
            const before = ticks[i + 1]?.price;
            const diff = before == null ? null : t.price - before;
            return (
              <tr key={`${t.ts}-${i}`}>
                <td className="l text-dim">{clock(t.ts)}</td>
                <td className="r">{num(t.price)}</td>
                <td className={`r ${diff == null || diff === 0 ? "text-dim" : diff > 0 ? "text-up" : "text-down"}`}>
                  {diff == null ? "—" : `${diff > 0 ? "+" : ""}${num(diff)}`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    );

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between px-3 pt-2 text-[10.5px] tracking-widest text-dim">
        <span>PRICE UPDATES{selected ? ` · ${ticker(selected)}` : ""}</span>
        {ticks?.length ? <span>{ticks.length} shown</span> : null}
      </div>
      {note}
      <div className="min-h-0 flex-1 overflow-auto">{body}</div>
    </div>
  );
}
