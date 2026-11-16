/** Yahoo symbol -> TradingView symbol, so each chart opens on the stock's own exchange.
 *
 *  Indian listings use BSE because TradingView's free embed carries BSE but not NSE data.
 *  US tickers use the exchange the search reported (NASDAQ, NYSE...) when known, otherwise
 *  the bare ticker, which TradingView resolves to the primary US listing. */

// Yahoo suffix -> TradingView exchange prefix
const SUFFIX: Record<string, string> = {
  L: "LSE", IL: "LSIN", DE: "XETR", F: "FWB", HM: "HAM", DU: "DUS", SG: "SWB", MU: "MUN", BE: "BER",
  PA: "EURONEXT", AS: "EURONEXT", BR: "EURONEXT", LS: "EURONEXT", IR: "EURONEXT",
  MI: "MIL", MC: "BME", SW: "SIX", VI: "VIE", ST: "OMXSTO", OL: "OSL", CO: "OMXCOP", HE: "OMXHEX",
  T: "TSE", HK: "HKEX", SI: "SGX", KS: "KRX", KQ: "KRX", SS: "SSE", SZ: "SZSE", TW: "TWSE",
  TO: "TSX", V: "TSXV", SA: "BMFBOVESPA", MX: "BMV", AX: "ASX", NZ: "NZX", JO: "JSE", TA: "TASE",
};

// Exchange label from the search -> TradingView prefix, for US tickers without a suffix
const US_EXCHANGE: Record<string, string> = {
  NASDAQ: "NASDAQ", NYSE: "NYSE", "NYSE AM": "AMEX", "NYSE ARCA": "AMEX", CBOE: "CBOE", OTC: "OTC",
};

const INDEX: Record<string, string> = {
  "^NSEI": "NSE:NIFTY", "^BSESN": "BSE:SENSEX", "^NSEBANK": "NSE:BANKNIFTY", "^GSPC": "SP:SPX",
  "^IXIC": "NASDAQ:IXIC", "^DJI": "DJ:DJI", "^FTSE": "FTSE:UKX", "^N225": "TVC:NI225",
  "^HSI": "TVC:HSI", "^GDAXI": "XETR:DAX",
};

const COMMODITY: Record<string, string> = {
  GOLD: "TVC:GOLD", SILVER: "TVC:SILVER", PLATINUM: "TVC:PLATINUM", CRUDE: "TVC:USOIL",
  BRENT: "TVC:UKOIL", NATGAS: "NYMEX:NG1!", COPPER: "COMEX:HG1!",
};

/** Exchanges TradingView's free embed has data for. Checked one by one: BSE, NASDAQ,
 *  NYSE, XETRA, Euronext, TSX and TVC load; NSE, LSE, Tokyo, Hong Kong and NYMEX futures
 *  load empty. Anything not listed is drawn from the local price cache instead. */
const EMBED_OK = new Set(["BSE", "NASDAQ", "NYSE", "AMEX", "CBOE", "XETR", "EURONEXT", "TSX", "TVC", "SP", "DJ"]);

export function embedHasData(tvSymbol: string): boolean {
  const i = tvSymbol.indexOf(":");
  return i < 0 || EMBED_OK.has(tvSymbol.slice(0, i));   // bare US tickers resolve on TradingView
}

export function tradingViewSymbol(symbol: string, exchange?: string): string {
  const s = symbol.toUpperCase();
  if (s.startsWith("CMDTY:")) return COMMODITY[s.slice(6)] ?? "TVC:GOLD";
  if (INDEX[s]) return INDEX[s];
  if (s.startsWith("^")) return s.slice(1);
  const dot = s.lastIndexOf(".");
  const base = dot > 0 ? s.slice(0, dot) : s;
  const suffix = dot > 0 ? s.slice(dot + 1) : "";
  if (suffix === "NS" || suffix === "BO") return `BSE:${base}`;
  if (suffix && SUFFIX[suffix]) {
    // Hong Kong codes are zero-padded on Yahoo (0700.HK) but not on TradingView (HKEX:700).
    const code = suffix === "HK" ? base.replace(/^0+(?=\d)/, "") : base;
    return `${SUFFIX[suffix]}:${code}`;
  }
  // US share classes: Yahoo writes BRK-B, TradingView BRK.B.
  const us = base.replace(/-(?=[A-Z]$)/, ".");
  const prefix = exchange ? US_EXCHANGE[exchange.toUpperCase()] : undefined;
  return prefix ? `${prefix}:${us}` : us;
}
