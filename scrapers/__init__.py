"""
scrapers — Modular Australian PC retailer scraping framework.

Usage:
    from scrapers import REGISTRY, search_all_retailers
    results = search_all_retailers("AMD Ryzen 9 9950X")
"""

from scrapers.base import BaseScraper, ProductListing
from scrapers.pcpartpicker import PCPartPickerScraper
from scrapers.staticice import StaticICEScraper
from scrapers.scorptec import ScorptecScraper
from scrapers.pccasegear import PCCaseGearScraper
from scrapers.centrecom import CentreComScraper
from scrapers.umart import UmartScraper
from scrapers.amazon_au import AmazonAUScraper
from scrapers.computeralliance import ComputerAllianceScraper
from scrapers.msy import MSYScraper

# ─── Scraper registry ───────────────────────────────────────────────────────
# Instantiate one of each adapter. Add new retailers here.

REGISTRY: list[BaseScraper] = [
    StaticICEScraper(),       # Meta-aggregator — often the best single source
    ScorptecScraper(),
    PCCaseGearScraper(),
    CentreComScraper(),
    UmartScraper(),
    ComputerAllianceScraper(),
    MSYScraper(),
    AmazonAUScraper(),         # Last because most likely to fail / CAPTCHA
]

# PCPartPicker is handled separately because it scrapes per-product-URL
# rather than via search queries. Keep a singleton available.
PCPARTPICKER = PCPartPickerScraper()


def search_all_retailers(
    query: str,
    use_cache: bool = True,
) -> list[ProductListing]:
    """
    Search every registered retailer for *query*.
    Returns a flat list of ProductListing from all retailers that responded.
    Each retailer is isolated — one failure won't affect the others.
    """
    import logging
    log = logging.getLogger("scrapers")

    all_results: list[ProductListing] = []

    for scraper in REGISTRY:
        try:
            if use_cache:
                results = scraper.search_cached(query)
            else:
                results = scraper.search(query)
            if results:
                log.info("[%s] returned %d results for '%s'",
                         scraper.STORE_NAME, len(results), query)
                all_results.extend(results)
            else:
                log.info("[%s] no results for '%s'", scraper.STORE_NAME, query)
        except Exception as e:
            log.error("[%s] FAILED for '%s': %s", scraper.STORE_NAME, query, e)

    return all_results


__all__ = [
    "BaseScraper",
    "ProductListing",
    "REGISTRY",
    "PCPARTPICKER",
    "search_all_retailers",
]
