"""Small JSON-over-HTTPS helper shared by the broker adapters. Tests replace
`call` and `get_bytes` so no adapter test touches the network."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from app.brokers.base import BrokerError


def _message(raw: bytes) -> str:
    try:
        body = json.loads(raw)
    except ValueError:
        return raw.decode("utf-8", "replace")[:200]
    if isinstance(body, dict):
        return str(body.get("message") or body.get("error") or body.get("detail") or body)[:200]
    return str(body)[:200]


def get_bytes(url: str, headers: dict[str, str] | None = None, timeout: float = 30) -> bytes:
    request = urllib.request.Request(url, headers=headers or {}, method="GET")
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
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as res:
            raw = res.read()
    except urllib.error.HTTPError as exc:
        raise BrokerError(_message(exc.read()), status=exc.code) from exc
    except urllib.error.URLError as exc:
        host = urllib.parse.urlsplit(url).hostname
        raise BrokerError(f"Could not reach {host}: {exc.reason}", status=503) from exc
    return json.loads(raw) if raw else {}
