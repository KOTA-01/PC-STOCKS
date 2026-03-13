"""
StaticICE Australia scraper.
StaticICE is a price comparison engine that aggregates Australian retailers.
"""

from __future__ import annotations

import re

import requests.utils

from scrapers.base import BaseScraper, ProductListing


class StaticICEScraper(BaseScraper):
    STORE_NAME = "StaticICE"
    BASE_URL = "https://www.staticice.com.au"
    SEARCH_URL = "https://www.staticice.com.au/cgi-bin/search.cgi"

    def search(self, query: str) -> list[ProductListing]:
        """Search StaticICE and return all matching product listings."""
        url = f"{self.SEARCH_URL}?q={requests.utils.quote(query)}&stype=1&num=20"
        soup = self._soup(url)
        if not soup:
            return []

        results: list[ProductListing] = []

        for row in soup.find_all("tr", valign="top"):
            cells = row.find_all("td", recursive=False)
            if len(cells) < 2:
                continue

            # First cell: price link via redirect.cgi
            price_link = cells[0].find("a", href=re.compile(r"redirect\.cgi"))
            if not price_link:
                continue

            price_text = price_link.get_text(strip=True)
            price = self.parse_price(price_text)
            if not price or price < 10 or price > 10_000:
                continue

            # Store name from redirect URL's "name" parameter
            href = price_link.get("href", "")
            store_match = re.search(r"name=([^&]+)", href)
            store = requests.utils.unquote(store_match.group(1)) if store_match else "Unknown"

            # Product description from second cell
            desc = self.clean_text(cells[1].get_text(" ", strip=True))
            font_tag = cells[1].find("font")
            if font_tag:
                desc_parts = cells[1].get_text(" ", strip=True).split(font_tag.get_text(" ", strip=True))
                desc = desc_parts[0].strip() if desc_parts else desc

            # Product URL (the redirect URL resolves to the retailer page)
            product_url = href
            if product_url and not product_url.startswith("http"):
                product_url = self.BASE_URL + "/" + product_url.lstrip("/")

            # Stock status
            alt_text = price_link.get("alt", "") + price_link.get("title", "")
            in_stock = "out of stock" not in alt_text.lower()

            # Shipping (StaticICE sometimes shows delivery info)
            shipping = None
            ship_text = cells[0].get_text(" ", strip=True)
            if "free" in ship_text.lower() and "ship" in ship_text.lower():
                shipping = 0.0

            results.append(ProductListing(
                title=desc,
                price=price,
                url=product_url,
                store=store,
                in_stock=in_stock,
                shipping=shipping,
            ))

        if not results:
            self.log.warning("No StaticICE results for: %s", query)

        return results
