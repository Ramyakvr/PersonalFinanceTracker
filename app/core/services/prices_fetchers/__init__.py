"""Source-specific price fetchers.

Implementations are injected via ``core.services.prices.refresh_prices``
so tests can stub them. Each fetcher accepts a list of ``Instrument``
rows and returns ``(instrument, price, currency, as_of)`` tuples.
"""
