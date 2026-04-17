"""
Scraper for Ubuy UAE (ubuy.ae) - International shopping platform.
Uses search page with proxy fallback.
"""

import re
import json
from bs4 import BeautifulSoup
from scrapers.base import BaseScraper, ScrapingResult, HEADERS, PROXY_URL



# Approximate conversion rates to AED
KWD_TO_AED = 12.0   # 1 KWD ≈ 12 AED
USD_TO_AED = 3.67    # 1 USD ≈ 3.67 AED


class UbuyScraper(BaseScraper):
    """Scraper for Ubuy UAE."""

    STORE_NAME = "Ubuy"
    BASE_URL = "https://www.ubuy.ae"
    SEARCH_URL = "https://www.ubuy.ae/en/search/index/view/product/s"

    # Ubuy internal API endpoints for search
    SEARCH_API_URLS = [
        "https://www.ubuy.ae/api/products/search",
        "https://www.ubuy.ae/en/search/index/view/product/s",
    ]

    def check_stock(self, url, product_name=None):
        """
        Check stock for a NeeDoh product on Ubuy.
        Strategy: Ubuy search API (JSON) → proxy API → proxy HTML → direct HTML.
        Search pages are JS-rendered so API approach is preferred.
        """
        try:
            # For search URLs, try the API approach first (search pages are JS-rendered)
            if '/search' in url or '/s/' in url:
                query = None
                if '?q=' in url:
                    query = url.split('?q=')[1].split('&')[0]
                elif '/search/' in url:
                    query = url.split('/search/')[-1].split('?')[0]

                if query:
                    # Try direct API search
                    api_result = self._api_search(query, url, product_name)
                    if api_result and api_result.status != 'UNKNOWN':
                        return api_result

                    # Try proxy-based API search
                    proxy_result = self._proxy_api_search(query, url, product_name)
                    if proxy_result and proxy_result.status != 'UNKNOWN':
                        return proxy_result

            # For product pages or as fallback, try fetching HTML
            html = None

            # Try proxy first (Ubuy may block datacenter IPs)
            proxy_resp = self.proxy_get(url, timeout=20)
            if proxy_resp and proxy_resp.status_code == 200:
                html = proxy_resp.text

            # Fallback to direct fetch
            if not html:
                html = self.fetch_page(url, timeout=15)

            if not html:
                return ScrapingResult(
                    status='UNKNOWN',
                    error='Failed to fetch Ubuy page (all methods failed)',
                    url=url,
                    product_title=product_name
                )

            soup = BeautifulSoup(html, 'html.parser')

            # Check if this is a search results page or product page
            if '/search' in url or '/s/' in url:
                return self._parse_search_page(soup, html, url, product_name)
            elif '/product/' in url:
                return self._parse_product_page(soup, html, url, product_name)
            else:
                return self._parse_product_page(soup, html, url, product_name)

        except Exception as e:
            return ScrapingResult(
                status='UNKNOWN',
                error=f'Exception: {str(e)[:200]}',
                url=url,
                product_title=product_name
            )

    def _api_search(self, query, original_url, product_name):
        """Try Ubuy's internal search API (returns JSON, bypasses JS rendering)."""
        search_term = query.replace('+', ' ')

        for api_base in self.SEARCH_API_URLS:
            try:
                api_url = f"{api_base}?q={query}&pageSize=20&country=ae&language=en"

                response = self.session.get(api_url, timeout=15, headers={
                    'Accept': 'application/json, text/html, */*',
                    'Referer': f'https://www.ubuy.ae/en/search?q={query}',
                    'X-Requested-With': 'XMLHttpRequest',
                })

                if response.status_code != 200:
                    continue

                # Try to parse as JSON
                try:
                    data = response.json()
                except Exception:
                    continue

                products = data.get('products', data.get('items', data.get('results', [])))
                if isinstance(data, list):
                    products = data

                if not products:
                    continue

                for item in products[:10]:
                    title = item.get('title', '') or item.get('name', '') or item.get('productTitle', '')
                    if not self._is_relevant(title, product_name):
                        continue

                    price = item.get('price') or item.get('sale_price') or item.get('salePrice')
                    if isinstance(price, str):
                        price = self.parse_price(price)
                    elif price:
                        price = float(price)

                    # Convert currencies
                    currency = (item.get('currency', '') or '').upper()
                    if currency == 'KWD' and price:
                        price = round(price * KWD_TO_AED, 2)
                    elif currency == 'USD' and price:
                        price = round(price * USD_TO_AED, 2)

                    in_stock = not item.get('out_of_stock', False)
                    product_url = item.get('url', '') or item.get('productUrl', '')
                    if product_url and not product_url.startswith('http'):
                        product_url = f"{self.BASE_URL}{product_url}"

                    return ScrapingResult(
                        status='IN_STOCK' if in_stock and price else 'OUT_OF_STOCK',
                        price=price,
                        currency='AED',
                        seller='Ubuy',
                        product_title=title,
                        url=product_url or original_url,
                        raw_text=f'Ubuy API: {title}'
                    )

                # Had results but none matched
                return ScrapingResult(
                    status='OUT_OF_STOCK',
                    url=original_url,
                    product_title=product_name,
                    raw_text=f'No matching NeeDoh "{search_term}" on Ubuy API'
                )

            except Exception:
                continue

        return None  # All API attempts failed

    def _proxy_api_search(self, query, original_url, product_name):
        """Try Ubuy search API through the Cloudflare Worker proxy."""
        search_term = query.replace('+', ' ')

        for api_base in self.SEARCH_API_URLS:
            try:
                api_url = f"{api_base}?q={query}&pageSize=20&country=ae&language=en"

                response = self.proxy_get(api_url, headers={
                    'Accept': 'application/json, text/html, */*',
                    'Referer': f'https://www.ubuy.ae/en/search?q={query}',
                    'X-Requested-With': 'XMLHttpRequest',
                }, timeout=20)

                if not response or response.status_code != 200:
                    continue

                try:
                    data = response.json()
                except Exception:
                    continue

                products = data.get('products', data.get('items', data.get('results', [])))
                if isinstance(data, list):
                    products = data

                if not products:
                    continue

                for item in products[:10]:
                    title = item.get('title', '') or item.get('name', '') or item.get('productTitle', '')
                    if not self._is_relevant(title, product_name):
                        continue

                    price = item.get('price') or item.get('sale_price') or item.get('salePrice')
                    if isinstance(price, str):
                        price = self.parse_price(price)
                    elif price:
                        price = float(price)

                    currency = (item.get('currency', '') or '').upper()
                    if currency == 'KWD' and price:
                        price = round(price * KWD_TO_AED, 2)
                    elif currency == 'USD' and price:
                        price = round(price * USD_TO_AED, 2)

                    in_stock = not item.get('out_of_stock', False)
                    product_url = item.get('url', '') or item.get('productUrl', '')
                    if product_url and not product_url.startswith('http'):
                        product_url = f"{self.BASE_URL}{product_url}"

                    return ScrapingResult(
                        status='IN_STOCK' if in_stock and price else 'OUT_OF_STOCK',
                        price=price,
                        currency='AED',
                        seller='Ubuy',
                        product_title=title,
                        url=product_url or original_url,
                        raw_text=f'Ubuy proxy API: {title}'
                    )

                return ScrapingResult(
                    status='OUT_OF_STOCK',
                    url=original_url,
                    product_title=product_name,
                    raw_text=f'No matching NeeDoh "{search_term}" on Ubuy proxy API'
                )

            except Exception:
                continue

        return None

    def _parse_search_page(self, soup, html, url, product_name):
        """Parse Ubuy search results page."""
        page_text = soup.get_text(' ', strip=True).lower()

        # Check for no results
        if 'did not match any product' in page_text or 'no results' in page_text:
            return ScrapingResult(
                status='OUT_OF_STOCK',
                url=url,
                product_title=product_name,
                raw_text='No products found on Ubuy search'
            )

        # Look for product containers (Ubuy uses various layouts)
        products = soup.find_all('div', class_=re.compile(r'product-card|product-item|prd-card', re.I))
        if not products:
            products = soup.find_all('div', class_=re.compile(r'product', re.I))

        for item in products[:10]:
            item_text = item.get_text(' ', strip=True)

            # Check relevance
            if not self._is_relevant(item_text, product_name):
                continue

            # Extract title
            title_elem = item.find('h3') or item.find('h2') or item.find('a', class_=re.compile(r'title|name', re.I))
            if not title_elem:
                title_elem = item.find('a', href=True)
            title = title_elem.get_text(strip=True) if title_elem else product_name

            # Extract price (Ubuy shows prices in AED or sometimes KWD/USD)
            price = self._extract_price(item)

            # Extract URL
            link = item.find('a', href=True)
            product_url = link['href'] if link else url
            if product_url and not product_url.startswith('http'):
                product_url = f"{self.BASE_URL}{product_url}"

            # Check stock
            item_lower = item_text.lower()
            out_of_stock = 'out of stock' in item_lower or 'unavailable' in item_lower

            return ScrapingResult(
                status='OUT_OF_STOCK' if out_of_stock else ('IN_STOCK' if price else 'UNKNOWN'),
                price=price,
                currency='AED',
                seller='Ubuy',
                product_title=title,
                url=product_url,
                raw_text=item_text[:500]
            )

        # No matching product
        return ScrapingResult(
            status='OUT_OF_STOCK',
            url=url,
            product_title=product_name,
            raw_text='No matching NeeDoh product found in Ubuy search'
        )

    def _extract_delivery(self, soup, page_text):
        """Extract delivery estimate from Ubuy product page."""
        # Look for delivery-related text
        delivery_patterns = [
            r'(?:estimated delivery|delivery by|arrives?|ships? in|delivered? by)\s*[:\-]?\s*(.{5,60}?)(?:\.|<|$)',
            r'(?:get it by|expected delivery)\s*[:\-]?\s*(.{5,60}?)(?:\.|<|$)',
            r'(\d+\s*-\s*\d+\s*(?:business\s*)?days?)',
            r'(free shipping.*?(?:\d+\s*days?|tomorrow|today))',
        ]
        for pattern in delivery_patterns:
            match = re.search(pattern, page_text, re.I)
            if match:
                return match.group(1).strip()[:80]

        # Check for delivery elements
        delivery_elem = soup.find(['div', 'span', 'p'], class_=re.compile(r'delivery|shipping|dispatch', re.I))
        if delivery_elem:
            text = delivery_elem.get_text(strip=True)
            if len(text) < 100:
                return text

        return None

    def _parse_product_page(self, soup, html, url, product_name):
        """Parse a single Ubuy product page."""
        page_text = soup.get_text(' ', strip=True).lower()

        # Extract title from h1
        title_elem = soup.find('h1')
        title = title_elem.get_text(strip=True) if title_elem else product_name

        # Extract price
        price = self._extract_price(soup)

        # Extract delivery estimate
        delivery_estimate = self._extract_delivery(soup, page_text)

        # Try JSON-LD structured data
        ld_scripts = soup.find_all('script', type='application/ld+json')
        for script in ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Product':
                    offers = data.get('offers', {})
                    if isinstance(offers, list):
                        offers = offers[0] if offers else {}
                    if isinstance(offers, dict):
                        if not price and offers.get('price'):
                            price = float(offers['price'])
                        avail = offers.get('availability', '')
                        if 'InStock' in avail:
                            return ScrapingResult(
                                status='IN_STOCK',
                                price=price,
                                currency='AED',
                                seller='Ubuy',
                                product_title=title,
                                url=url,
                                raw_text=page_text[:500],
                                delivery_estimate=delivery_estimate
                            )
                        elif 'OutOfStock' in avail:
                            return ScrapingResult(
                                status='OUT_OF_STOCK',
                                price=price,
                                currency='AED',
                                seller='Ubuy',
                                product_title=title,
                                url=url,
                                raw_text=page_text[:500],
                                delivery_estimate=delivery_estimate
                            )
            except (json.JSONDecodeError, ValueError, TypeError):
                continue

        # Check stock indicators from page text
        indicators = {
            'out_of_stock_text': 'out of stock' in page_text,
            'add_to_cart': 'add to cart' in page_text,
            'buy_now': 'buy now' in page_text,
            'price_visible': price is not None,
            'currently_unavailable': 'currently unavailable' in page_text or 'not available' in page_text,
        }

        status = self.normalize_status(indicators)

        return ScrapingResult(
            status=status,
            price=price,
            currency='AED',
            seller='Ubuy',
            product_title=title,
            url=url,
            raw_text=page_text[:500],
            delivery_estimate=delivery_estimate
        )

    def _extract_price(self, soup_or_elem):
        """Extract price from a page element, converting KWD/USD to AED."""
        all_text = soup_or_elem.get_text(' ', strip=True)

        # Try AED first (native UAE price)
        aed_patterns = [
            r'AED\s*(\d+(?:\.\d+)?)',
            r'(\d+(?:\.\d+)?)\s*AED',
        ]
        for pattern in aed_patterns:
            match = re.search(pattern, all_text, re.I)
            if match:
                try:
                    price = float(match.group(1))
                    if 1 < price < 5000:
                        return price
                except ValueError:
                    continue

        # Try KWD (Ubuy proxy sometimes returns KWD prices) → convert to AED
        kwd_patterns = [
            r'KWD\s*(\d+(?:\.\d+)?)',
            r'(\d+(?:\.\d+)?)\s*KWD',
        ]
        for pattern in kwd_patterns:
            match = re.search(pattern, all_text, re.I)
            if match:
                try:
                    kwd_price = float(match.group(1))
                    if 1 < kwd_price < 500:
                        aed_price = round(kwd_price * KWD_TO_AED, 2)
                        return aed_price
                except ValueError:
                    continue

        # Try USD → convert to AED
        usd_patterns = [
            r'USD\s*(\d+(?:\.\d+)?)',
            r'\$\s*(\d+(?:\.\d+)?)',
            r'(\d+(?:\.\d+)?)\s*USD',
        ]
        for pattern in usd_patterns:
            match = re.search(pattern, all_text, re.I)
            if match:
                try:
                    usd_price = float(match.group(1))
                    if 1 < usd_price < 1000:
                        aed_price = round(usd_price * USD_TO_AED, 2)
                        return aed_price
                except ValueError:
                    continue

        # Try price elements with CSS classes
        price_elems = soup_or_elem.find_all(['span', 'div', 'h2', 'p'], class_=re.compile(r'price|cost', re.I))
        for elem in price_elems:
            text = elem.get_text(strip=True)
            price = self.parse_price(text)
            if price:
                return price

        return None

    def _is_relevant(self, text, product_name):
        """Check if text is relevant to the NeeDoh product."""
        if not text or not product_name:
            return True

        text_lower = text.lower()

        # Must mention needoh or nee doh or schylling
        if 'needoh' not in text_lower and 'nee doh' not in text_lower and 'nee-doh' not in text_lower and 'schylling' not in text_lower:
            return False

        return True
