"""
Simple time-based cache for scraper results.
Avoids hammering retailers on repeated searches within a short window.
"""

import json
import time
import hashlib
import logging
from pathlib import Path

log = logging.getLogger("scrapers.cache")

_CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "scraper_cache"
_DEFAULT_TTL = 1800  # 30 minutes


def _ensure_dir():
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _key(namespace: str, query: str) -> str:
    """Deterministic cache key from namespace + query."""
    raw = f"{namespace}:{query}".lower().strip()
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def get(namespace: str, query: str, ttl: int = _DEFAULT_TTL):
    """Return cached value if it exists and hasn't expired, else None."""
    _ensure_dir()
    path = _CACHE_DIR / f"{_key(namespace, query)}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        if time.time() - data.get("ts", 0) > ttl:
            return None
        return data.get("value")
    except Exception:
        return None


def put(namespace: str, query: str, value):
    """Store a value in the cache."""
    _ensure_dir()
    path = _CACHE_DIR / f"{_key(namespace, query)}.json"
    try:
        path.write_text(json.dumps({"ts": time.time(), "value": value}))
    except Exception as e:
        log.warning("Cache write failed: %s", e)


def clear(namespace: str | None = None):
    """Clear all cache or just one namespace (by prefix convention)."""
    _ensure_dir()
    count = 0
    for f in _CACHE_DIR.glob("*.json"):
        try:
            f.unlink()
            count += 1
        except Exception:
            pass
    log.info("Cleared %d cache entries", count)
