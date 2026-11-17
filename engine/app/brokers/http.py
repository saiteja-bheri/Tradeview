"""Small JSON-over-HTTPS helper shared by the broker adapters. Tests replace
`call` and `get_bytes` so no adapter test touches the network."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from app.brokers.base import BrokerError


# The only request allowed to send data to a broker: Zerodha's exchange of a
# login's request_token for the day's access token. Everything else is GET.
ALLOWED_WRITES = frozenset({("POST", "https://api.kite.trade/session/token")})


def check_read_only(method: str, url: str) -> None:
    """Refuses any non-GET request outside ALLOWED_WRITES, before it is sent."""
    method = method.upper()
    if method == "GET":
        return
    parts = urllib.parse.urlsplit(url)
    if (method, f"{parts.scheme}://{parts.netloc}{parts.path}") not in ALLOWED_WRITES:
        raise BrokerError(f"Blocked a {method} request to {parts.netloc}{parts.path}: "
                          "this app only reads from brokers", status=403)


# Sent unless the caller sets its own: Cloudflare, in front of several broker
# APIs, refuses Python's default "Python-urllib" signature (error 1010).
USER_AGENT = "QuantTerminal/0.5 (read-only analytics)"


def _headers(headers: dict[str, str] | None) -> dict[str, str]:
    return {"User-Agent": USER_AGENT, **(headers or {})}


def _message(raw: bytes) -> str:
    try:
        body = json.loads(raw)
    except ValueError:
        return raw.decode("utf-8", "replace")[:200]
    if isinstance(body, dict):
        return str(body.get("message") or body.get("error") or body.get("detail") or body)[:200]
    return str(body)[:200]


def get_bytes(url: str, headers: dict[str, str] | None = None, timeout: float = 30) -> bytes:
    request = urllib.request.Request(url, headers=_headers(headers), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as res:
            return res.read()
    except urllib.error.HTTPError as exc:
        raise BrokerError(_message(exc.read()), status=exc.code) from exc
    except urllib.error.URLError as exc:
        host = urllib.parse.urlsplit(url).hostname
        raise BrokerError(f"Could not reach {host}: {exc.reason}", status=503) from exc


def call(method: str, url: str, headers: dict[str, str] | None = None,
         form: dict[str, str] | None = None, timeout: float = 20) -> dict:
    """GET, or POST of a urlencoded form (used only to open a login session)."""
    check_read_only(method, url)
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    request = urllib.request.Request(url, data=data, headers=_headers(headers), method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as res:
            raw = res.read()
    except urllib.error.HTTPError as exc:
        raise BrokerError(_message(exc.read()), status=exc.code) from exc
    except urllib.error.URLError as exc:
        host = urllib.parse.urlsplit(url).hostname
        raise BrokerError(f"Could not reach {host}: {exc.reason}", status=503) from exc
    return json.loads(raw) if raw else {}
