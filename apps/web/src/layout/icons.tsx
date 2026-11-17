import type { PageId } from "../state/store";

/** Rail icons: simple line drawings, 20px, drawn in the current text colour. */
const PATHS: Record<PageId, React.JSX.Element> = {
  markets: (
    <>
      <circle cx="10" cy="10" r="7.25" />
      <path d="M2.75 10h14.5M10 2.75c2 2.1 3 4.5 3 7.25s-1 5.15-3 7.25M10 2.75c-2 2.1-3 4.5-3 7.25s1 5.15 3 7.25" />
    </>
  ),
  portfolio: (
    <>
      <rect x="2.75" y="5.75" width="14.5" height="10.5" rx="2" />
      <path d="M7 5.75V4.5a1.25 1.25 0 0 1 1.25-1.25h3.5A1.25 1.25 0 0 1 13 4.5v1.25M2.75 10h14.5" />
    </>
  ),
  chart: <path d="M2.75 16.25h14.5M4.5 13l3.5-4 3 2.5 4.5-6" />,
  analytics: (
    <>
      <path d="M10 2.75v14.5M4 6.5h12" />
      <path d="M4 6.5 2 11a2.25 2.25 0 0 0 4 0L4 6.5ZM16 6.5 14 11a2.25 2.25 0 0 0 4 0l-2-4.5Z" />
    </>
  ),
  plan: (
    <>
      <circle cx="10" cy="10" r="7.25" />
      <circle cx="10" cy="10" r="3.75" />
      <circle cx="10" cy="10" r="0.6" fill="currentColor" />
    </>
  ),
  settings: (
    <>
      <circle cx="10" cy="10" r="2.5" />
      <path d="M10 2.5v2M10 15.5v2M2.5 10h2M15.5 10h2M4.7 4.7l1.4 1.4M13.9 13.9l1.4 1.4M4.7 15.3l1.4-1.4M13.9 6.1l1.4-1.4" />
    </>
  ),
};

export function PageIcon({ page, className = "" }: { page: PageId; className?: string }) {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true" className={`h-5 w-5 ${className}`}
         fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      {PATHS[page]}
    </svg>
  );
}
