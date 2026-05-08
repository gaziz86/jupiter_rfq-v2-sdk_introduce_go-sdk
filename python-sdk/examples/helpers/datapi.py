"""DatAPI client used by the production streaming example.

Mirrors ``rust-sdk/examples/helpers/datapi.rs``: a tiny HTTP wrapper over
``GET /v1/prices?ids=...`` that returns USD prices for the given tokens.
"""

from dataclasses import dataclass
from typing import Dict, Iterable, List

import requests


@dataclass
class TokenPriceData:
    """Single token's price snapshot returned by DatAPI.

    Mirrors the Rust ``TokenPriceData`` struct.
    """

    usd_price: float
    block_id: int
    decimals: int
    price_change24h: float


# Mirrors Rust's ``DatapiResponse = HashMap<String, TokenPriceData>``.
DatapiResponse = Dict[str, TokenPriceData]


class DatapiClient:
    """Tiny synchronous HTTP client for the Jupiter DatAPI."""

    def __init__(self, host: str):
        self._host = host.rstrip("/")
        self._session = requests.Session()

    def fetch_prices(self, token_ids: Iterable[str]) -> DatapiResponse:
        """Fetch prices for a list of token mints."""
        ids = ",".join(token_ids)
        url = f"{self._host}/v1/prices?ids={ids}"

        response = self._session.get(
            url, headers={"accept": "application/json"}
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"HTTP error {response.status_code}: {response.text}"
            )

        body = response.json()
        return {
            token: TokenPriceData(
                usd_price=float(data.get("usdPrice", 0.0)),
                block_id=int(data.get("blockId", 0)),
                decimals=int(data.get("decimals", 0)),
                price_change24h=float(data.get("priceChange24h", 0.0)),
            )
            for token, data in body.items()
        }

    def fetch_price(self, token_id: str) -> DatapiResponse:
        """Fetch the price for a single token."""
        return self.fetch_prices([token_id])


__all__ = ["DatapiClient", "DatapiResponse", "TokenPriceData"]
