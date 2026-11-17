import { useEffect } from "react";
import { PageWorkspace } from "./layout/PageWorkspace";
import { Rail } from "./layout/Rail";
import { TopBar } from "./layout/TopBar";
import { Palette } from "./ribbon/Palette";
import { BondsDialog } from "./ribbon/BondsDialog";
import { SettingsPage } from "./settings/SettingsPage";
import { ImportDialog } from "./ribbon/ImportDialog";
import { ReviewDialog } from "./ribbon/ReviewDialog";
import { useStore } from "./state/store";

const DOCK_PAGES = ["markets", "portfolio", "chart", "analytics", "plan"] as const;

export function App() {
  const init = useStore((s) => s.init);
  const error = useStore((s) => s.error);
  const notice = useStore((s) => s.notice);
  const dismiss = useStore((s) => s.dismiss);
  const page = useStore((s) => s.page);

  useEffect(() => {
    init();
  }, [init]);

  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(dismiss, 6000);
    return () => clearTimeout(t);
  }, [notice, dismiss]);

  return (
    <div className="flex h-full flex-col">
      <TopBar />
      {(error || notice) && (
        <div role="status"
             className={`flex items-center justify-between border-b border-line px-3 py-1.5 ${
               error ? "bg-down/15 text-down" : "bg-up/10 text-up"
             }`}>
          <span>{error ?? notice}</span>
          <button onClick={dismiss} aria-label="Dismiss" className="px-1 text-dim hover:text-ink">✕</button>
        </div>
      )}
      <div className="flex min-h-0 flex-1">
        <Rail />
        {/* Every page stays mounted so charts and scroll positions survive switching. */}
        <main className="relative min-w-0 flex-1">
          {DOCK_PAGES.map((p) => (
            <div key={p} className={`absolute inset-0 ${page === p ? "" : "invisible"}`} aria-hidden={page !== p}>
              <PageWorkspace page={p} />
            </div>
          ))}
          <div className={`absolute inset-0 ${page === "settings" ? "" : "invisible"}`} aria-hidden={page !== "settings"}>
            <SettingsPage />
          </div>
        </main>
      </div>
      <Palette />
      <BondsDialog />
      <ReviewDialog />
      <ImportDialog />
    </div>
  );
}
