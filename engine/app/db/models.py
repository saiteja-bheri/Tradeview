from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, String, UniqueConstraint, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class Instrument(Base):
    __tablename__ = "instruments"
    symbol: Mapped[str] = mapped_column(String, primary_key=True)  # Yahoo symbol, e.g. RELIANCE.NS
    name: Mapped[str] = mapped_column(String, default="")
    exchange: Mapped[str] = mapped_column(String, default="")
    scrip_code: Mapped[str] = mapped_column(String, default="")
    isin: Mapped[str] = mapped_column(String, default="", index=True)  # ties NSE and BSE listings together
    # equity | etf | mutual_fund | gold | commodity | bond; "" = work it out from the symbol
    asset_class: Mapped[str] = mapped_column(String, default="")
    # Trading currency as Yahoo reports it (INR, USD, GBp, JPY...). "" = INR for NSE/BSE.
    currency: Mapped[str] = mapped_column(String, default="")


class Bond(Base):
    """Terms of a bond tracked by hand (symbol BOND:<ID>). Coupons become
    dividend income on their payment dates; the bond is valued at `price`."""

    __tablename__ = "bonds"
    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, default="")
    isin: Mapped[str] = mapped_column(String, default="")
    face_value: Mapped[float] = mapped_column(Float, default=1000.0)
    coupon_rate: Mapped[float] = mapped_column(Float, default=0.0)     # annual, percent of face
    frequency: Mapped[int] = mapped_column(default=2)                  # coupons per year; 0 = zero-coupon
    maturity: Mapped[date] = mapped_column(Date)
    price: Mapped[float] = mapped_column(Float, default=0.0)           # valuation price per bond; 0 = face value


class Trade(Base):
    __tablename__ = "trades"
    __table_args__ = (UniqueConstraint("broker", "trade_id", name="uq_trade"),)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    broker: Mapped[str] = mapped_column(String)
    trade_id: Mapped[str] = mapped_column(String)
    symbol: Mapped[str] = mapped_column(String, index=True)
    side: Mapped[str] = mapped_column(String)  # BUY | SELL
    quantity: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    traded_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    # When the row entered the ledger (file upload, sync or manual entry). A split
    # or bonus between traded_at and this moment may already be reflected in the
    # quantity the broker reported, so the user is asked once.
    imported_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)


class CorporateAction(Base):
    """kind = split | bonus (value is the share multiplier, e.g. 2.0 for a
    2-for-1 split or a 1:1 bonus) or dividend (value is cash per share)."""

    __tablename__ = "corporate_actions"
    __table_args__ = (UniqueConstraint("symbol", "ex_date", "kind", name="uq_action"),)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    ex_date: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String)
    value: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String, default="manual")
    # Splits and bonuses only: "" applies it (nothing to ask), "pending" applies it
    # but waits for the user to confirm, "apply" confirmed, "skip" = the uploaded
    # quantities already include it, so it must not be applied again.
    review: Mapped[str] = mapped_column(String, default="")


class PriceBar(Base):
    __tablename__ = "price_history"
    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    close: Mapped[float] = mapped_column(Float)
    adj_close: Mapped[float] = mapped_column(Float)


class Memo(Base):
    """An AI-written memo plus the exact figures that were sent to produce it."""

    __tablename__ = "memos"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    model: Mapped[str] = mapped_column(String)
    payload: Mapped[str] = mapped_column(String)      # JSON sent to the model
    text: Mapped[str] = mapped_column(String)
    unverified: Mapped[str] = mapped_column(String, default="[]")  # JSON list of flagged numbers


class Watch(Base):
    """One row per stock the user has marked or looked at:
      * watched: on the watchlist (eye icon); prices are cached locally
      * starred: picked for the optimizer (star icon); prices are cached locally
      * viewed_at: last opened from the search (the History tab); nothing is downloaded for it"""

    __tablename__ = "watchlist"
    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    starred: Mapped[bool] = mapped_column(default=False)
    watched: Mapped[bool] = mapped_column(default=False)
    added_at: Mapped[datetime] = mapped_column(DateTime)
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)


class WealthItem(Base):
    """Something you own outside the market portfolio: cash, fixed and recurring
    deposits, pension savings (EPF, PPF, NPS, other) and insurance policies.

    `amount` is the current balance (cash, PPF, EPF, NPS, pension, policy fund or
    surrender value) or, for a fixed deposit, the principal, whose value then
    accrues at `rate` from `start_date`. `cover` is a policy's sum assured, which
    protects but is not net worth. Values are in INR."""

    __tablename__ = "wealth_items"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String, default="")
    institution: Mapped[str] = mapped_column(String, default="")
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    rate: Mapped[float] = mapped_column(Float, default=0.0)            # annual %, for growth and projections
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    maturity_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    monthly_contribution: Mapped[float] = mapped_column(Float, default=0.0)
    cover: Mapped[float] = mapped_column(Float, default=0.0)           # insurance sum assured
    premium: Mapped[float] = mapped_column(Float, default=0.0)         # insurance premium per year
    notes: Mapped[str] = mapped_column(String, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class CashWithdrawal(Base):
    """Money taken out of the dividend cash balance. Dividends and bond coupons
    are held as cash in the portfolio until a withdrawal is recorded here."""

    __tablename__ = "cash_withdrawals"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[float] = mapped_column(Float)                       # INR
    note: Mapped[str] = mapped_column(String, default="")


class NewsItem(Base):
    """A headline for one symbol, kept so the NEWS tab can be reopened without
    downloading again (refreshed at most every 30 minutes). `source` is the feed
    it came from (app.market.news_sources.SOURCES: yahoo, google, et, ...)."""

    __tablename__ = "news"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String)
    summary: Mapped[str] = mapped_column(String, default="")
    publisher: Mapped[str] = mapped_column(String, default="")
    url: Mapped[str] = mapped_column(String, default="")
    published_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    source: Mapped[str] = mapped_column(String, default="yahoo")


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String)


class BrokerHolding(Base):
    """What a broker last said the account holds. Used only to check the ledger
    against the broker; the ledger itself stays the source of truth."""

    __tablename__ = "broker_holdings"
    broker: Mapped[str] = mapped_column(String, primary_key=True)
    symbol: Mapped[str] = mapped_column(String, primary_key=True)  # Yahoo symbol
    isin: Mapped[str] = mapped_column(String, default="")
    name: Mapped[str] = mapped_column(String, default="")
    quantity: Mapped[float] = mapped_column(Float)
    avg_price: Mapped[float] = mapped_column(Float, default=0.0)
    synced_at: Mapped[datetime] = mapped_column(DateTime)


# Columns added after the first release. create_all() never alters an existing
# table, so a ledger made by an older version gets them here.
_ADDED_COLUMNS = {
    "instruments": {"isin": "VARCHAR NOT NULL DEFAULT ''", "asset_class": "VARCHAR NOT NULL DEFAULT ''",
                    "currency": "VARCHAR NOT NULL DEFAULT ''"},
    "trades": {"imported_at": "DATETIME"},
    "corporate_actions": {"review": "VARCHAR NOT NULL DEFAULT ''"},
    "watchlist": {"watched": "BOOLEAN NOT NULL DEFAULT 0"},
    "news": {"source": "VARCHAR NOT NULL DEFAULT 'yahoo'"},
}
# Run once, right after a column is added. Before the eye icon existed, starring
# a stock also put it on the watchlist, so those stay watched.
_AFTER_ADD = {("watchlist", "watched"): "UPDATE watchlist SET watched = starred"}


def _migrate(engine) -> None:
    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            have = {c["name"] for c in inspect(conn).get_columns(table)}
            for name, ddl in columns.items():
                if name not in have:
                    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}'))
                    if (table, name) in _AFTER_ADD:
                        conn.execute(text(_AFTER_ADD[(table, name)]))


def make_sessionmaker(url: str) -> sessionmaker:
    engine = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    _migrate(engine)
    return sessionmaker(engine, expire_on_commit=False)
