"""Brokers and market-data sources behind one interface.

Every source here is read-only. A broker adapter may read holdings and the
day's trades and may stream prices; nothing in this package can send anything
to an exchange. The engine's tests enforce that by scanning the source."""
