export interface Settings {
  benchmark: string;
  benchmark_name: string;
  cov_horizon_days: number;
  confidence: number;
  horizon_days: number;
  lookback_days: number;
  risk_free_rate: number;
  display_currency: string;
  insight_frequency: "hourly" | "daily";
}

export interface Holding {
  symbol: string;
  quantity: number;
  avg_cost: number;
  last: number | null;
  value: number | null;
  weight: number | null;
  unrealized_pnl: number | null;
  realized_pnl: number;
  dividends: number;
  beta: number | null;
  component_var: number | null;
  name?: string;
  asset_class?: AssetClass;
  currency?: string;
  fx_rate?: number | null;
  total_return?: number | null;
  total_return_pct?: number | null;
  xirr?: number | null;
}

export type AssetClass = "equity" | "etf" | "mutual_fund" | "gold" | "commodity" | "bond";

export interface Returns {
  invested: number | null;
  total_return: number | null;
  total_return_pct: number | null;
  xirr: number | null;
}

export interface Allocation {
  asset_class: AssetClass;
  value: number | null;
  weight: number | null;
}

export interface Metrics {
  beta: number | null;
  jensens_alpha_annualized: number | null;
  sharpe: number | null;
  sortino: number | null;
  max_drawdown: number | null;
  volatility_annualized: number | null;
  var: number | null;
  var_pct: number | null;
  var_z: number | null;
}

export interface Portfolio {
  as_of: string | null;
  params: Settings;
  portfolio_value: number | null;
  net_delta: number | null;
  realized_pnl: number | null;
  unrealized_pnl: number | null;
  dividends: number | null;
  metrics: Metrics | null;
  covariance: Covariance | null;
  observations: number;
  holdings: Holding[];
  warnings: string[];
  returns?: Returns;
  allocation?: Allocation[];
  pending_reviews?: number;
  portfolio_cash?: number | null;
  display?: { choice: string; currency: string; inr_per_unit: number; note?: string };
}

export interface Covariance {
  symbols: string[];
  horizon_days: number;
  observations: number;
  matrix: (number | null)[][];
  annualized: (number | null)[][];
  correlation: (number | null)[][];
}

export interface BenchmarkOption {
  symbol: string;
  name: string;
  kind: "INDEX" | "ETF" | "FUND" | "STOCK";
  exchange: string;
  preset: boolean;
}

/** A trade made elsewhere, as typed into the ledger. Never sent to a broker. */
export interface TradeInput {
  symbol: string;
  side: "BUY" | "SELL";
  quantity: number;
  price: number;
  traded_at: string;
  name?: string;
  /** "INTL" for a listing picked from international search results (price in its own currency). */
  market?: "IN" | "INTL";
}

export interface Trade {
  id: number;
  symbol: string;
  name: string;
  side: "BUY" | "SELL";
  quantity: number;
  price: number;
  traded_at: string;
  broker: string;
}

export interface CorporateAction {
  id: number;
  symbol: string;
  ex_date: string;
  kind: "split" | "bonus" | "dividend";
  value: number;
  source: string;
  review?: "" | "pending" | "apply" | "skip";
}

export interface ImportResult {
  broker?: string;
  imported: number;
  duplicates: number;
  updated: number;
  skipped: string[];
}

export interface Quote {
  ltp: number;
  prev_close: number | null;
  change: number | null;
  change_pct: number | null;
  ts: number;
}

export interface FeedStatus {
  source: "upstox" | "zerodha" | "groww" | "bse" | "yahoo-delayed" | "none" | string;
  state: "connecting" | "live" | "error" | "off";
  detail: string;
}

export interface LiveSnapshot {
  type: "snapshot";
  status: FeedStatus;
  quotes: Record<string, Quote>;
  portfolio: {
    held: number;
    priced: number;
    value: number;
    unrealized_pnl: number;
    day_pnl: number | null;
    holdings: Record<string, { value: number; unrealized_pnl: number; day_pnl: number | null }>;
  } | null;
}

export interface InsightState {
  configured: boolean;
  source: "environment" | "keychain" | "memory" | null;
  model: string;
  frequency?: "hourly" | "daily";
  last_at?: string | null;
  next_at?: string | null;
}

export interface Memo {
  id: number;
  created_at: string;
  model: string;
  text: string;
  payload: Record<string, unknown>;
  unverified_numbers: string[];
  cached?: boolean;
  next_at?: string | null;
}

export interface SearchResult {
  symbol: string;
  name: string;
  exchange: string;
  held: boolean;
  asset_class?: AssetClass;
  market?: string;
  currency?: string;
}

export interface SearchResponse {
  query: string;
  results: SearchResult[];
  online: boolean;
}

export type SourceId = "upstox" | "zerodha" | "groww" | "bse" | "yahoo";
export type PriceSource = "auto" | SourceId | "off";

export interface CredentialField {
  name: string;
  label: string;
  secret: boolean;
  required: boolean;
  help: string;
  set: boolean;
  source: "environment" | "keychain" | "memory" | null;
}

export interface Mismatch {
  broker: string;
  symbol: string;
  isin: string;
  broker_quantity: number;
  ledger_quantity: number;
}

export interface SourceState {
  id: SourceId;
  label: string;
  kind: "broker" | "data";
  capabilities: ("csv" | "holdings" | "trades" | "live" | "history")[];
  login: "none" | "redirect" | "generate";
  experimental: boolean;
  notes: string;
  live_note: string;
  configured: boolean;
  session: { needed: boolean; active: boolean; issued?: string | null };
  fields: CredentialField[];
  last_sync: string | null;
  holdings_synced: number;
  mismatches: Mismatch[];
}

export interface ConnectionsState {
  price_source: PriceSource;
  price_sources: PriceSource[];
  env_override: string | null;
  feed: FeedStatus;
  sources: SourceState[];
}

export interface SyncResult {
  imported: number;
  duplicates: number;
  holdings: number;
  mismatches: Mismatch[];
  synced_at: string;
}

export interface Bond {
  symbol: string;
  name: string;
  isin: string;
  face_value: number;
  coupon_rate: number;
  frequency: 0 | 1 | 2 | 4 | 12;
  maturity: string;
  price: number;
  coupon_per_bond: number;
}

export type BondInput = Omit<Bond, "symbol" | "coupon_per_bond">;

export interface BseSyncResult {
  added: { symbol: string; ex_date: string; kind: string; value: number; purpose: string }[];
  already_recorded: number;
  failed: string[];
  checked: number;
}

export interface ActionReview {
  id: number;
  symbol: string;
  kind: "split" | "bonus";
  value: number;
  ex_date: string;
  source: string;
  trades_before: number;
  uploaded_on: string | null;
  quantity_if_applied: number;
  quantity_if_skipped: number;
  broker_quantity: number | null;
  suggestion: { answer: "apply" | "skip" | null; reason: string };
}

export interface WatchItem {
  symbol: string;
  starred: boolean;
  watched: boolean;
  exchange: string;
  name: string;
  asset_class: AssetClass;
  currency: string;
  last: number | null;
  as_of: string | null;
  change_pct: number | null;
  cached_bars: number;
  held: boolean;
  viewed_at: string | null;
}

export interface CacheStatus {
  database: string;
  symbols: { symbol: string; bars: number; first: string; last: string; refreshed: string | null; starred: boolean; traded: boolean }[];
  bars: number;
  served_from_cache: number;
  incremental_updates: number;
  full_downloads: number;
}

export interface OptPortfolio {
  return: number;
  volatility: number;
  sharpe: number | null;
  weights: Record<string, number>;
}

export interface OptimizerResult {
  scope: "portfolio" | "starred" | "both" | "custom";
  symbols: string[];
  observations: number;
  from: string;
  to: string;
  risk_free_rate: number;
  max_weight: number;
  shrinkage: number;
  portfolios: { max_sharpe: OptPortfolio | null; min_variance: OptPortfolio | null; equal_weight: OptPortfolio | null; current?: OptPortfolio | null };
  frontier: { return: number; volatility: number }[];
  assets: { symbol: string; name: string; held: boolean; return: number; volatility: number; sharpe: number | null }[];
  warnings: string[];
}

export interface ImportField { field: string; label: string; required: boolean; format: string }

export interface ImportPreview {
  broker: "upstox" | "zerodha" | "groww" | "generic";
  header_row: number;
  headings: string[];
  mapping: Record<string, string | null>;
  missing: string[];
  samples: string[][];
  fields: ImportField[];
}

export interface EverythingSheet {
  sheet: string;
  kind: "trades" | "bonds" | "wealth" | "mixed" | "skip";
  routes?: Record<string, number>;
  broker?: string | null;
  rows: number;
  reason?: string;
  header_row?: number;
  headings?: string[];
  mapping?: Record<string, string | null>;
  missing?: string[];
  default_exchange?: string;
  samples: string[][];
}

export interface EverythingPreview {
  sheets: EverythingSheet[];
  workbook: boolean;
  broker: string | null;
}

export interface EverythingResult {
  sheets: { sheet: string; kind: string; added: number; updated: number; duplicates: number; skipped: string[] }[];
  totals: { trades: number; trade_duplicates: number; bonds: number; wealth: number };
  skipped: string[];
}

export interface ImportFormats {
  generic: { headings: { heading: string; required: boolean; format: string }[]; notes: string[] };
  brokers: Record<string, { label: string; file: string; required: string[]; optional: string[]; where: string }>;
  everything?: {
    types: { type: string; goes_to: string; uses: string; also: string[] }[];
    columns: { heading: string; required: boolean; format: string }[];
    notes: string[];
  };
  broker_labels?: Record<string, string>;
}

export interface ShockRow { shock: number; pnl: number; pnl_pct: number; low: number; high: number; beta: number }

export interface StressResult {
  as_of: string;
  observations: number;
  benchmark: string;
  benchmark_name: string;
  portfolio_value: number;
  horizon_days: number;
  portfolio_beta: number;
  shocks: ShockRow[];
  custom: ShockRow & { holdings: { symbol: string; name: string; value: number; beta: number; move: number; pnl: number }[] };
  crises: { id: string; label: string; kind: "crash" | "rally"; start: string; end: string; available: boolean; market_move?: number;
            pnl?: number; pnl_pct?: number; actual_share?: number;
            by_holding?: { symbol: string; move: number; pnl: number; method: "actual" | "beta" }[] }[];
  monte_carlo: {
    simulations: number; horizon_days: number;
    percentiles: Record<"p1" | "p5" | "p25" | "p50" | "p75" | "p95" | "p99", number>;
    expected_shortfall_95: number; expected_shortfall_99: number; expected_gain_95: number;
    prob_loss: Record<string, number>;
    prob_gain: Record<string, number>;
    histogram: { edges: number[]; counts: number[] };
  };
  correlation: { confidence: number; horizon_days: number; var_normal: number; var_stressed: number;
                 avg_correlation: number; avg_correlation_stressed: number };
  unpriced: string[];
  warnings: string[];
}

export interface NewsItem {
  id: string;
  symbols: string[];
  title: string;
  summary: string;
  publisher: string;
  url: string;
  published_at: string;
  source: string;
  sources: string[];
}

export interface NewsSource {
  id: string;
  label: string;
  region: string;
  kind: "symbol" | "feed";
  enabled: boolean;
  shown?: boolean;
  count?: number;
}

export interface MarketEvent {
  date: string;
  symbol: string;
  kind: "earnings" | "ex_dividend" | "dividend" | "split" | "bonus" | "coupon" | "maturity" | "check" | string;
  text: string;
  source: string;
}

export interface NewsFeed {
  items: NewsItem[];
  events: MarketEvent[];
  covered: { symbol: string; why: "held" | "watched" | "starred" | "market" | "selected"; name: string }[];
  sources: NewsSource[];
  updated_at: string | null;
  downloaded_news?: number;
  new_headlines?: number;
  errors: string[];
}

export type WealthKind = "cash" | "fixed_deposit" | "recurring_deposit" | "ppf" | "epf" | "nps" | "pension"
  | "life_insurance" | "term_insurance";

export interface WealthInput {
  kind: WealthKind;
  name: string;
  institution: string;
  amount: number;
  rate: number;
  start_date: string | null;
  maturity_date: string | null;
  monthly_contribution: number;
  cover: number;
  premium: number;
  notes: string;
}

export interface WealthItemRow extends WealthInput {
  id: number;
  kind_label: string;
  group: string;
  liquidity: "liquid" | "deposit" | "locked" | "protection";
  effective_rate: number;
  value: number;
  matures_in_days: number | null;
}

export interface WealthOverview {
  net_worth: number;
  market_value: number;
  portfolio_cash: number;
  other_assets: number;
  groups: { group: string; value: number; weight: number | null }[];
  liquidity: { cash: number; market: number; deposits: number; locked: number };
  protection: { life_cover: number; annual_premium: number; policies: number };
  monthly_contributions: number;
  maturing_within_90_days: WealthItemRow[];
  items: WealthItemRow[];
  kinds: { kind: WealthKind; label: string; group: string; liquidity: string; rate: number }[];
}

export interface ProjectionPoint {
  month: number; date: string; invested: number; expected: number;
  p10: number; p50: number; p90: number; other: number; other_invested: number;
  total_p10: number; total_p50: number; total_p90: number;
  cost: number; p10_after_tax: number; p50_after_tax: number; p90_after_tax: number; total_p50_after_tax: number;
}

export interface ProjectionResult {
  assumptions: {
    source: "past" | "cautious" | "neutral" | "optimistic"; expected_return: number; volatility: number;
    volatility_source?: string; weights: Record<string, number>;
    per_class: Record<string, { expected_return: number; volatility: number }> | null;
    monthly_sip: number; step_up_pct: number; years: number; interval: string; start_value: number; simulations: number;
    start_cost: number; tax_gains_pct: number; gains_exemption: number; tax_interest_pct: number; renew_deposits: boolean;
  };
  points: ProjectionPoint[];
  summary: {
    invested_total: number; added_by_sip: number; median: number; bad_case: number; good_case: number; expected: number;
    median_annual_return: number | null; chance_below_invested: number; other_assets: number; total_median: number;
    median_after_tax: number; bad_case_after_tax: number; good_case_after_tax: number; tax_on_median: number;
    median_annual_return_after_tax: number | null; total_median_after_tax: number;
  };
  warnings: string[];
}

export interface Timeline {
  dates: string[];
  series: {
    market: (number | null)[]; invested: (number | null)[]; cash: (number | null)[];
    gain: (number | null)[]; other_wealth: (number | null)[]; net_worth: (number | null)[];
    benchmark: (number | null)[] | null;
  };
  by_class: Record<string, (number | null)[]>;
  wealth_groups: Record<string, (number | null)[]>;
  benchmark: string;
  benchmark_name: string;
  warnings: string[];
}

export interface CashMovement {
  date: string;
  kind: "dividend" | "sale" | "purchase" | "withdrawal";
  symbol: string;
  amount: number;
  from_cash: number;
  new_money: number;
  cash: number;
  money_in: number;
  note?: string;
  id?: number;
}

export interface PortfolioCash {
  balance: number;
  dividends: number;
  sale_proceeds: number;
  spent_from_cash: number;
  new_money: number;
  withdrawn: number;
  money_in: number;
  movements: CashMovement[];
  withdrawals: { id: number; date: string; amount: number; note: string }[];
}
