"""Where API credentials live. They are kept in the operating system's
credential store (macOS Keychain, Windows Credential Manager) and never in the
database, logs or API responses. An environment variable overrides the store."""
from __future__ import annotations

import os
from typing import Callable, Protocol

SERVICE = "QuantTerminal"
UPSTOX = ("upstox-token", ("QT_UPSTOX_TOKEN", "QT_UPSTOX_ACCESS_TOKEN"))
GEMINI = ("gemini-api-key", ("QT_GEMINI_API_KEY", "GEMINI_API_KEY"))

# One keychain entry per credential field: {field: (account, environment overrides)}.
ZERODHA = {
    "api_key": ("zerodha-api-key", ("QT_ZERODHA_API_KEY",)),
    "api_secret": ("zerodha-api-secret", ("QT_ZERODHA_API_SECRET",)),
    "access_token": ("zerodha-access-token", ("QT_ZERODHA_ACCESS_TOKEN",)),
}
GROWW = {
    "api_key": ("groww-api-key", ("QT_GROWW_API_KEY",)),
    "api_secret": ("groww-api-secret", ("QT_GROWW_API_SECRET",)),
    "totp_secret": ("groww-totp-secret", ("QT_GROWW_TOTP_SECRET",)),
    "access_token": ("groww-access-token", ("QT_GROWW_ACCESS_TOKEN",)),
}


class TokenStore(Protocol):
    def get(self) -> str | None: ...
    def source(self) -> str | None: ...
    def set(self, token: str) -> None: ...
    def clear(self) -> None: ...


class KeyringStore:
    def __init__(self, account: str, env_names: tuple[str, ...] = ()):
        self.account = account
        self.env_names = env_names

    def _env(self) -> str | None:
        for name in self.env_names:
            value = os.environ.get(name, "").strip()
            if value:
                return value
        return None

    def _saved(self) -> str | None:
        try:
            import keyring

            return keyring.get_password(SERVICE, self.account) or None
        except Exception:
            return None

    def get(self) -> str | None:
        return self._env() or self._saved()

    def source(self) -> str | None:
        if self._env():
            return "environment"
        return "keychain" if self._saved() else None

    def set(self, token: str) -> None:
        import keyring

        try:
            keyring.set_password(SERVICE, self.account, token)
        except Exception as exc:
            raise RuntimeError(f"Could not save to the system credential store: {exc}") from exc

    def clear(self) -> None:
        import keyring

        try:
            keyring.delete_password(SERVICE, self.account)
        except Exception:
            pass  # nothing saved


class MemoryStore:
    """In-process store for tests and for running without a credential store."""

    def __init__(self, token: str | None = None):
        self._token = token

    def get(self) -> str | None:
        return self._token

    def source(self) -> str | None:
        return "memory" if self._token else None

    def set(self, token: str) -> None:
        self._token = token

    def clear(self) -> None:
        self._token = None


StoreFactory = Callable[[str, tuple[str, ...]], TokenStore]


def keychain_stores(account: str, env_names: tuple[str, ...] = ()) -> TokenStore:
    return KeyringStore(account, env_names)


def memory_stores(account: str, env_names: tuple[str, ...] = ()) -> TokenStore:
    return MemoryStore()


def credential_set(fields: dict[str, tuple[str, tuple[str, ...]]], factory: StoreFactory) -> dict[str, TokenStore]:
    return {name: factory(account, envs) for name, (account, envs) in fields.items()}
