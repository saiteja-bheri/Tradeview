import { useEffect } from "react";
import { type PageId, useStore } from "../state/store";
import { PageIcon } from "./icons";
import { PAGES } from "./pages";

const MOD = typeof navigator !== "undefined" && navigator.platform.toLowerCase().includes("mac") ? "⌘" : "Ctrl+";

/** True when the key press belongs to a text field, so page shortcuts stay out of the way. */
export function typingIn(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
}

/** Left rail: one button per page, Settings at the bottom; Ctrl/⌘+1…6 switch pages. */
export function Rail() {
  const page = useStore((s) => s.page);
  const setPage = useStore((s) => s.setPage);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.altKey || e.shiftKey || typingIn(e.target)) return;
      const n = Number(e.key);
      if (Number.isInteger(n) && n >= 1 && n <= PAGES.length) {
        e.preventDefault();
        setPage(PAGES[n - 1].id);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setPage]);

  const button = (id: PageId, label: string, n: number) => {
    const on = page === id;
    return (
      <button key={id} onClick={() => setPage(id)} aria-label={label} aria-current={on ? "page" : undefined}
              title={`${label}  ${MOD}${n}`}
              className={`relative flex h-11 w-11 items-center justify-center rounded-xl transition-colors ${
                on ? "bg-accent/15 text-accent" : "text-dim hover:bg-raise hover:text-ink"}`}>
        {on && <span className="absolute -left-[7px] top-2.5 h-6 w-[3px] rounded-r bg-accent" aria-hidden="true" />}
        <PageIcon page={id} />
      </button>
    );
  };

  const main = PAGES.filter((p) => p.id !== "settings");
  return (
    <nav aria-label="Pages" className="flex w-14 shrink-0 flex-col items-center gap-1.5 border-r border-line bg-panel py-2">
      {main.map((p, i) => button(p.id, p.label, i + 1))}
      <div className="mt-auto">{button("settings", "Settings", PAGES.length)}</div>
    </nav>
  );
}
