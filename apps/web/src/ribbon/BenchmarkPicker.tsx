import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { BenchmarkOption } from "../api/types";
import { useStore } from "../state/store";

const KIND: Record<BenchmarkOption["kind"], string> = { INDEX: "INDEX", ETF: "ETF", FUND: "FUND", STOCK: "STOCK" };

/** Benchmark for beta and alpha: built-in indices and ETFs, or anything found by search. */
export function BenchmarkPicker({ hideLabel = false }: { hideLabel?: boolean } = {}) {
  const params = useStore((s) => s.portfolio?.params);
  const setParam = useStore((s) => s.setParam);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [options, setOptions] = useState<BenchmarkOption[]>([]);
  const [online, setOnline] = useState(true);
  const [loading, setLoading] = useState(false);
  const [active, setActive] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const seq = useRef(0);
  const q = query.trim();

  useEffect(() => {
    if (!open) return;
    const mine = ++seq.current;
    setLoading(true);
    const timer = setTimeout(async () => {
      try {
        const r = await api.benchmarks(q);
        if (mine !== seq.current) return;
        setOptions(r.results);
        setOnline(r.online);
        setActive(0);
      } catch {
        if (mine === seq.current) setOptions([]);
      } finally {
        if (mine === seq.current) setLoading(false);
      }
    }, q ? 200 : 0);
    return () => clearTimeout(timer);
  }, [open, q]);

  useEffect(() => {
    if (!open) return;
    inputRef.current?.focus();
    const onDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [open]);

  useEffect(() => {
    listRef.current?.children[active]?.scrollIntoView({ block: "nearest" });
  }, [active]);

  const pick = (o: BenchmarkOption) => {
    setParam({ benchmark: o.symbol, benchmark_name: o.name });
    setOpen(false);
    setQuery("");
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (options.length) {
        const step = e.key === "ArrowDown" ? 1 : -1;
        setActive((a) => (a + step + options.length) % options.length);
      }
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (options[active]) pick(options[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  const name = params?.benchmark_name || params?.benchmark || "—";

  return (
    <div ref={rootRef} className="relative flex shrink-0 items-center gap-1.5">
      {!hideLabel && <span className="text-[10px] tracking-widest text-dim">BENCH</span>}
      <button
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        title={params ? `${name} (${params.benchmark})` : undefined}
        className="flex max-w-40 items-center gap-1.5 rounded-sm border border-line bg-accent px-2 py-1 text-[10.5px] font-semibold text-black"
      >
        <span className="truncate uppercase">{name}</span>
        <span aria-hidden="true" className="text-[8px]">▼</span>
      </button>

      {open && (
        <div className="absolute left-0 top-full z-30 mt-1 w-[25rem] max-w-[90vw] border border-accent bg-panel shadow-2xl">
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Search any index, ETF or mutual fund"
            aria-label="Search benchmarks"
            spellCheck={false}
            autoComplete="off"
            className="w-full border-b border-line bg-transparent px-3 py-2 text-accent outline-none placeholder:text-dim/60"
          />
          {options.length === 0 ? (
            <div className="px-3 py-2 text-dim">
              {loading ? "Searching…" : online ? "No matching benchmark." : "Market search is offline."}
            </div>
          ) : (
            <ul ref={listRef} role="listbox" aria-label="Benchmarks" className="max-h-80 overflow-auto py-1">
              {options.map((o, i) => {
                const on = i === active;
                const current = o.symbol === params?.benchmark;
                return (
                  <li
                    key={o.symbol}
                    role="option"
                    aria-selected={on}
                    onMouseDown={(e) => { e.preventDefault(); pick(o); }}
                    onMouseMove={() => setActive(i)}
                    className={`flex cursor-pointer items-center gap-3 px-3 py-1.5 ${on ? "bg-accent text-black" : ""}`}
                  >
                    <span className="w-3 shrink-0 text-center">{current ? "✓" : ""}</span>
                    <span className="min-w-0 flex-1 truncate">{o.name}</span>
                    <span className={`shrink-0 text-[10px] ${on ? "text-black/70" : "text-dim"}`}>{o.symbol}</span>
                    <span className={`w-10 shrink-0 text-right text-[10px] tracking-widest ${on ? "text-black/70" : "text-dim"}`}>
                      {KIND[o.kind]}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
          {!online && options.length > 0 && (
            <div className="border-t border-line px-3 py-1 text-[10px] text-dim">
              Market search is offline. Showing the built-in list only.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
