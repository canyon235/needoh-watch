"""
Scraper for desertcart.ae - UAE e-commerce store.
Uses API endpoint for search with HTML fallback.
"""

import requests
import json
import re
from bs4 import BeautifulSoup
from scrapers.base import BaseScraper, ScrapingResult, HEADERS


class DesertcartScraper(BaseScraper):
    """Scraper for Desertcart.ae with API-first approach."""

    STORE_NAME = "Desertcart"
    BASE_URL = "https://www.desertcart.ae"
    API_ENDPOINT = f"{BASE_URL}/api/products"
    SEARCH_URL = f"{BASE_URL}/search"

    def __init__(self):
        super().__init__()
        # Override headers for API calls
        self.api_headers = HEADERS.copy()
        self.api_headers["Accept"] = "application/json"

    def _is_relevant(self, product_title):
        """
        Filter results for relevance to NeeDoh products.
        Returns True if the product appears to be a NeeDoh fidget toy.
        """
        if not product_title:
            return False

        title_lower = product_title.lower()

        # Positive indicators
        needoh_keywords = [
            "needoh", "fidget", "sensory", "stress relief", "pop it",
            "squeeze toy", "hand toy", "stress ball", "anxiety toy"
        ]

        has_positive = any(keyword in title_lower for keyword in needoh_keywords)

        # Negative indicators to exclude irrelevant products
        exclude_keywords = [
            "book", "clothing", "furniture", "decorative", "poster",
            "wall art", "pillow", "blanket", "plush toy"
        ]

        has_negative = any(keyword in title_lower for keyword in exclude_keywords)

        return has_positive and not has_negative

    def search(self, query):
        """
        Search for products using API endpoint first, fall back to HTML parsing.
        Returns list of product data dictionaries.
        """
        products = []

        # Try API endpoint first
        api_products = self._search_api(query)
        if api_products:
            products.extend(api_products)
            return products

        # Fall back to HTML search page parsing
        html_products = self._search_html(query)
        if html_products:
            products.extend(html_products)

        return products

    def _search_api(self, query):
        """
        Search using the API endpoint.
        Returns list of product data dicts or empty list on failure.
        """
        try:
            params = {"q": query}
            url = f"{self.API_ENDPOINT}?q={query}"

            response = self.session.get(
                url,
                headers=self.api_headers,
                timeout=15
            )
            response.raise_for_status()

            data = response.json()

            # Extract products from API response
            products = []
            if isinstance(data, dict) and "products" in data:
                products = data.get("products", [])
            elif isinstance(data, list):
                products = data

            return products

        except (requests.RequestException, json.JSONDecodeError, KeyError) as e:
            print(f"API search failed for '{query}': {str(e)}")
            return []

    def _search_html(self, query):
        """
        Search using HTML page parsing as fallback.
        Returns list of product data dicts.
        """
        try:
            params = {"q": query}
            html = self.fetch_page(
                self.SEARCH_URL,
                timeout=15
            )

            if not html:
                return []

            soup = BeautifulSoup(html, "html.parser")
            products = []

            # Look for product containers - adjust selector based on actual HTML structure
            product_items = soup.find_all("div", class_=re.compile("product|item", re.I))

            for item in product_items:
                try:
                    title_elem = item.find(["h2", "h3", "a"], class_=re.compile("title|name", re.I))
                    title = title_elem.get_text(strip=True) if title_elem else None

                    if not title or not self._is_relevant(title):
                        continue

                    # Extract price
                    price_elem = item.find(["span", "div"], class_=re.compile("price", re.I))
                    price_text = price_elem.get_text(strip=True) if price_elem else None
                    price = self.parse_price(price_text)

                    # Extract product URL
                    url_elem = item.find("a", href=True)
                    product_url = url_elem["href"] if url_elem else None
                    if product_url and not product_url.startswith("http"):
                        product_url = f"{self.BASE_URL}{product_url}"

                    # Check stock status
                    stock_text = item.get_text(strip=True).lower()
                    in_stock = "out of stock" not in stock_text and "unavailable" not in stock_text

                    products.append({
                        "title": title,
                        "price": price,
                        "url": product_url,
                        "in_stock": in_stock,
                        "raw_html": str(item)
                    })

                except Exception as e:
                    print(f"Error parsing product item: {str(e)}")
                    continue

            return products

        except Exception as e:
            print(f"HTML search failed for '{query}': {str(e)}")
            return []

    def check_stock(self, url, product_name=None):
        """
        Check stock status for a specific product URL.
        Returns ScrapingResult object.
        """
        try:
            html = self.fetch_page(url, timeout=15)

            if not html:
                return ScrapingResult(
                    status='UNKNOWN',
                    error='Failed to fetch product page',
                    url=url,
                    product_title=product_name
                )

            soup = BeautifulSoup(html, "html.parser")

            # Extract title
            title_elem = soup.find(["h1", "h2"], class_=re.compile("title|heading|name", re.I))
            title = title_elem.get_text(strip=True) if title_elem else product_name

            # Extract price
            price_elem = soup.find(["span", "div"], class_=re.compile("price|cost", re.I))
            price_text = price_elem.get_text(strip=True) if price_elem else None
            price = self.parse_price(price_text)

            # Determine stock status
            page_text = soup.get_text(strip=True).lower()
            raw_html_section = str(soup.find(["div", "section"], class_=re.compile("availability|stock", re.I)))

            indicators = {
                'out_of_stock_text': 'out of stock' in page_text or 'currently unavailable' in page_text,
                'add_to_cart': 'add to cart' in page_text,
                'buy_now': 'buy now' in page_text,
                'price_visible': price is not None,
                'limited_stock': 'limited' in page_text and 'stock' in page_text,
                'currently_unavailable': 'currently unavailable' in page_text,
            }

            status = self.normalize_status(indicators)

            return ScrapingResult(
                status=status,
                price=price,
                currency='AED',
                seller='Desertcart',
                product_title=title,
                url=url,
                raw_text=html[:1000]  # First 1000 chars for AI analysis
            )

        except Exception as e:
            return ScrapingResult(
                status='UNKNOWN',
                error=f'Exception: {str(e)}',
                url=url,
                product_title=product_name
            )

    def scrape_product(self, product_name):
        """
        Scrape product availability across Desertcart.
        Returns list of ScrapingResult objects.
        """
        results = []

        try:
            # Search for the product
            products = self.search(product_name)

            if not products:
                return [ScrapingResult(
                    status='UNKNOWN',
                    error='No products found',
                    product_title=product_name
                )]

            # Check stock status for each result
            for product in products:
                # Handle both dict and object responses from API
                title = product.get("title") if isinstance(product, dict) else getattr(product, "title", None)
                url = product.get("url") if isinstance(product, dict) else getattr(product, "url", None)

                # Skip if URL is missing
                if not url:
                    continue

                # For API results, extract directly
                if isinstance(product, dict) and "title" in product:
                    price = product.get("price")
                    in_stock = product.get("in_stock", True)

                    result = ScrapingResult(
                        status='IN_STOCK' if in_stock else 'OUT_OF_STOCK',
                        price=price,
                        currency='AED',
                        seller=self.STORE_NAME,
                        product_title=title,
                        url=url,
                        raw_text=product.get("raw_html", "")[:1000]
                    )
                    results.append(result)
                else:
                    # For HTML results, check the page
                    result = self.check_stock(url, title)
                    results.append(result)

            return results if results else [ScrapingResult(
                status='UNKNOWN',
                error='No valid results found',
                product_title=product_name
            )]

        except Exception as e:
            return [ScrapingResult(
                status='UNKNOWN',
                error=f'Scraping error: {str(e)}',
                product_title=product_name
            )]
