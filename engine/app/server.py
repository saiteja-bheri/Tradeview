"""Entry point: `python -m app.server`. Also the target for PyInstaller later."""
from __future__ import annotations

import uvicorn

from app import config
from app.brokers.registry import FeedContext, choose_feed
from app.main import create_app
from app.secrets import GEMINI, UPSTOX, KeyringStore, keychain_stores


def make_feed(ctx: FeedContext):
    """QT_FEED = auto (default) | upstox | zerodha | groww | bse | yahoo | off
    overrides the price source chosen under CONNECT. With `auto`, Upstox is
    used when its token is saved, otherwise delayed Yahoo quotes."""
    return choose_feed(ctx, config.feed_choice())


app = create_app(
    token_store=KeyringStore(*UPSTOX),
    feed_factory=make_feed,
    gemini_store=KeyringStore(*GEMINI),
    store_factory=keychain_stores,
)


def main() -> None:
    # Under the desktop shell the session token travels in the WebSocket URL,
    # and uvicorn logs that URL at INFO level, so only warnings are logged there.
    quiet = config.token() is not None
    uvicorn.run(app, host=config.host(), port=config.port(),
                log_level="warning" if quiet else "info", access_log=not quiet)

if __name__ == "__main__":
    main()
