const DASH = "—";

export function num(v: number | null | undefined, digits = 2): string {
  if (v == null) return DASH;
  return v.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** Money is held in rupees; it is shown in the display currency chosen in the
 *  ribbon, converted at the latest rate the engine reports. */
const SYMBOLS: Record<string, string> = {
  INR: "₹", USD: "$", EUR: "€", GBP: "£", JPY: "¥", AED: "AED ", SGD: "S$", AUD: "A$", CAD: "C$",
  CHF: "CHF ", HKD: "HK$",
};
let display = { currency: "INR", rate: 1 };

export function setDisplay(d: { currency: string; inr_per_unit: number } | undefined): void {
  display = d && d.inr_per_unit > 0 ? { currency: d.currency, rate: d.inr_per_unit } : { currency: "INR", rate: 1 };
}

export function displayCurrency(): string {
  return display.currency;
}

/** A rupee amount in the display currency, with its symbol. */
export function inr(v: number | null | undefined, digits = 0): string {
  if (v == null) return DASH;
  const x = v / display.rate;
  const d = display.currency === "INR" || Math.abs(x) >= 1000 ? digits : Math.max(digits, 2);
  return `${SYMBOLS[display.currency] ?? display.currency + " "}${num(x, d)}`;
}

/** A rupee amount in the display currency, without the symbol (table cells). */
export function money(v: number | null | undefined, digits = 0): string {
  return v == null ? DASH : num(v / display.rate, digits);
}

export function pct(v: number | null | undefined, digits = 2): string {
  return v == null ? DASH : `${num(v * 100, digits)}%`;
}

/** A signed rupee amount (P&L) in the display currency. */
export function signed(v: number | null | undefined, digits = 0): string {
  if (v == null) return DASH;
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${num(Math.abs(v) / display.rate, digits)}`;
}

export function tone(v: number | null | undefined): string {
  if (v == null || v === 0) return "text-ink";
  return v > 0 ? "text-up" : "text-down";
}

/** RELIANCE.NS -> RELIANCE */
export function ticker(symbol: string): string {
  if (symbol.startsWith("MF:")) return `MF ${symbol.slice(3)}`;
  if (symbol.startsWith("CMDTY:") || symbol.startsWith("BOND:")) return symbol.slice(symbol.indexOf(":") + 1);
  return symbol.replace(/\.(NS|BO)$/, "");
}

/** Short tag for each asset class, and the colour it reads in. */
export const ASSET_TAG: Record<string, { label: string; cls: string }> = {
  equity: { label: "EQ", cls: "text-dim" },
  etf: { label: "ETF", cls: "text-cyan" },
  mutual_fund: { label: "MF", cls: "text-cyan" },
  gold: { label: "GOLD", cls: "text-amber" },
  commodity: { label: "CMDTY", cls: "text-amber" },
  bond: { label: "BOND", cls: "text-up" },
};

export const ASSET_NAME: Record<string, string> = {
  equity: "Stocks", etf: "ETFs", mutual_fund: "Mutual funds", gold: "Gold",
  commodity: "Commodities", bond: "Bonds",
};

export function signedPct(v: number, digits = 2): string {
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${num(Math.abs(v) * 100, digits)}%`;
}

export function feedLabel(status: { source: string; state: string } | undefined): string {
  if (!status || status.state === "off") return "LAST CLOSE";
  if (status.state === "error") return "FEED ERROR";
  if (status.state === "connecting") return "CONNECTING";
  return FEED_LABELS[status.source] ?? "DELAYED";
}

const FEED_LABELS: Record<string, string> = {
  upstox: "UPSTOX LIVE",
  zerodha: "ZERODHA LIVE",
  groww: "GROWW LTP",
  bse: "BSE (BETA)",
  "yahoo-delayed": "DELAYED",
};

/** Real-time sources get the green dot; polled or delayed ones stay amber. */
export function isRealtime(status: { source: string; state: string } | undefined): boolean {
  return status?.state === "live" && (status.source === "upstox" || status.source === "zerodha");
}
