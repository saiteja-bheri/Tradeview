import type { ReactNode } from "react";
import { type SectionId, useStore } from "../state/store";
import { AboutSection, AiSection, ConnectionsSection, DataSection, DisplaySection, NewsSection, ResetCard, RiskSection } from "./sections";

export const SECTIONS: { id: SectionId; label: string; view: () => ReactNode }[] = [
  { id: "risk", label: "Risk", view: RiskSection },
  { id: "connections", label: "Connections", view: ConnectionsSection },
  { id: "display", label: "Display", view: DisplaySection },
  { id: "ai", label: "AI insight", view: AiSection },
  { id: "news", label: "News", view: NewsSection },
  { id: "data", label: "Data", view: () => <><DataSection /><ResetCard /></> },
  { id: "about", label: "About", view: AboutSection },
];

/** Settings: section list on the left, the chosen section on the right. */
export function SettingsPage() {
  const section = useStore((s) => s.settingsSection);
  const open = useStore((s) => s.openSettings);
  const current = SECTIONS.find((s) => s.id === section) ?? SECTIONS[0];
  const View = current.view;
  return (
    <div className="flex h-full min-h-0 gap-2 p-2">
      <nav aria-label="Settings sections" className="w-[220px] shrink-0 rounded-lg border border-line bg-panel py-3">
        <h1 className="px-4 pb-3 text-[17px] font-semibold">Settings</h1>
        {SECTIONS.map((s) => {
          const on = s.id === current.id;
          return (
            <button key={s.id} onClick={() => open(s.id)} aria-current={on ? "page" : undefined}
                    className={`block w-full border-l-2 px-4 py-2 text-left ${
                      on ? "border-accent bg-raise text-ink" : "border-transparent text-dim hover:bg-raise/60 hover:text-ink"}`}>
              {s.label}
            </button>
          );
        })}
      </nav>
      <div className="min-w-0 flex-1 overflow-auto rounded-lg">
        <div className="max-w-[820px] space-y-2">
          <View />
        </div>
      </div>
    </div>
  );
}
