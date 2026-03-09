"""
PC STOCKS — Price Scraper
Fetches real AUD prices from PCPartPicker AU and StaticICE.
Falls back gracefully if a source is unreachable.
"""

import re
import time
import logging
import requests
from bs4 import BeautifulSoup

log = logging.getLogger("scraper")

# ─── Common HTTP helpers ────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-AU,en;q=0.9",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

# Polite delay between requests to the same domain
_last_request_time: dict[str, float] = {}
RATE_LIMIT_SECONDS = 3.0


def _rate_limit(domain: str):
    """Sleep if we've hit the same domain recently."""
    now = time.time()
    last = _last_request_time.get(domain, 0)
    wait = RATE_LIMIT_SECONDS - (now - last)
    if wait > 0:
        time.sleep(wait)
    _last_request_time[domain] = time.time()


def _get(url: str, timeout: int = 15) -> requests.Response | None:
    """GET with rate limiting and error handling."""
    from urllib.parse import urlparse
    domain = urlparse(url).netloc
    _rate_limit(domain)
    try:
        resp = SESSION.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp
    except Exception as e:
        log.warning("GET %s failed: %s", url, e)
        return None


# ─── PCPartPicker AU ────────────────────────────────────────────────────────

def scrape_pcpartpicker(url: str) -> dict | None:
    """
    Scrape a PCPartPicker AU product page.
    Returns {"price": float, "retailer": str, "in_stock": bool} or None.
    """
    if not url or "pcpartpicker.com/product/" not in url:
        return None

    # Make sure it's the AU site
    url = url.replace("pcpartpicker.com", "au.pcpartpicker.com") if "au." not in url else url

    resp = _get(url)
    if not resp:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    # ── Strategy 1: Parse the price list table ──
    prices_table = soup.find("table", class_="xs-col-12")
    if not prices_table:
        # Try alternative: the prices section
        prices_section = soup.find("section", class_="prices")
        if prices_section:
            prices_table = prices_section.find("table")

    if prices_table:
        best_price = None
        best_retailer = None
        best_in_stock = False

        for row in prices_table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 2:
                continue

            row_text = row.get_text(" ", strip=True)
            row_in_stock = "out of stock" not in row_text.lower()

            # Find the final price cell (usually last or second-to-last)
            price_text = None
            retailer_text = None

            for cell in cells:
                text = cell.get_text(strip=True)
                # Look for price pattern like $824.52
                price_match = re.search(r'\$[\d,]+\.?\d*', text)
                if price_match:
                    try:
                        val = float(price_match.group().replace("$", "").replace(",", ""))
                        # Prefer in-stock items; among same stock status, pick cheapest
                        is_better = (
                            best_price is None
                            or (row_in_stock and not best_in_stock)
                            or (row_in_stock == best_in_stock and val < best_price)
                        )
                        if is_better:
                            best_price = val
                            best_in_stock = row_in_stock
                            # Try to find retailer name from the row
                            retailer_el = row.find("td", class_="td__logo") or row.find("a")
                            if retailer_el:
                                img = retailer_el.find("img")
                                if img and img.get("alt"):
                                    retailer_text = img["alt"]
                                elif retailer_el.get_text(strip=True):
                                    retailer_text = retailer_el.get_text(strip=True)
                    except ValueError:
                        pass

            if price_text is None and best_price is not None:
                pass  # We already set it above

        if best_price is not None:
            return {
                "price": best_price,
                "retailer": retailer_text or "Unknown",
                "in_stock": best_in_stock,
            }

    # ── Strategy 2: Find price in structured data or meta tags ──
    # Look for JSON-LD
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            import json
            data = json.loads(script.string)
            if isinstance(data, dict):
                offers = data.get("offers", {})
                if isinstance(offers, list):
                    for offer in offers:
                        p = offer.get("price")
                        if p:
                            return {
                                "price": float(p),
                                "retailer": offer.get("seller", {}).get("name", "Unknown"),
                                "in_stock": True,
                            }
                elif isinstance(offers, dict):
                    p = offers.get("lowPrice") or offers.get("price")
                    if p:
                        return {
                            "price": float(p),
                            "retailer": "PCPartPicker AU",
                            "in_stock": True,
                        }
        except Exception:
            pass

    # ── Strategy 3: Regex the page for a prominent price ──
    page_text = soup.get_text()
    # Look for the "best price" pattern
    price_matches = re.findall(r'\$(\d{2,4}(?:\.\d{2})?)', page_text)
    if price_matches:
        prices_float = [float(p) for p in price_matches if 30 < float(p) < 5000]
        if prices_float:
            return {
                "price": min(prices_float),
                "retailer": "PCPartPicker AU",
                "in_stock": True,
            }

    log.warning("Could not parse price from PCPartPicker: %s", url)
    return None


# ─── StaticICE AU ───────────────────────────────────────────────────────────

STATICICE_SEARCH = "https://www.staticice.com.au/cgi-bin/search.cgi"


def _parse_staticice_rows(soup: BeautifulSoup) -> list[dict]:
    """
    Parse StaticICE's table-based HTML.
    Each product row is: <tr valign="top"> with two <td> cells:
      - td[0]: <a href="/cgi-bin/redirect.cgi?name=STORE&...">$PRICE</a>
      - td[1]: product description + store name/logo, state, date
    Returns list of {"price": float, "retailer": str, "description": str}.
    """
    results = []
    for row in soup.find_all("tr", valign="top"):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 2:
            continue

        # First cell should contain a price link to redirect.cgi
        price_link = cells[0].find("a", href=re.compile(r"redirect\.cgi"))
        if not price_link:
            continue

        price_text = price_link.get_text(strip=True)
        price_match = re.match(r"\$(\d[\d,]*(?:\.\d{2})?)", price_text)
        if not price_match:
            continue

        try:
            price = float(price_match.group(1).replace(",", ""))
        except ValueError:
            continue

        if price < 10 or price > 10_000:
            continue

        # Extract store name from the redirect URL's "name" parameter
        href = price_link.get("href", "")
        store_match = re.search(r"name=([^&]+)", href)
        store = requests.utils.unquote(store_match.group(1)) if store_match else "Unknown"

        # Extract product description from the second cell
        desc = cells[1].get_text(" ", strip=True)
        # Trim off the store/date footer (after the first <font> or <br>)
        font_tag = cells[1].find("font")
        if font_tag:
            desc = cells[1].get_text(" ", strip=True).split(font_tag.get_text(" ", strip=True))[0].strip()

        # Check stock status from the alt/title attribute
        alt_text = price_link.get("alt", "") + price_link.get("title", "")
        in_stock = "out of stock" not in alt_text.lower()

        results.append({
            "price": price,
            "retailer": store,
            "description": desc,
            "in_stock": in_stock,
        })

    return results


def scrape_staticice(query: str) -> dict | None:
    """
    Search StaticICE for an Australian product price.
    Returns {"price": float, "retailer": str, "in_stock": bool} or None.
    """
    if not query:
        return None

    url = f"{STATICICE_SEARCH}?q={requests.utils.quote(query)}&stype=1&num=20"
    resp = _get(url)
    if not resp:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    rows = _parse_staticice_rows(soup)

    if not rows:
        log.warning("No StaticICE results for: %s", query)
        return None

    # Prefer in-stock results; pick lowest price among them
    in_stock = [r for r in rows if r["in_stock"]]
    pool = in_stock if in_stock else rows

    best = min(pool, key=lambda r: r["price"])
    log.info(
        "StaticICE [%s]: $%.2f @ %s — %s",
        query, best["price"], best["retailer"], best["description"][:60],
    )
    return {
        "price": best["price"],
        "retailer": best["retailer"],
        "in_stock": best.get("in_stock", True),
    }


# ─── Combined scraper ───────────────────────────────────────────────────────

def fetch_price(
    pcpartpicker_url: str | None = None,
    staticice_query: str | None = None,
    fallback_price: float = 0,
) -> dict:
    """
    Try multiple sources to get a current AUD price.
    Returns {"price": float, "retailer": str, "source": str, "in_stock": bool}.
    """

    pcpp_result = None

    # 1. Try PCPartPicker
    if pcpartpicker_url and "/product/" in pcpartpicker_url:
        result = scrape_pcpartpicker(pcpartpicker_url)
        if result:
            result["source"] = "pcpartpicker"
            log.info("PCPartPicker price: $%.2f from %s (in_stock=%s)",
                     result["price"], result["retailer"], result["in_stock"])
            if result["in_stock"]:
                return result
            # Keep out-of-stock result as a fallback reference
            pcpp_result = result

    # 2. Try StaticICE
    if staticice_query:
        result = scrape_staticice(staticice_query)
        if result:
            result["source"] = "staticice"
            log.info("StaticICE price: $%.2f from %s", result["price"], result["retailer"])
            return result

    # 3. Return out-of-stock PCPartPicker result if we had one
    if pcpp_result:
        log.info("Using out-of-stock PCPartPicker result as last resort")
        return pcpp_result

    # 3. Fallback
    log.warning("All sources failed, using fallback price: $%.2f", fallback_price)
    return {
        "price": fallback_price,
        "retailer": "Unknown",
        "source": "fallback",
        "in_stock": False,
    }


# ─── Part definitions with scraping config ──────────────────────────────────

PART_SCRAPE_CONFIG = [
    {
        "id": "cpu",
        "type": "CPU",
        "name": "AMD Ryzen 9 9950X",
        "spec": "16-Core / 32-Thread — 4.3 GHz base, 5.7 GHz boost",
        "pcpartpicker_url": "https://au.pcpartpicker.com/product/kcQcCJ/amd-ryzen-9-9950x-43-ghz-16-core-processor-100-100001277wof",
        "staticice_query": "AMD Ryzen 9 9950X",
        "fallback_price": 825,
    },
    {
        "id": "cooler",
        "type": "CPU Cooler",
        "name": "ARCTIC Liquid Freezer III Pro 360",
        "spec": "360mm AIO — 77 CFM",
        "pcpartpicker_url": "https://au.pcpartpicker.com/product/3nhmP6/arctic-liquid-freezer-iii-pro-360-77-cfm-liquid-cpu-cooler-acfre00142a",
        "staticice_query": "Arctic Liquid Freezer III 360",
        "fallback_price": 169,
    },
    {
        "id": "mobo",
        "type": "Motherboard",
        "name": "MSI MAG X870 Tomahawk WiFi",
        "spec": "ATX AM5 — Wi-Fi 7, PCIe 5.0, 4x M.2",
        "pcpartpicker_url": "https://au.pcpartpicker.com/product/3rLFf7/msi-mag-x870-tomahawk-wifi-atx-am5-motherboard-mag-x870-tomahawk-wifi",
        "staticice_query": "MSI MAG X870 Tomahawk WiFi",
        "fallback_price": 467,
    },
    {
        "id": "ram",
        "type": "Memory",
        "name": "Corsair Vengeance 96 GB DDR5-6000 CL36",
        "spec": "2 x 48 GB — DDR5-6000 CL36",
        "pcpartpicker_url": None,
        "staticice_query": "Corsair Vengeance 96GB DDR5 6000",
        "fallback_price": 900,
    },
    {
        "id": "ssd1",
        "type": "Storage (OS)",
        "name": "Samsung 990 Pro 2 TB NVMe",
        "spec": "M.2-2280 PCIe 4.0 — 7,450 MB/s read",
        "pcpartpicker_url": "https://au.pcpartpicker.com/product/wkK322/samsung-990-pro-2-tb-m2-2280-pcie-40-x4-nvme-solid-state-drive-mz-v9p2t0bw",
        "staticice_query": "Samsung 990 Pro 2TB",
        "fallback_price": 280,
    },
    {
        "id": "gpu",
        "type": "GPU",
        "name": "ASUS ProArt RTX 4060 OC 8 GB",
        "spec": "GeForce RTX 4060 — workstation-quiet design",
        "pcpartpicker_url": "https://au.pcpartpicker.com/product/F7h7YJ/asus-proart-oc-geforce-rtx-4060-8-gb-video-card-proart-rtx4060-o8g",
        "staticice_query": "ASUS ProArt RTX 4060",
        "fallback_price": 499,
    },
    {
        "id": "case",
        "type": "Case",
        "name": "Lian Li DAN A3 Wood mATX",
        "spec": "Micro-ATX — wood front panel, 360mm rad support",
        "pcpartpicker_url": None,
        "staticice_query": "Lian Li DAN A3 Wood",
        "fallback_price": 145,
    },
    {
        "id": "psu",
        "type": "Power Supply",
        "name": "MSI MAG A850GL PCIE5 850W",
        "spec": "80+ Gold — Fully Modular, ATX 3.0",
        "pcpartpicker_url": "https://au.pcpartpicker.com/product/WnYmP6/msi-mag-a850gl-pcie5-850-w-80-gold-certified-fully-modular-atx-power-supply-mag-a850gl-pcie5",
        "staticice_query": "MSI MAG A850GL 850W",
        "fallback_price": 139,
    },
]


def scrape_all() -> list[dict]:
    """
    Scrape prices for all parts.
    Returns list of {id, type, name, spec, price, retailer, source, in_stock}.
    """
    results = []
    for part in PART_SCRAPE_CONFIG:
        log.info("Scraping %s: %s ...", part["type"], part["name"])
        price_data = fetch_price(
            pcpartpicker_url=part.get("pcpartpicker_url"),
            staticice_query=part.get("staticice_query"),
            fallback_price=part["fallback_price"],
        )
        results.append({
            "id": part["id"],
            "type": part["type"],
            "name": part["name"],
            "spec": part["spec"],
            "price": price_data["price"],
            "retailer": price_data["retailer"],
            "source": price_data["source"],
            "in_stock": price_data["in_stock"],
        })
    return results


# ─── CLI test ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    print("\n🔍 Scraping all parts...\n")
    results = scrape_all()
    total = 0
    for r in results:
        total += r["price"]
        status = "✅" if r["source"] != "fallback" else "⚠️"
        print(f"  {status} {r['type']:18s}  ${r['price']:>8.2f}  [{r['source']}] {r['retailer']}")
    print(f"\n  {'TOTAL':>20s}  ${total:>8.2f}")
    print()
