"""Broker adapter registry.

Each adapter is a stateless singleton keyed by ``BrokerAccount.broker_key``.
New brokers are added by creating a module that exposes a class matching the
``BrokerAdapter`` Protocol, then registering it here.
"""

from __future__ import annotations

from core.services.imports.brokers.aionion import AionionAdapter
from core.services.imports.brokers.base import (
    BrokerAdapter,
    BrokerFormatError,
    NormalizedCA,
    NormalizedDividend,
    NormalizedTrade,
)
from core.services.imports.brokers.chola import CholaAdapter
from core.services.imports.brokers.zerodha import ZerodhaAdapter

REGISTRY: dict[str, BrokerAdapter] = {
    ZerodhaAdapter.key: ZerodhaAdapter(),
    CholaAdapter.key: CholaAdapter(),
    AionionAdapter.key: AionionAdapter(),
}

# Master list of the user's known broker client IDs. Used by:
#   * the seed_broker_accounts management command -- pre-creates BrokerAccount
#     rows so dashboards list them before the first import.
#   * the import view -- to warn when an uploaded file's client id does not
#     match the broker we expected (typo, mis-categorised file, etc.).
# Add new (broker_key, client_id) pairs here when a new account is opened.
KNOWN_CLIENT_IDS: tuple[tuple[str, str], ...] = ()


def known_client_ids_for(broker_key: str) -> tuple[str, ...]:
    """Return the tuple of expected client IDs for ``broker_key``."""
    return tuple(cid for k, cid in KNOWN_CLIENT_IDS if k == broker_key)


def get_adapter(broker_key: str) -> BrokerAdapter:
    try:
        return REGISTRY[broker_key]
    except KeyError as exc:
        raise KeyError(
            f"Unknown broker_key: {broker_key!r}. Known: {sorted(REGISTRY)}"
        ) from exc


__all__ = [
    "KNOWN_CLIENT_IDS",
    "REGISTRY",
    "BrokerAdapter",
    "BrokerFormatError",
    "NormalizedCA",
    "NormalizedDividend",
    "NormalizedTrade",
    "get_adapter",
    "known_client_ids_for",
]
