"""Groww through its official Trade API SDK, `growwapi` (read-only use).

Groww API access is a paid subscription. A session is opened from the API key
plus either the TOTP secret (preferred: no daily manual step) or the API
secret; an access token pasted directly also works. Tokens reset at about
06:00 every morning.

Reads: holdings, and last-traded prices for the live feed. Groww's trade
history comes from its report download (IMPORT CSV), because the SDK has no
call for past trades."""
from __future__ import annotations

from pathlib import Path

from app.brokers.base import BrokerError, Field, Holding, Source, UnavailableFeed
from app.market import symbols

INSTALL = "Groww support needs its SDK: run  engine\\.venv\\Scripts\\pip install growwapi pyotp"


def _sdk():
    try:
        from growwapi import GrowwAPI
    except ImportError as exc:
        raise BrokerError(INSTALL, status=501) from exc
    return GrowwAPI


class GrowwSource(Source):
    id = "groww"
    label = "Groww"
    fields = (
        Field("api_key", "API key", help="Groww > Trade API > generate a key."),
        Field("totp_secret", "TOTP secret", required=False,
              help="Optional. Lets the app open each day's session without asking you."),
        Field("api_secret", "API secret", required=False,
              help="Optional alternative to the TOTP secret."),
    )
    capabilities = frozenset({"csv", "holdings", "live"})
    login = "generate"
    notes = ("Import trades with IMPORT CSV (Groww's stock order report, CSV or Excel). "
             "SYNC checks the ledger against your Groww holdings.")
    live_note = "Last traded price, polled every few seconds. Day P&L isn't available from this source."

    def start_session(self, value: str | None) -> None:
        pasted = (value or "").strip()
        if pasted:
            if any(c.isspace() for c in pasted) or len(pasted) < 20:
                raise BrokerError("That does not look like a Groww access token", status=400)
            self._store_session(pasted)
            return
        key = self.value("api_key")
        if not key:
            raise BrokerError("Save your Groww API key first", status=400)
        GrowwAPI = _sdk()
        totp_secret, secret = self.value("totp_secret"), self.value("api_secret")
        try:
            if totp_secret:
                try:
                    import pyotp
                except ImportError as exc:
                    raise BrokerError(INSTALL, status=501) from exc
                token = GrowwAPI.get_access_token(api_key=key, totp=pyotp.TOTP(totp_secret).now())
            elif secret:
                token = GrowwAPI.get_access_token(api_key=key, secret=secret)
            else:
                raise BrokerError("Save a TOTP secret or API secret, or paste an access token", status=400)
        except BrokerError:
            raise
        except Exception as exc:
            raise BrokerError(f"Groww login failed: {exc}", status=401) from exc
        if not token:
            raise BrokerError("Groww did not return an access token", status=401)
        self._store_session(str(token))

    def client(self):
        token = self.session_token()
        if not token:
            raise BrokerError("No Groww session today. Click LOG IN under Groww first.", status=401)
        return _sdk()(token)

    def fetch_holdings(self) -> list[Holding]:
        try:
            reply = self.client().get_holdings_for_user(timeout=15)
        except BrokerError:
            raise
        except Exception as exc:
            raise BrokerError(f"Groww holdings request failed: {exc}") from exc
        out = []
        for h in (reply or {}).get("holdings", []):
            qty = float(h.get("quantity") or 0)
            if qty <= 0:
                continue
            out.append(Holding(symbol=symbols.to_yahoo(h.get("trading_symbol") or "", "NSE"),
                               isin=(h.get("isin") or "").upper(), name="", quantity=qty,
                               avg_price=float(h.get("average_price") or 0)))
        return out

    def make_feed(self, cache_dir: Path):
        if not self.session_token():
            return UnavailableFeed(self.id, "Log in to Groww under CONNECT to use its prices.")
        from app.market.feeds.groww_poll import GrowwPollFeed

        return GrowwPollFeed(self.client)
