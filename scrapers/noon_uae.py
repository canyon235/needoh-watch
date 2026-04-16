"""
Noon UAE scraper for NeeDoh products.
Uses Noon's mobile catalog API as the primary method (most reliable),
with HTML scraping as fallback.
"""

import re
import json
import time
import random
import requests
from scrapers.base import BaseScraper, ScrapingResult


class NoonScraper(BaseScraper):
    STORE_NAME = "Noon"

    # Mobile API headers — these bypass Noon's web anti-bot protection
    MOBILE_HEADERS = {
        'User-Agent': 'NoonApp/5.0.0 (Android 13; SM-S908B)',
        'Accept': 'application/json',
        'Accept-Language': 'en-AE',
        'Accept-Encoding': 'gzip, deflate',  # No brotli — requests can't decode it
        'X-Locale': 'en-ae',
        'X-Platform': 'android',
        'X-Content': 'V4',
        'Connection': 'keep-alive',
    }

    def __init__(self):
        super().__init__()
        self.api_base = "https://www.noon.com/_svc/catalog/api/v3/u/"

    def check_stock(self, url, product_name=None):
        """Check stock on Noon UAE. Uses mobile API first (most reliable)."""

        # Always try mobile API first for search queries
        if 'search' in url or 'q=' in url:
            result = self._mobile_api_search(url, product_name)
            if result and result.status != 'UNKNOWN':
                return result

        # If API fails, try direct product page (for non-search URLs)
        if '/search' not in url:
            return self._check_product_page(url, product_name)

        # Last resort: return UNKNOWN with helpful error
        return ScrapingResult(
            status='UNKNOWN',
            error='Noon API temporarily unavailable',
            url=url
        )

    def _mobile_api_search(self, url, product_name):
        """
        Use Noon's mobile app API — this is the most reliable method.
        The mobile API doesn't have the same anti-bot restrictions as the web.
        """
        try:
            # Extract query from URL
            query = re.search(r'[?&]q=([^&]+)', url)
            if not query:
                # If no query param, try to build from product name
                if product_name:
                    search_term = product_name.replace(' ', '+')
                else:
                    return None
            else:
                search_term = query.group(1)  # Keep URL-encoded (with + signs)

            # Build API URL — use the raw search term (with + for spaces)
            api_url = f"{self.api_base}search/?q={search_term}&locale=en-ae"

            # Use a fresh session with mobile headers to avoid interference
            response = requests.get(
                api_url,
                headers=self.MOBILE_HEADERS,
                timeout=12
            )

            if response.status_code != 200:
                return None

            data = response.json()
            hits = data.get('hits', [])

            # Decode search term for display and matching
            display_term = search_term.replace('+', ' ')

            if not hits:
                return ScrapingResult(
                    status='OUT_OF_STOCK',
                    raw_text=f'No results for "{display_term}" on Noon',
                    url=url
                )

            # Find best match
            for hit in hits[:10]:
                title = hit.get('name', '') or hit.get('title', '')
                if not self._is_relevant(title, product_name or display_term):
                    continue

                # Extract pricing
                price = hit.get('sale_price') or hit.get('price')
                offer_price = hit.get('offer_price')
                actual_price = offer_price or price

                # Stock status
                is_buyable = hit.get('is_buyable', False)
                stock_text = hit.get('stock_text', '')

                status = 'IN_STOCK' if is_buyable else 'OUT_OF_STOCK'
                if stock_text and ('few left' in stock_text.lower() or 'limited' in stock_text.lower()):
                    status = 'LOW_STOCK'

                # Build product URL for buy link
                product_url = hit.get('url', '')
                if product_url and not product_url.startswith('http'):
                    product_url = f"https://www.noon.com/uae-en/{product_url}"

                return ScrapingResult(
                    status=status,
                    price=float(actual_price) if actual_price else None,
                    product_title=title,
                    seller=hit.get('seller_name'),
                    raw_text=json.dumps({
                        'title': title,
                        'price': actual_price,
                        'is_buyable': is_buyable,
                        'stock_text': stock_text,
                    }),
                    url=product_url or url  # Use specific product URL when available
                )

            # Had results but none matched the product name — report as OUT_OF_STOCK
            # Do NOT use unrelated results (causes false availability)
            return ScrapingResult(
                status='OUT_OF_STOCK',
                raw_text=f'No matching "{display_term}" found in Noon search results',
                url=url
            )

        except requests.Timeout:
            return ScrapingResult(
                status='UNKNOWN',
                error='Noon API timed out',
                url=url
            )
        except Exception as e:
            return None

    def _check_product_page(self, url, product_name):
        """Check a specific Noon product page (non-search URL)."""
        # For product pages, try to extract the SKU and use the API
        sku_match = re.search(r'/([A-Z0-9]+)/p/', url)
        if sku_match:
            sku = sku_match.group(1)
            try:
                api_url = f"{self.api_base}product/{sku}?locale=en-ae"
                response = requests.get(api_url, headers=self.MOBILE_HEADERS, timeout=12)
                if response.status_code == 200:
                    data = response.json()
                    product = data.get('product', data)

                    title = product.get('name', '') or product.get('title', '')
                    price = product.get('sale_price') or product.get('price')
                    is_buyable = product.get('is_buyable', False)

                    return ScrapingResult(
                        status='IN_STOCK' if is_buyable else 'OUT_OF_STOCK',
                        price=float(price) if price else None,
                        product_title=title,
                        seller=product.get('seller_name'),
                        raw_text=json.dumps(product)[:500],
                        url=url
                    )
            except Exception:
                pass

        return ScrapingResult(
            status='UNKNOWN',
            error='Could not check Noon product page',
            url=url
        )

    def _is_relevant(self, title, query):
        """Check if a result is relevant to the specific product we're looking for.
        Must match the distinctive keyword (not just 'needoh')."""
        if not title or not query:
            return False  # Require explicit match
        title_lower = title.lower()
        query_lower = query.lower()

        # Remove common generic words to find the distinctive keywords
        generic = {'needoh', 'nee', 'doh', 'schylling', 'stress', 'ball', 'toy', 'fidget', 'sensory'}
        keywords = [w for w in query_lower.split() if len(w) > 2 and w not in generic]

        if not keywords:
            # Product name is only generic words (e.g. "NeeDoh Blob")
            return 'needoh' in title_lower or ('nee' in title_lower and 'doh' in title_lower)

        # ALL distinctive keywords must appear in the title
        matches = sum(1 for kw in keywords if kw in title_lower)
        return matches >= len(keywords) * 0.8
