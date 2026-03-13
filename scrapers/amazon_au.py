"""
Amazon Australia (amazon.com.au) scraper.

Amazon AU is more aggressive with anti-scraping measures, so this adapter
is best-effort and may fail. It's isolated so failure here won't break
the rest of the comparison.

Search URL pattern: https://www.amazon.com.au/s?k=QUERY
"""

from __future__ import annotations

import re
import json
from urllib.parse import quote_plus

from scrapers.base import BaseScraper, ProductListing


class AmazonAUScraper(BaseScraper):
    STORE_NAME = "Amazon AU"
    BASE_URL = "https://www.amazon.com.au"
    TIMEOUT = 20  # Amazon can be slow
    MAX_RETRIES = 1  # Don't hammer Amazon

    def search(self, query: str) -> list[ProductListing]:
        url = f"{self.BASE_URL}/s?k={quote_plus(query)}"

        resp = self._get(url)
        if not resp:
            return []

        # Amazon often returns CAPTCHA pages; detect and bail
        if "captcha" in resp.text.lower() or "robot" in resp.text.lower():
            self.log.warning("[Amazon AU] CAPTCHA detected — skipping")
            return []

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")

        results: list[ProductListing] = []

        # Amazon search result items
        items = soup.select(
            "[data-component-type='s-search-result'], "
            ".s-result-item[data-asin], "
            ".sg-col-inner .s-result-item"
        )

        for item in items:
            try:
                asin = item.get("data-asin", "")
                if not asin:
                    continue

                # Title
                title_el = item.select_one(
                    "h2 a span, h2 span.a-text-normal, "
                    ".a-size-medium.a-text-normal, .a-size-base-plus"
                )
                if not title_el:
                    continue

                title = self.clean_text(title_el.get_text())
                if not title or len(title) < 5:
                    continue

                # URL
                link = item.select_one("h2 a, a.a-link-normal[href*='/dp/']")
                href = ""
                if link:
                    href = link.get("href", "")
                    if not href.startswith("http"):
                        href = self.BASE_URL + href
                if not href:
                    href = f"{self.BASE_URL}/dp/{asin}"

                # Price — Amazon has multiple price formats
                price = None
                price_el = item.select_one(
                    ".a-price .a-offscreen, "
                    ".a-price-whole, "
                    "span.a-price span[aria-hidden='true']"
                )
                if price_el:
                    price = self.parse_price(price_el.get_text())

                if not price:
                    # Try the whole/fraction pattern
                    whole_el = item.select_one(".a-price-whole")
                    frac_el = item.select_one(".a-price-fraction")
                    if whole_el:
                        whole = whole_el.get_text(strip=True).replace(",", "").rstrip(".")
                        frac = frac_el.get_text(strip=True) if frac_el else "00"
                        try:
                            price = float(f"{whole}.{frac}")
                        except ValueError:
                            pass

                if not price:
                    continue

                # Stock — Amazon doesn't always show stock on search
                card_text = item.get_text().lower()
                in_stock = "currently unavailable" not in card_text

                # Shipping
                shipping = None
                delivery_el = item.select_one(".a-row.a-size-base .a-color-base")
                if delivery_el:
                    delivery_text = delivery_el.get_text().lower()
                    if "free" in delivery_text:
                        shipping = 0.0

                results.append(ProductListing(
                    title=title,
                    price=price,
                    url=href,
                    store=self.STORE_NAME,
                    in_stock=in_stock,
                    shipping=shipping,
                ))
            except Exception as e:
                self.log.debug("Error parsing Amazon item: %s", e)
                continue

        return results
