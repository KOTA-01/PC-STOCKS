"""
Scorptec (scorptec.com.au) scraper.

Scorptec is a major Australian PC parts retailer based in Melbourne.
Search URL pattern: https://www.scorptec.com.au/search?q=QUERY
"""

from __future__ import annotations

import re
import json
from urllib.parse import quote_plus

from scrapers.base import BaseScraper, ProductListing


class ScorptecScraper(BaseScraper):
    STORE_NAME = "Scorptec"
    BASE_URL = "https://www.scorptec.com.au"

    def search(self, query: str) -> list[ProductListing]:
        url = f"{self.BASE_URL}/search?q={quote_plus(query)}"
        soup = self._soup(url)
        if not soup:
            return []

        results: list[ProductListing] = []

        # Scorptec product cards in search results
        # Common selectors for their product grid
        product_cards = soup.select(
            ".product-card, .product-item, .product_box, "
            "[class*='product-list'] [class*='product'], "
            ".search-results .item, .product-grid .product"
        )

        if not product_cards:
            # Fallback: try to find any product-like containers
            product_cards = soup.find_all("div", class_=re.compile(r"product", re.I))

        for card in product_cards:
            try:
                # Title
                title_el = card.select_one(
                    "a.product-title, .product-name a, .product_title a, "
                    "h2 a, h3 a, h4 a, .name a, a[class*='title']"
                )
                if not title_el:
                    title_el = card.find("a", href=re.compile(r"/product/"))
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
                    ".product-price, .price, .product_price, "
                    "[class*='price']:not([class*='was']):not([class*='rrp']), "
                    ".current-price, .sale-price"
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

                # Stock status
                card_text = card.get_text().lower()
                in_stock = not any(x in card_text for x in [
                    "out of stock", "sold out", "unavailable", "pre-order"
                ])

                # Shipping
                shipping = None
                if "free shipping" in card_text or "free delivery" in card_text:
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
                self.log.debug("Error parsing Scorptec card: %s", e)
                continue

        # Fallback: try JSON-LD
        if not results:
            results = self._try_json_ld(soup)

        return results

    def _try_json_ld(self, soup) -> list[ProductListing]:
        """Try to extract product data from JSON-LD structured data."""
        results = []
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") not in ("Product", "ItemList"):
                        continue
                    if item.get("@type") == "ItemList":
                        for elem in item.get("itemListElement", []):
                            product = elem.get("item", elem)
                            listing = self._parse_jsonld_product(product)
                            if listing:
                                results.append(listing)
                    else:
                        listing = self._parse_jsonld_product(item)
                        if listing:
                            results.append(listing)
            except Exception:
                continue
        return results

    def _parse_jsonld_product(self, product: dict) -> ProductListing | None:
        """Parse a single JSON-LD Product object."""
        name = product.get("name", "")
        offers = product.get("offers", {})
        if isinstance(offers, list):
            offers = offers[0] if offers else {}

        price = offers.get("price") or offers.get("lowPrice")
        if not price:
            return None

        try:
            price_val = float(price)
        except (ValueError, TypeError):
            return None

        url = product.get("url", offers.get("url", ""))
        if url and not url.startswith("http"):
            url = self.BASE_URL + url

        in_stock = "InStock" in offers.get("availability", "")

        return ProductListing(
            title=name,
            price=price_val,
            url=url,
            store=self.STORE_NAME,
            in_stock=in_stock,
        )
