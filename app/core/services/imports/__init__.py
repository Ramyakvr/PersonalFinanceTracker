"""Import service package.

Contains:

* ``generic``  — the Phase-6 generic CSV importer (Assets + Transactions).
* ``brokers/`` — per-broker adapters for tradebooks and dividend statements.
* ``tradebook`` — service entry points that ingest broker-native files into
  StockTrade / DividendRecord rows via the broker adapters.

Re-exports the Phase-6 public API so existing imports like
``from core.services import imports as imp`` keep working.
"""

from core.services.imports.generic import (
    ASSET_OPTIONAL,
    ASSET_REQUIRED,
    BOOL_TRUE,
    MODE_APPEND,
    MODE_UPDATE,
    TX_OPTIONAL,
    TX_REQUIRED,
    VALID_MODES,
    ImportResult,
    import_assets,
    import_transactions,
    list_import_jobs,
)
from core.services.imports.tradebook import (
    import_dividends,
    import_statement,
    import_tradebook,
)

__all__ = [
    "ASSET_OPTIONAL",
    "ASSET_REQUIRED",
    "BOOL_TRUE",
    "MODE_APPEND",
    "MODE_UPDATE",
    "TX_OPTIONAL",
    "TX_REQUIRED",
    "VALID_MODES",
    "ImportResult",
    "import_assets",
    "import_dividends",
    "import_statement",
    "import_tradebook",
    "import_transactions",
    "list_import_jobs",
]
