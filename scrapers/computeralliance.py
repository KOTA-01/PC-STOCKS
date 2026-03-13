"""
Computer Alliance (computeralliance.com.au) scraper.

Computer Alliance is a Brisbane-based PC retailer.
Search URL pattern: https://www.computeralliance.com.au/search?w=QUERY
"""

from __future__ import annotations

import re
import json
from urllib.parse import quote_plus

from scrapers.base import BaseScraper, ProductListing


class ComputerAllianceScraper(BaseScraper):
    STORE_NAME = "Computer Alliance"
    BASE_URL = "https://www.computeralliance.com.au"

    def search(self, query: str) -> list[ProductListing]:
        # Computer Alliance uses SLI Systems or similar for search
        url = f"{self.BASE_URL}/search?w={quote_plus(query)}"
        soup = self._soup(url)
        if not soup:
            return []

        results: list[ProductListing] = []

        # Computer Alliance product listings
        product_cards = soup.select(
            ".product-item, .product-card, .product-listing .product, "
            "[class*='product-list'] .item, .search-results .product, "
            ".product-grid .product, li.product"
        )

        if not product_cards:
            product_cards = soup.find_all("div", class_=re.compile(r"product[-_]item|product[-_]card", re.I))

        for card in product_cards:
            try:
                # Title
                title_el = card.select_one(
                    "a.product-title, .product-name a, .product-item-name a, "
                    "h2 a, h3 a, h4 a, a[class*='product']"
                )
                if not title_el:
                    title_el = card.find("a", href=re.compile(r"computeralliance\.com\.au/"))
                if not title_el:
                    continue

                title = self.clean_text(title_el.get_text())
                if not title or len(title) < 5:
                    continue

                # URL
                href = title_el.get("href", "")
                if not href.startswith("http"):
                    href = self.BASE_URL + href

                # Price
                price_el = card.select_one(
                    ".product-price, .price, [class*='price']:not([class*='was'])"
                )
                price = None
                if price_el:
                    price = self.parse_price(price_el.get_text())

                if not price:
                    price_match = re.search(r"\$[\d,]+\.?\d*", card.get_text())
                    if price_match:
                        price = self.parse_price(price_match.group())

                if not price:
                    continue

                # Stock
                card_text = card.get_text().lower()
                in_stock = not any(x in card_text for x in [
                    "out of stock", "sold out", "unavailable", "pre-order"
                ])

                # Shipping
                shipping = None
                if "free shipping" in card_text or "free freight" in card_text:
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
                self.log.debug("Error parsing Computer Alliance card: %s", e)
                continue

        # Fallback: JSON-LD
        if not results:
            results = self._try_json_ld(soup)

        return results

    def _try_json_ld(self, soup) -> list[ProductListing]:
        results = []
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "Product":
                        continue
                    offers = item.get("offers", {})
                    if isinstance(offers, list):
                        offers = offers[0] if offers else {}
                    p = offers.get("price") or offers.get("lowPrice")
                    if not p:
                        continue
                    url = item.get("url", "")
                    if url and not url.startswith("http"):
                        url = self.BASE_URL + url
                    results.append(ProductListing(
                        title=item.get("name", ""),
                        price=float(p),
                        url=url,
                        store=self.STORE_NAME,
                        in_stock="InStock" in offers.get("availability", ""),
                    ))
            except Exception:
                continue
        return results
