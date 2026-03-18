"""PokeWallet API client for card identification."""

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class PokeWalletCard:
    id: str
    name: str
    clean_name: str = ""
    set_name: str = ""
    set_code: str = ""
    card_number: str = ""
    rarity: str = ""
    card_type: str = ""
    hp: str = ""
    image_url: str = ""


@dataclass
class SearchResult:
    query: str
    cards: List[PokeWalletCard]
    total: int
    page: int


class PokeWalletClient:
    """Client for the PokeWallet Pokemon TCG API."""

    def __init__(self, api_key: str, base_url: str = "https://api.pokewallet.io",
                 timeout: float = 30.0):
        self.base_url = base_url
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"X-API-Key": api_key},
            timeout=timeout,
        )
        self._rate_remaining_hour = 100
        self._rate_remaining_day = 1000
        self._cache: Dict[str, Any] = {}
        self._cache_timestamps: Dict[str, float] = {}
        self._cache_ttl = 3600  # 1 hour

    async def search(self, query: str, page: int = 1, limit: int = 20) -> SearchResult:
        """Search for cards by name, number, or set code."""
        cache_key = f"search:{query}:{page}:{limit}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        self._check_rate_limit()
        response = await self._client.get("/search", params={"q": query, "page": page, "limit": limit})
        self._update_rate_limits(response.headers)
        response.raise_for_status()
        data = response.json()

        cards = []
        for item in data.get("results", []):
            card_info = item.get("card_info", {})
            cards.append(PokeWalletCard(
                id=item.get("id", ""),
                name=card_info.get("name", ""),
                clean_name=card_info.get("clean_name", ""),
                set_name=card_info.get("set_name", ""),
                set_code=card_info.get("set_code", ""),
                card_number=card_info.get("card_number", ""),
                rarity=card_info.get("rarity", ""),
                card_type=card_info.get("card_type", ""),
                hp=card_info.get("hp", ""),
            ))

        result = SearchResult(
            query=query,
            cards=cards,
            total=data.get("pagination", {}).get("total", len(cards)),
            page=page,
        )
        self._set_cached(cache_key, result)
        return result

    async def get_card(self, card_id: str) -> Optional[PokeWalletCard]:
        """Get detailed card information by ID."""
        cache_key = f"card:{card_id}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        self._check_rate_limit()
        response = await self._client.get(f"/cards/{card_id}")
        self._update_rate_limits(response.headers)

        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()

        card_info = data.get("card_info", {})
        card = PokeWalletCard(
            id=data.get("id", card_id),
            name=card_info.get("name", ""),
            clean_name=card_info.get("clean_name", ""),
            set_name=card_info.get("set_name", ""),
            set_code=card_info.get("set_code", ""),
            card_number=card_info.get("card_number", ""),
            rarity=card_info.get("rarity", ""),
            card_type=card_info.get("card_type", ""),
            hp=card_info.get("hp", ""),
        )
        self._set_cached(cache_key, card)
        return card

    async def get_sets(self) -> List[Dict]:
        """Get all available sets."""
        cache_key = "sets:all"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        self._check_rate_limit()
        response = await self._client.get("/sets")
        self._update_rate_limits(response.headers)
        response.raise_for_status()
        data = response.json()
        sets = data.get("data", [])
        self._set_cached(cache_key, sets)
        return sets

    async def get_image(self, card_id: str, size: str = "high") -> bytes:
        """Download card image."""
        self._check_rate_limit()
        response = await self._client.get(f"/images/{card_id}", params={"size": size})
        self._update_rate_limits(response.headers)
        response.raise_for_status()
        return response.content

    def _check_rate_limit(self):
        if self._rate_remaining_hour <= 5:
            raise RuntimeError(f"Approaching hourly rate limit ({self._rate_remaining_hour} remaining)")
        if self._rate_remaining_day <= 10:
            raise RuntimeError(f"Approaching daily rate limit ({self._rate_remaining_day} remaining)")

    def _update_rate_limits(self, headers):
        if "X-RateLimit-Remaining-Hour" in headers:
            self._rate_remaining_hour = int(headers["X-RateLimit-Remaining-Hour"])
        if "X-RateLimit-Remaining-Day" in headers:
            self._rate_remaining_day = int(headers["X-RateLimit-Remaining-Day"])

    def _get_cached(self, key: str):
        if key in self._cache:
            ts = self._cache_timestamps.get(key, 0)
            if time.time() - ts < self._cache_ttl:
                return self._cache[key]
            del self._cache[key]
            del self._cache_timestamps[key]
        return None

    def _set_cached(self, key: str, value):
        self._cache[key] = value
        self._cache_timestamps[key] = time.time()

    async def close(self):
        await self._client.aclose()
