"""
PC STOCKS — Price Scraper (v2)
Orchestrates modular retailer scrapers to find the best AUD prices.

Public API (unchanged — consumed by server.py):
    PART_SCRAPE_CONFIG  — list of part definitions
    scrape_all()        — scrape every part, returns list[dict]
"""

import logging
from datetime import datetime, timezone

from scrapers import search_all_retailers, PCPARTPICKER, ProductListing
from scrapers.matcher import best_match

log = logging.getLogger("scraper")

# ─── Part definitions ────────────────────────────────────────────────────────
# Each entry describes a part to track.  Fields consumed by the scrapers:
#   search_query       — text used to search retailer sites
#   pcpartpicker_url   — (optional) direct PCPartPicker AU product page
#   fallback_price     — last-resort estimated price

PART_SCRAPE_CONFIG = [
    {
        "id": "cpu",
        "type": "CPU",
        "name": "AMD Ryzen 9 9950X",
        "spec": "16-Core / 32-Thread — 4.3 GHz base, 5.7 GHz boost",
        "search_query": "AMD Ryzen 9 9950X",
        "pcpartpicker_url": "https://au.pcpartpicker.com/product/kcQcCJ/amd-ryzen-9-9950x-43-ghz-16-core-processor-100-100001277wof",
        "fallback_price": 825,
    },
    {
        "id": "cooler",
        "type": "CPU Cooler",
        "name": "ARCTIC Liquid Freezer III Pro 360",
        "spec": "360mm AIO — 77 CFM",
        "search_query": "Arctic Liquid Freezer III 360",
        "pcpartpicker_url": "https://au.pcpartpicker.com/product/3nhmP6/arctic-liquid-freezer-iii-pro-360-77-cfm-liquid-cpu-cooler-acfre00142a",
        "fallback_price": 169,
    },
    {
        "id": "mobo",
        "type": "Motherboard",
        "name": "MSI MAG B850M Mortar WiFi",
        "spec": "Micro-ATX AM5 — Wi-Fi 6E, PCIe 5.0 M.2, strong VRM",
        "search_query": "MSI MAG B850M Mortar WiFi",
        "pcpartpicker_url": None,
        "fallback_price": 369,
    },
    {
        "id": "ram",
        "type": "Memory",
        "name": "Corsair Vengeance 96 GB DDR5-6000 CL36 (CMK96GX5M2E6000Z36)",
        "spec": "2 x 48 GB — DDR5-6000 CL36 — CMK96GX5M2E6000Z36",
        "search_query": "CMK96GX5M2E6000Z36",
        "pcpartpicker_url": None,
        "fallback_price": 1099,
    },
    {
        "id": "ssd1",
        "type": "Storage (OS)",
        "name": "Samsung 990 Pro 2 TB NVMe",
        "spec": "M.2-2280 PCIe 4.0 — 7,450 MB/s read",
        "search_query": "Samsung 990 Pro 2TB",
        "pcpartpicker_url": None,
        "fallback_price": 489,
    },
    {
        "id": "gpu",
        "type": "GPU",
        "name": "PNY GeForce RTX 5060 ARGB OC Triple Fan 8 GB (VCG50608TFXXPB1-O)",
        "spec": "GeForce RTX 5060 — 8 GB GDDR7, ARGB triple-fan OC",
        "search_query": "VCG50608TFXXPB1-O",
        "pcpartpicker_url": None,
        "fallback_price": 489,
    },
    {
        "id": "case",
        "type": "Case",
        "name": "Lian Li DAN A3 Wood mATX",
        "spec": "Micro-ATX — wood front panel, 360mm rad support",
        "search_query": "Lian Li DAN A3 Wood",
        "pcpartpicker_url": None,
        "fallback_price": 145,
    },
    {
        "id": "psu",
        "type": "Power Supply",
        "name": "MSI MAG A850GL PCIE5 850W",
        "spec": "80+ Gold — Fully Modular, ATX 3.0",
        "search_query": "MSI MAG A850GL 850W",
        "pcpartpicker_url": "https://au.pcpartpicker.com/product/WnYmP6/msi-mag-a850gl-pcie5-850-w-80-gold-certified-fully-modular-atx-power-supply-mag-a850gl-pcie5",
        "fallback_price": 139,
    },
]


# Temporary manual stock overrides for listings where retailer pages or
# aggregator snippets are known to misreport availability.
STOCK_OVERRIDES = {
}


# ─── Core scraping logic ────────────────────────────────────────────────────

def _scrape_part(part: dict) -> dict:
    """
    Scrape a single part across all retailers and return the best result.

    Strategy:
      1. Query all retailers via search_all_retailers()
      2. Also pull PCPartPicker product page if URL is available
      3. Use the matcher to score every listing against the wanted part
      4. Pick the best match (highest score, in-stock preferred, lowest price)
      5. Fall back to the configured fallback_price if everything fails
    """
    pid = part["id"]
    name = part["name"]
    ptype = part["type"]
    spec = part["spec"]
    query = part.get("search_query") or name
    pcpp_url = part.get("pcpartpicker_url")
    fallback = part["fallback_price"]
    stock_override = STOCK_OVERRIDES.get(pid)

    all_listings: list[ProductListing] = []

    # ── 1. Search all registered retailers ──────────────────────────
    try:
        retailer_results = search_all_retailers(query)
        all_listings.extend(retailer_results)
    except Exception as e:
        log.error("[%s] Retailer search failed: %s", pid, e)

    # ── 2. PCPartPicker product page (if we have a direct URL) ──────
    if pcpp_url:
        try:
            pcpp_results = PCPARTPICKER.scrape_product_page(pcpp_url)
            all_listings.extend(pcpp_results)
        except Exception as e:
            log.error("[%s] PCPartPicker page scrape failed: %s", pid, e)

    # ── 3. Match and pick the best listing ──────────────────────────
    if all_listings:
        listing, match_score = best_match(
            all_listings,
            wanted_name=name,
            wanted_type=ptype,
            wanted_spec=spec,
        )

        if listing:
            source_name = listing.store.lower().replace(" ", "_")
            log.info(
                "✓ %s: $%.2f @ %s (score=%.2f, in_stock=%s, url=%s)",
                name, listing.price, listing.store, match_score,
                listing.in_stock, listing.url[:80],
            )
            return {
                "id": pid,
                "type": ptype,
                "name": name,
                "spec": spec,
                "price": listing.price,
                "retailer": listing.store,
                "source": source_name,
                "in_stock": listing.in_stock,
                "stock_status": getattr(
                    listing,
                    "stock_status",
                    "in_stock" if listing.in_stock else "out_of_stock",
                ),
                "url": listing.url,
                "shipping": listing.shipping,
                "match_score": round(match_score, 2),
            } | (stock_override or {})

    # ── 4. Fallback ─────────────────────────────────────────────────
    log.warning("✗ %s: all sources failed — using fallback $%.2f", name, fallback)
    return {
        "id": pid,
        "type": ptype,
        "name": name,
        "spec": spec,
        "price": fallback,
        "retailer": "Unknown",
        "source": "fallback",
        "in_stock": False,
        "stock_status": "out_of_stock",
        "url": "",
        "shipping": None,
        "match_score": 0.0,
    } | (stock_override or {})


def scrape_all() -> list[dict]:
    """
    Scrape prices for all configured parts.
    Returns list of dicts compatible with the server's run_scrape().
    """
    log.info("━━ Scraping %d parts across all retailers ━━", len(PART_SCRAPE_CONFIG))
    results = []
    for part in PART_SCRAPE_CONFIG:
        log.info("── %s: %s ──", part["type"], part["name"])
        result = _scrape_part(part)
        results.append(result)

    ok = sum(1 for r in results if r["source"] != "fallback")
    log.info("━━ Done: %d/%d parts found real prices ━━", ok, len(results))
    return results


# ─── CLI test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    )
    print("\n🔍 Scraping all parts across all retailers...\n")
    results = scrape_all()
    total = 0
    for r in results:
        total += r["price"]
        icon = "✅" if r["source"] != "fallback" else "⚠️"
        score_str = f"match={r['match_score']:.2f}" if r.get("match_score") else ""
        print(
            f"  {icon} {r['type']:18s}  ${r['price']:>8.2f}  "
            f"[{r['source']}] {r['retailer']:20s} {score_str}"
        )
    print(f"\n  {'TOTAL':>20s}  ${total:>8.2f}")
    print()
