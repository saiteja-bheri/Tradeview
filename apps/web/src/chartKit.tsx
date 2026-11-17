import { useCallback, useEffect, useRef, useState, type ReactNode, type RefObject } from "react";

/** Plot geometry in viewBox units: total width and the left/right margins. */
export interface PlotX { W: number; L: number; R: number }

/** Fraction across the plot area (0 = left edge, 1 = right edge) for a pointer event. */
export function plotFrac(svg: SVGSVGElement | null, clientX: number, p: PlotX): number {
  if (!svg) return 0;
  const box = svg.getBoundingClientRect();
  const x = ((clientX - box.left) / box.width) * p.W;
  return Math.min(1, Math.max(0, (x - p.L) / (p.W - p.L - p.R)));
}

/** Position in viewBox units for a pointer event. */
export function svgPoint(svg: SVGSVGElement | null, e: { clientX: number; clientY: number }, W: number, H: number) {
  if (!svg) return { x: 0, y: 0 };
  const box = svg.getBoundingClientRect();
  return { x: ((e.clientX - box.left) / box.width) * W, y: ((e.clientY - box.top) / box.height) * H };
}

/**
 * Horizontal zoom and pan for an SVG chart: scroll to zoom around the pointer,
 * drag to pan, double-click to reset. `full` is the whole x range; the visible
 * range never leaves it. `moved` tells a click handler whether the pointer was
 * dragged (so a pan does not also count as a click).
 */
export function useZoomPan(svgRef: RefObject<SVGSVGElement | null>, full: [number, number], p: PlotX,
                           minSpan = (full[1] - full[0]) / 50) {
  const [dom, setDom] = useState<[number, number]>(full);
  const [busy, setBusy] = useState(false);          // true while zooming/panning: animations off
  const drag = useRef<{ x: number; dom: [number, number]; moved: boolean } | null>(null);
  const moved = useRef(false);
  const idle = useRef<ReturnType<typeof setTimeout>>(undefined);
  const lo = full[0], hi = full[1];

  useEffect(() => { setDom([lo, hi]); }, [lo, hi]);

  const pulse = useCallback(() => {
    setBusy(true);
    clearTimeout(idle.current);
    idle.current = setTimeout(() => setBusy(false), 250);
  }, []);

  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();                           // zoom the chart, not the page
      const f = plotFrac(el, e.clientX, p);
      pulse();
      setDom(([a, b]) => {
        const span = b - a;
        const next = Math.min(hi - lo, Math.max(minSpan, span * (e.deltaY < 0 ? 0.8 : 1.25)));
        const centre = a + f * span;
        const na = Math.min(hi - next, Math.max(lo, centre - f * next));
        return [na, na + next];
      });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [svgRef, lo, hi, minSpan, p, pulse]);

  const bind = {
    onPointerDown: (e: React.PointerEvent<SVGSVGElement>) => {
      drag.current = { x: e.clientX, dom, moved: false };
      moved.current = false;
    },
    onPointerMove: (e: React.PointerEvent<SVGSVGElement>) => {
      const d = drag.current;
      if (!d || !svgRef.current) return;
      const box = svgRef.current.getBoundingClientRect();
      const dxPx = e.clientX - d.x;
      if (Math.abs(dxPx) > 3) {
        if (!d.moved) svgRef.current.setPointerCapture(e.pointerId);
        d.moved = true;
        moved.current = true;
      }
      if (!d.moved) return;
      pulse();
      const span = d.dom[1] - d.dom[0];
      const shift = (-dxPx / (box.width * (p.W - p.L - p.R) / p.W)) * span;
      const na = Math.min(hi - span, Math.max(lo, d.dom[0] + shift));
      setDom([na, na + span]);
    },
    onPointerUp: () => { drag.current = null; },
    onPointerLeave: () => { drag.current = null; },
    onDoubleClick: () => setDom([lo, hi]),
  };
  const zoomed = dom[0] > lo + 1e-9 || dom[1] < hi - 1e-9;
  return { dom, setDom, bind, zoomed, reset: () => setDom([lo, hi]), busy, wasDrag: () => moved.current };
}

/** Floating readout placed at a point in viewBox units, flipped to stay inside the chart. */
export function ChartTip({ x, y, W, H, children }: { x: number; y: number; W: number; H: number; children: ReactNode }) {
  const right = x > W * 0.6, low = y > H * 0.55;
  return (
    <div className="pointer-events-none absolute z-20 min-w-[150px] border border-line bg-bg/95 px-2 py-1.5 text-[10.5px] shadow-lg"
         style={{ left: `${(x / W) * 100}%`, top: `${(y / H) * 100}%`,
                  transform: `translate(${right ? "calc(-100% - 10px)" : "10px"}, ${low ? "calc(-100% - 6px)" : "6px"})` }}>
      {children}
    </div>
  );
}

/** Small "zoomed: reset" control and a hint, shown above interactive charts. */
export function ZoomHint({ zoomed, reset, extra }: { zoomed: boolean; reset: () => void; extra?: string }) {
  return (
    <span className="ml-auto flex items-center gap-2 text-[10px] text-dim">
      {extra}
      {zoomed ? (
        <button type="button" onClick={reset} className="border border-line px-1.5 py-0.5 text-ink hover:border-amber">RESET ZOOM</button>
      ) : <span>scroll to zoom · drag to pan</span>}
    </span>
  );
}
