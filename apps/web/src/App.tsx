import { useEffect } from "react";
import { Workspace } from "./layout/Workspace";
import { Palette } from "./ribbon/Palette";
import { Ribbon } from "./ribbon/Ribbon";
import { BondsDialog } from "./ribbon/BondsDialog";
import { ConnectionsDialog } from "./ribbon/ConnectionsDialog";
import { ImportDialog } from "./ribbon/ImportDialog";
import { ReviewDialog } from "./ribbon/ReviewDialog";
import { useStore } from "./state/store";

export function App() {
  const init = useStore((s) => s.init);
  const error = useStore((s) => s.error);
  const notice = useStore((s) => s.notice);
  const dismiss = useStore((s) => s.dismiss);

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
      <Ribbon />
      {(error || notice) && (
        <div role="status"
             className={`flex items-center justify-between border-b border-line px-3 py-1.5 ${
               error ? "bg-down/15 text-down" : "bg-up/10 text-up"
             }`}>
          <span>{error ?? notice}</span>
          <button onClick={dismiss} aria-label="Dismiss" className="px-1 text-dim hover:text-ink">✕</button>
        </div>
      )}
      <Workspace />
      <Palette />
      <ConnectionsDialog />
      <BondsDialog />
      <ReviewDialog />
      <ImportDialog />
    </div>
  );
}
