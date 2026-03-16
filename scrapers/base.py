"""
Base scraper class for Australian PC retailers.

Each retailer adapter inherits from BaseScraper and implements:
  - search(query) -> list[ProductListing]

The base class provides HTTP helpers, retry logic, rate limiting,
caching, and structured logging.
"""

from __future__ import annotations

import re
import time
import logging
import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from urllib.parse import urlparse, quote_plus

import requests
from bs4 import BeautifulSoup

from scrapers import cache as _cache

# ─── Shared HTTP session ────────────────────────────────────────────────────

_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-AU,en;q=0.9",
})

# Per-domain rate limiting
_last_hit: dict[str, float] = {}
_RATE_LIMIT = 3.0  # seconds between requests to the same domain


# ─── Data structures ────────────────────────────────────────────────────────

@dataclass
class ProductListing:
    """Normalised product result from any retailer."""
    title: str
    price: float
    url: str
    store: str
    in_stock: bool = True
    stock_status: str = "unknown"
    shipping: float | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self):
        if self.stock_status == "in_stock":
            self.in_stock = True
        elif self.stock_status == "out_of_stock":
            self.in_stock = False
        elif not self.in_stock:
            self.stock_status = "out_of_stock"

    def to_dict(self) -> dict:
        return asdict(self)


# ─── Base class ─────────────────────────────────────────────────────────────

class BaseScraper:
    """
    Override in each retailer adapter:
        STORE_NAME  — human-readable store name
        BASE_URL    — retailer root URL
        search()    — takes a query string, returns list[ProductListing]
    """

    STORE_NAME: str = "Unknown"
    BASE_URL: str = ""
    TIMEOUT: int = 15
    MAX_RETRIES: int = 2
    CACHE_TTL: int = 1800  # 30 minutes

    def __init__(self):
        self.log = logging.getLogger(f"scrapers.{self.STORE_NAME.lower().replace(' ', '_')}")

    # ── HTTP helpers ────────────────────────────────────────────────────────

    def _rate_limit(self, url: str):
        domain = urlparse(url).netloc
        now = time.time()
        wait = _RATE_LIMIT - (now - _last_hit.get(domain, 0))
        if wait > 0:
            time.sleep(wait)
        _last_hit[domain] = time.time()

    def _get(self, url: str, **kwargs) -> requests.Response | None:
        """HTTP GET with rate limiting, retries, and timeout."""
        self._rate_limit(url)
        last_err = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                resp = _SESSION.get(url, timeout=self.TIMEOUT, **kwargs)
                resp.raise_for_status()
                return resp
            except requests.Timeout as e:
                last_err = e
                self.log.warning("[%s] Timeout (attempt %d/%d): %s",
                                 self.STORE_NAME, attempt, self.MAX_RETRIES, url)
            except requests.HTTPError as e:
                last_err = e
                status = getattr(e.response, "status_code", "?")
                self.log.warning("[%s] HTTP %s (attempt %d/%d): %s",
                                 self.STORE_NAME, status, attempt, self.MAX_RETRIES, url)
                if status in (403, 404, 410):
                    break  # Don't retry on these
            except requests.RequestException as e:
                last_err = e
                self.log.warning("[%s] Request error (attempt %d/%d): %s",
                                 self.STORE_NAME, attempt, self.MAX_RETRIES, e)
            if attempt < self.MAX_RETRIES:
                time.sleep(2 * attempt)  # backoff
        self.log.error("[%s] All retries exhausted for %s — %s",
                       self.STORE_NAME, url, last_err)
        return None

    def _soup(self, url: str, **kwargs) -> BeautifulSoup | None:
        """GET + parse as BeautifulSoup."""
        resp = self._get(url, **kwargs)
        if not resp:
            return None
        return BeautifulSoup(resp.text, "html.parser")

    # ── Caching wrapper ─────────────────────────────────────────────────────

    def _cache_key(self) -> str:
        return self.STORE_NAME.lower().replace(" ", "_")

    def search_cached(self, query: str) -> list[ProductListing]:
        """Search with caching. Falls back to live search on cache miss."""
        ns = self._cache_key()
        cached = _cache.get(ns, query, ttl=self.CACHE_TTL)
        if cached is not None:
            self.log.debug("[%s] Cache hit for '%s'", self.STORE_NAME, query)
            return [ProductListing(**item) for item in cached]

        results = self.search(query)
        if results:
            _cache.put(ns, query, [r.to_dict() for r in results])
        return results

    # ── To be overridden ────────────────────────────────────────────────────

    def search(self, query: str) -> list[ProductListing]:
        """
        Search the retailer for products matching *query*.
        Must be overridden by each adapter.
        Returns a list of ProductListing (may be empty on failure).
        """
        raise NotImplementedError

    # ── Parsing helpers ─────────────────────────────────────────────────────

    @staticmethod
    def parse_price(text: str) -> float | None:
        """Extract a dollar price from text like '$1,234.56' or '1234'."""
        if not text:
            return None
        m = re.search(r"\$?\s*([\d,]+(?:\.\d{1,2})?)", text.replace("\xa0", ""))
        if not m:
            return None
        try:
            val = float(m.group(1).replace(",", ""))
            return val if 1 < val < 50_000 else None
        except ValueError:
            return None

    @staticmethod
    def clean_text(text: str) -> str:
        """Collapse whitespace and strip."""
        return re.sub(r"\s+", " ", text).strip()
