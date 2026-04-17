"""
Noon UAE scraper for NeeDoh products.
Uses Noon's mobile catalog API as the primary method (most reliable),
with proxy fallback when Render's datacenter IP is blocked.
"""

import re
import json
import time
import random
import requests
import cloudscraper
from scrapers.base import BaseScraper, ScrapingResult, PROXY_URL


class NoonScraper(BaseScraper):
    STORE_NAME = "Noon"

    # Mobile API headers — these bypass Noon's web anti-bot protection
    MOBILE_HEADERS = {
        'User-Agent': 'NoonApp/5.0.0 (Android 13; SM-S908B)',
        'Accept': 'application/json',
        'Accept-Language': 'en-AE',
        'Accept-Encoding': 'gzip, deflate',
        'X-Locale': 'en-ae',
        'X-Platform': 'android',
        'X-Content': 'V4',
        'Connection': 'keep-alive',
    }

    # Web API headers — lighter than mobile, works from datacenter IPs
    WEB_API_HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-AE,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate',
        'Referer': 'https://www.noon.com/',
        'Origin': 'https://www.noon.com',
        'Connection': 'keep-alive',
    }

    def __init__(self):
        super().__init__()
        self.api_base = "https://www.noon.com/_svc/catalog/api/v3/u/"
        # Dedicated cloudscraper session for Noon API calls
        self._cs = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False}
        )

    def check_stock(self, url, product_name=None):
        """Check stock on Noon UAE.
        Strategy: direct mobile API → direct web API → proxy mobile API → UNKNOWN
        """
        if 'search' in url or 'q=' in url:
            # Try mobile API first (most data, fastest)
            result = self._mobile_api_search(url, product_name)
            if result and result.status != 'UNKNOWN':
                return result

            # Try web API as fallback
            result = self._web_api_search(url, product_name)
            if result and result.status != 'UNKNOWN':
                return result

            # Try through proxy (different IP, bypasses Render blocking)
            result = self._proxy_api_search(url, product_name)
            if result and result.status != 'UNKNOWN':
                return result

            # Try HTML page with __NEXT_DATA__ parsing (last resort)
            result = self._html_search(url, product_name)
            if result and result.status != 'UNKNOWN':
                return result

            # Try proxy HTML page (different IP + HTML parsing)
            result = self._proxy_html_search(url, product_name)
            if result and result.status != 'UNKNOWN':
                return result

            # All methods failed
            return ScrapingResult(
                status='UNKNOWN',
                error='Noon not reachable from any method (API+proxy+HTML all failed)',
                url=url
            )

        # For non-search URLs, try product page
        if '/search' not in url:
            return self._check_product_page(url, product_name)

        return ScrapingResult(
            status='UNKNOWN',
            error='Noon API unreachable',
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

            # Try with cloudscraper — give it a real chance to respond
            response = self._cs.get(
                api_url,
                headers=self.MOBILE_HEADERS,
                timeout=20
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

                # Extract delivery estimate from Noon API data
                delivery_estimate = None
                delivery_text = hit.get('delivery_text', '') or hit.get('express_delivery_text', '')
                if delivery_text:
                    delivery_estimate = delivery_text
                elif hit.get('is_express_delivery'):
                    delivery_estimate = 'Express delivery available'
                elif hit.get('delivery_days'):
                    delivery_estimate = f"Delivers in {hit['delivery_days']} days"

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
                    url=product_url or url,  # Use specific product URL when available
                    delivery_estimate=delivery_estimate
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
                error='Noon mobile API timed out',
                url=url
            )
        except Exception as e:
            return None

    def _web_api_search(self, url, product_name):
        """Fallback: Use Noon's web catalog API with browser-like headers."""
        try:
            query = re.search(r'[?&]q=([^&]+)', url)
            if not query:
                if product_name:
                    search_term = product_name.replace(' ', '+')
                else:
                    return None
            else:
                search_term = query.group(1)

            # Try the web API endpoint (different from mobile)
            api_url = f"https://www.noon.com/_svc/catalog/api/v3/u/search/?q={search_term}&locale=en-ae&limit=20"

            response = self._cs.get(
                api_url,
                headers=self.WEB_API_HEADERS,
                timeout=20
            )

            if response.status_code != 200:
                return None

            data = response.json()
            hits = data.get('hits', [])
            display_term = search_term.replace('+', ' ')

            if not hits:
                return ScrapingResult(
                    status='OUT_OF_STOCK',
                    raw_text=f'No results for "{display_term}" on Noon (web API)',
                    url=url
                )

            # Find best match (same logic as mobile)
            for hit in hits[:10]:
                title = hit.get('name', '') or hit.get('title', '')
                if not self._is_relevant(title, product_name or display_term):
                    continue

                price = hit.get('sale_price') or hit.get('price')
                offer_price = hit.get('offer_price')
                actual_price = offer_price or price
                is_buyable = hit.get('is_buyable', False)

                status = 'IN_STOCK' if is_buyable else 'OUT_OF_STOCK'
                stock_text = hit.get('stock_text', '')
                if stock_text and ('few left' in stock_text.lower() or 'limited' in stock_text.lower()):
                    status = 'LOW_STOCK'

                product_url = hit.get('url', '')
                if product_url and not product_url.startswith('http'):
                    product_url = f"https://www.noon.com/uae-en/{product_url}"

                delivery_estimate = None
                delivery_text = hit.get('delivery_text', '') or hit.get('express_delivery_text', '')
                if delivery_text:
                    delivery_estimate = delivery_text

                return ScrapingResult(
                    status=status,
                    price=float(actual_price) if actual_price else None,
                    product_title=title,
                    seller=hit.get('seller_name'),
                    raw_text=json.dumps({'title': title, 'price': actual_price, 'source': 'web_api'}),
                    url=product_url or url,
                    delivery_estimate=delivery_estimate
                )

            return ScrapingResult(
                status='OUT_OF_STOCK',
                raw_text=f'No matching "{display_term}" on Noon (web API)',
                url=url
            )

        except requests.Timeout:
            return None
        except Exception:
            return None

    def _html_search(self, url, product_name):
        """Last resort: scrape the HTML search results page directly."""
        try:
            from bs4 import BeautifulSoup

            response = self._cs.get(
                url,
                headers=self.WEB_API_HEADERS,
                timeout=10
            )

            if response.status_code != 200:
                return None

            html = response.text
            soup = BeautifulSoup(html, 'html.parser')

            # Check for __NEXT_DATA__ JSON (Next.js apps embed data in a script tag)
            next_data = soup.find('script', id='__NEXT_DATA__')
            if next_data:
                try:
                    data = json.loads(next_data.string)
                    page_props = data.get('props', {}).get('pageProps', {})
                    catalog = page_props.get('catalog', {}) or page_props.get('searchResult', {})
                    hits = catalog.get('hits', []) or catalog.get('products', [])

                    if hits:
                        for hit in hits[:10]:
                            title = hit.get('name', '') or hit.get('title', '')
                            if product_name and not self._is_relevant(title, product_name):
                                continue
                            price = hit.get('sale_price') or hit.get('price')
                            is_buyable = hit.get('is_buyable', True)

                            return ScrapingResult(
                                status='IN_STOCK' if is_buyable and price else 'OUT_OF_STOCK',
                                price=float(price) if price else None,
                                product_title=title,
                                seller=hit.get('seller_name'),
                                raw_text=f'Noon HTML/NEXT_DATA: {title}',
                                url=url
                            )
                except (json.JSONDecodeError, KeyError):
                    pass

            # Fallback: check page text for stock indicators
            page_text = soup.get_text(' ', strip=True).lower()
            if 'no results' in page_text or '0 results' in page_text:
                return ScrapingResult(
                    status='OUT_OF_STOCK',
                    raw_text='No results found on Noon HTML page',
                    url=url
                )

            return None  # Could not determine from HTML

        except Exception:
            return None

    def _proxy_html_search(self, url, product_name):
        """Use the Cloudflare Worker proxy to fetch Noon's HTML search page,
        then parse __NEXT_DATA__ embedded JSON for product data."""
        if not PROXY_URL:
            return None

        try:
            from bs4 import BeautifulSoup

            # Fetch the HTML page through the proxy
            response = self.proxy_get(url, headers=self.WEB_API_HEADERS, timeout=25)
            if not response or response.status_code != 200:
                return None

            html = response.text
            if not html or len(html) < 500:
                return None

            soup = BeautifulSoup(html, 'html.parser')

            # Look for __NEXT_DATA__ which contains search results as embedded JSON
            next_data = soup.find('script', id='__NEXT_DATA__')
            if next_data:
                try:
                    data = json.loads(next_data.string)
                    page_props = data.get('props', {}).get('pageProps', {})
                    catalog = page_props.get('catalog', {}) or page_props.get('searchResult', {})
                    hits = catalog.get('hits', []) or catalog.get('products', [])

                    if hits:
                        for hit in hits[:10]:
                            title = hit.get('name', '') or hit.get('title', '')
                            if product_name and not self._is_relevant(title, product_name):
                                continue
                            price = hit.get('sale_price') or hit.get('price')
                            is_buyable = hit.get('is_buyable', True)

                            product_url = hit.get('url', '')
                            if product_url and not product_url.startswith('http'):
                                product_url = f"https://www.noon.com/uae-en/{product_url}"

                            delivery_estimate = None
                            delivery_text = hit.get('delivery_text', '') or hit.get('express_delivery_text', '')
                            if delivery_text:
                                delivery_estimate = delivery_text

                            return ScrapingResult(
                                status='IN_STOCK' if is_buyable and price else 'OUT_OF_STOCK',
                                price=float(price) if price else None,
                                product_title=title,
                                seller=hit.get('seller_name'),
                                raw_text=f'Noon proxy HTML/NEXT_DATA: {title}',
                                url=product_url or url,
                                delivery_estimate=delivery_estimate
                            )

                        # Had hits but none matched
                        return ScrapingResult(
                            status='OUT_OF_STOCK',
                            raw_text=f'No matching product on Noon (proxy HTML)',
                            url=url
                        )
                except (json.JSONDecodeError, KeyError):
                    pass

            # Check page text for stock signals
            page_text = soup.get_text(' ', strip=True).lower()
            if 'no results' in page_text or '0 results' in page_text:
                return ScrapingResult(
                    status='OUT_OF_STOCK',
                    raw_text='No results on Noon (proxy HTML)',
                    url=url
                )

            return None

        except Exception as e:
            print(f"  Noon proxy HTML search failed: {e}")
            return None

    def _proxy_api_search(self, url, product_name):
        """Use the Cloudflare Worker proxy to reach Noon's mobile API.
        This bypasses Render's datacenter IP being blocked by Noon.
        """
        if not PROXY_URL:
            return None

        try:
            query = re.search(r'[?&]q=([^&]+)', url)
            if not query:
                if product_name:
                    search_term = product_name.replace(' ', '+')
                else:
                    return None
            else:
                search_term = query.group(1)

            api_url = f"{self.api_base}search/?q={search_term}&locale=en-ae"

            # Route through proxy with mobile headers
            response = self.proxy_get(api_url, headers=self.MOBILE_HEADERS, timeout=25)
            if not response or response.status_code != 200:
                return None

            data = response.json()
            hits = data.get('hits', [])
            display_term = search_term.replace('+', ' ')

            if not hits:
                return ScrapingResult(
                    status='OUT_OF_STOCK',
                    raw_text=f'No results for "{display_term}" on Noon (via proxy)',
                    url=url
                )

            # Find best match (same logic as mobile API)
            for hit in hits[:10]:
                title = hit.get('name', '') or hit.get('title', '')
                if not self._is_relevant(title, product_name or display_term):
                    continue

                price = hit.get('sale_price') or hit.get('price')
                offer_price = hit.get('offer_price')
                actual_price = offer_price or price
                is_buyable = hit.get('is_buyable', False)
                stock_text = hit.get('stock_text', '')

                status = 'IN_STOCK' if is_buyable else 'OUT_OF_STOCK'
                if stock_text and ('few left' in stock_text.lower() or 'limited' in stock_text.lower()):
                    status = 'LOW_STOCK'

                product_url = hit.get('url', '')
                if product_url and not product_url.startswith('http'):
                    product_url = f"https://www.noon.com/uae-en/{product_url}"

                delivery_estimate = None
                delivery_text = hit.get('delivery_text', '') or hit.get('express_delivery_text', '')
                if delivery_text:
                    delivery_estimate = delivery_text

                return ScrapingResult(
                    status=status,
                    price=float(actual_price) if actual_price else None,
                    product_title=title,
                    seller=hit.get('seller_name'),
                    raw_text=json.dumps({
                        'title': title,
                        'price': actual_price,
                        'is_buyable': is_buyable,
                        'source': 'proxy',
                    }),
                    url=product_url or url,
                    delivery_estimate=delivery_estimate
                )

            return ScrapingResult(
                status='OUT_OF_STOCK',
                raw_text=f'No matching "{display_term}" on Noon (via proxy)',
                url=url
            )

        except Exception as e:
            print(f"  Noon proxy search failed: {e}")
            return None

    def _check_product_page(self, url, product_name):
        """Check a specific Noon product page (non-search URL)."""
        # For product pages, try to extract the SKU and use the API
        sku_match = re.search(r'/([A-Z0-9]+)/p/', url)
        if sku_match:
            sku = sku_match.group(1)
            try:
                api_url = f"{self.api_base}product/{sku}?locale=en-ae"
                response = self._cs.get(api_url, headers=self.MOBILE_HEADERS, timeout=12)
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

    def _is_needoh_brand(self, title):
        """Check if a product is genuinely a NeeDoh/Schylling brand item."""
        if not title:
            return False
        t = title.lower()
        return ('needoh' in t or 'nee doh' in t or 'nee-doh' in t
                or 'schylling' in t or 'nee doh' in t.replace('-', ' '))

    def _is_relevant(self, title, query):
        """Check if a result is relevant to the specific product we're looking for.
        Must be NeeDoh brand AND match the distinctive keyword."""
        if not title or not query:
            return False  # Require explicit match
        title_lower = title.lower()
        query_lower = query.lower()

        # MUST be NeeDoh/Schylling brand
        if not self._is_needoh_brand(title):
            return False

        # Remove common generic words to find the distinctive keywords
        generic = {'needoh', 'nee', 'doh', 'schylling', 'stress', 'ball', 'toy', 'fidget', 'sensory'}
        keywords = [w for w in query_lower.split() if len(w) > 2 and w not in generic]

        if not keywords:
            # Product name is only generic words (e.g. "NeeDoh Blob")
            return True  # Brand check already passed above

        # ALL distinctive keywords must appear in the title
        matches = sum(1 for kw in keywords if kw in title_lower)
        return matches >= len(keywords) * 0.8
