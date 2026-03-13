"""
PCPartPicker Australia scraper.
Queries the AU version of PCPartPicker for product pricing data.
"""

from __future__ import annotations

import re
import json

from scrapers.base import BaseScraper, ProductListing


class PCPartPickerScraper(BaseScraper):
    STORE_NAME = "PCPartPicker AU"
    BASE_URL = "https://au.pcpartpicker.com"

    def search(self, query: str) -> list[ProductListing]:
        """
        PCPartPicker doesn't have a clean search API — we use their search
        endpoint and parse the results page.
        """
        url = f"{self.BASE_URL}/search/?q={query}"
        soup = self._soup(url)
        if not soup:
            return []

        results: list[ProductListing] = []

        # Search results are typically in a list/table of product links
        for row in soup.select(".search_results--list .search_results--link, .productListing tr"):
            try:
                link = row.find("a", href=True)
                if not link:
                    continue

                title = self.clean_text(link.get_text())
                if not title:
                    continue

                href = link["href"]
                if not href.startswith("http"):
                    href = self.BASE_URL + href

                price = None
                price_el = row.select_one(".product_price, .price, .td__finalPrice")
                if price_el:
                    price = self.parse_price(price_el.get_text())

                if not price:
                    price_match = re.search(r"\$[\d,]+\.?\d*", row.get_text())
                    if price_match:
                        price = self.parse_price(price_match.group())

                if not price:
                    continue

                in_stock = "out of stock" not in row.get_text().lower()

                results.append(ProductListing(
                    title=title,
                    price=price,
                    url=href,
                    store=self.STORE_NAME,
                    in_stock=in_stock,
                ))
            except Exception as e:
                self.log.debug("Error parsing PCPartPicker row: %s", e)
                continue

        return results

    def scrape_product_page(self, url: str) -> list[ProductListing]:
        """
        Scrape a specific PCPartPicker product page for retailer prices.
        This is the more reliable path when we have a direct product URL.
        """
        if not url or "pcpartpicker.com/product/" not in url:
            return []

        # Ensure AU site
        if "au." not in url:
            url = url.replace("pcpartpicker.com", "au.pcpartpicker.com")

        soup = self._soup(url)
        if not soup:
            return []

        results: list[ProductListing] = []

        # Parse the retailer prices table
        prices_table = soup.find("table", class_="xs-col-12")
        if not prices_table:
            section = soup.find("section", class_="prices")
            if section:
                prices_table = section.find("table")

        if prices_table:
            for row in prices_table.find_all("tr"):
                cells = row.find_all("td")
                if len(cells) < 2:
                    continue

                row_text = row.get_text(" ", strip=True)
                in_stock = "out of stock" not in row_text.lower()

                # Find price
                price = None
                for cell in cells:
                    price = self.parse_price(cell.get_text())
                    if price:
                        break

                if not price:
                    continue

                # Find retailer name
                retailer = "PCPartPicker AU"
                retailer_el = row.find("td", class_="td__logo") or row.find("a")
                if retailer_el:
                    img = retailer_el.find("img")
                    if img and img.get("alt"):
                        retailer = img["alt"]
                    elif retailer_el.get_text(strip=True):
                        retailer = retailer_el.get_text(strip=True)

                # Find product link
                link = row.find("a", href=True)
                product_url = url
                if link and link.get("href", "").startswith("http"):
                    product_url = link["href"]

                # Find product title from page
                title_el = soup.find("h1", class_="pageTitle") or soup.find("h1")
                title = self.clean_text(title_el.get_text()) if title_el else "Unknown"

                # Shipping info
                shipping = None
                ship_cell = row.find("td", class_="td__shipping")
                if ship_cell:
                    ship_text = ship_cell.get_text(strip=True)
                    if "free" in ship_text.lower():
                        shipping = 0.0
                    else:
                        shipping = self.parse_price(ship_text)

                results.append(ProductListing(
                    title=title,
                    price=price,
                    url=product_url,
                    store=retailer,
                    in_stock=in_stock,
                    shipping=shipping,
                ))

        # Fallback: try JSON-LD structured data
        if not results:
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict):
                        offers = data.get("offers", {})
                        title = data.get("name", "Unknown")
                        offer_list = offers if isinstance(offers, list) else [offers]
                        for offer in offer_list:
                            p = offer.get("price") or offer.get("lowPrice")
                            if p:
                                results.append(ProductListing(
                                    title=title,
                                    price=float(p),
                                    url=url,
                                    store=offer.get("seller", {}).get("name", self.STORE_NAME),
                                    in_stock=offer.get("availability", "").endswith("InStock"),
                                ))
                except Exception:
                    pass

        return results
