import { useEffect, useRef, useState, type ReactNode } from "react";

/** Wraps a number and flashes green or red for a moment when it changes. */
export function Flash({ value, children }: { value: number | null | undefined; children: ReactNode }) {
  const prev = useRef(value);
  const [cls, setCls] = useState("");
  useEffect(() => {
    const before = prev.current;
    prev.current = value;
    if (before == null || value == null || before === value) return;
    setCls(value > before ? "flash-up" : "flash-down");
    const t = setTimeout(() => setCls(""), 800);
    return () => clearTimeout(t);
  }, [value]);
  return <span className={`rounded-sm px-0.5 ${cls}`}>{children}</span>;
}

export function Empty({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-1 p-6 text-center">
      <div className="text-dim">{title}</div>
      {hint && <div className="max-w-xs text-[10.5px] text-dim/70">{hint}</div>}
    </div>
  );
}

export function Seg<T extends string | number>({
  label, value, options, onChange, hideLabel = false,
}: {
  hideLabel?: boolean;
  label: string;
  value: T | undefined;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div className="flex shrink-0 items-center gap-1.5" role="group" aria-label={label}>
      {!hideLabel && <span className="text-[10px] tracking-widest text-dim">{label}</span>}
      <div className="flex overflow-hidden rounded-sm border border-line">
        {options.map((o) => (
          <button
            type="button"
            key={String(o.value)}
            onClick={() => onChange(o.value)}
            aria-pressed={o.value === value}
            className={`px-2 py-1 text-[10.5px] transition-colors ${
              o.value === value ? "bg-amber font-semibold text-black" : "text-dim hover:bg-raise hover:text-ink"
            }`}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}

/** Eye icon for "watch": outlined when off, filled when on. */
export function EyeIcon({ on, className = "" }: { on: boolean; className?: string }) {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true" className={`inline-block h-3.5 w-3.5 align-[-2px] ${className}`}>
      <path d="M1 8s2.6-4.5 7-4.5S15 8 15 8s-2.6 4.5-7 4.5S1 8 1 8Z" fill={on ? "currentColor" : "none"}
            stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
      <circle cx="8" cy="8" r="2" fill={on ? "var(--color-panel)" : "none"} stroke={on ? "var(--color-panel)" : "currentColor"}
              strokeWidth="1.3" />
    </svg>
  );
}
