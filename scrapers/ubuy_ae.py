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

    # Real Ubuy search API (returns HTML with product cards)
    SEARCH_API_URL = "https://www.ubuy.ae/en/ubcommon/esglobal-v2/search/products"

    def check_stock(self, url, product_name=None):
        """
        Check stock for a NeeDoh product on Ubuy.
        Strategy for search URLs: two-step approach —
          1. Fetch search page via proxy to get session CSRF token
          2. Call the real search API with that token to get product HTML
        For product pages: direct/proxy HTML fetch.
        """
        try:
            # For search URLs, use the two-step API approach
            if '/search' in url or '/s/' in url:
                query = None
                if '?q=' in url:
                    query = url.split('?q=')[1].split('&')[0].replace('+', ' ')
                elif '/search/' in url:
                    query = url.split('/search/')[-1].split('?')[0].replace('+', ' ')

                if query:
                    # Two-step approach: get CSRF from page, then call real API
                    api_result = self._two_step_api_search(query, url, product_name)
                    if api_result and api_result.status != 'UNKNOWN':
                        return api_result

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

    def _two_step_api_search(self, query, original_url, product_name):
        """Two-step Ubuy search: fetch page for CSRF token, then call real API.
        Ubuy search pages are 100% JS-rendered, but the actual API returns
        server-rendered HTML with product cards when given a valid CSRF token.
        """
        import base64

        try:
            # Step 1: Fetch the search page via proxy to get session CSRF token
            search_page_url = f"https://www.ubuy.ae/en/search?q={query.replace(' ', '+')}"
            page_html = None

            proxy_resp = self.proxy_get(search_page_url, timeout=25)
            if proxy_resp and proxy_resp.status_code == 200 and len(proxy_resp.text) > 5000:
                page_html = proxy_resp.text

            if not page_html:
                page_html = self.fetch_page(search_page_url, timeout=20)

            if not page_html or len(page_html) < 5000:
                return None

            # Extract CSRF token from page
            csrf_match = re.findall(r'csrftoken_search\s*=\s*["\']([^"\']+)["\']', page_html)
            csrf = csrf_match[0] if csrf_match else ""
            if not csrf:
                return None

            # Extract store variable
            store_match = re.findall(r'(?:var|let)\s+ubuy_store\s*=\s*["\']([^"\']+)["\']', page_html)
            store = store_match[0] if store_match else "us"

            # Step 2: Build and call the real search API
            req_data = {
                "q": query,
                "ctx": query,
                "page": "1",
                "brand": "",
                "ufulfilled": "",
                "price_range": "",
                "sort_by": "",
                "lang": "",
                "dc": "",
                "search_type": "",
                "skus": "",
                "store": store,
                "csrf_token": csrf,
                "is_video": ""
            }
            req_b64 = base64.b64encode(json.dumps(req_data).encode()).decode()
            api_url = f"{self.SEARCH_API_URL}?ubuy=es1&req={req_b64}"

            # Call API via proxy (with proper headers)
            api_resp = self.proxy_get(api_url, headers={
                'Accept': 'text/html, */*',
                'Referer': search_page_url,
                'X-Requested-With': 'XMLHttpRequest',
            }, timeout=25)

            if not api_resp or api_resp.status_code != 200 or len(api_resp.text) < 100:
                return None

            api_html = api_resp.text

            # Parse the product cards from API response HTML
            return self._parse_api_html(api_html, original_url, product_name, query)

        except Exception as e:
            print(f"  Ubuy two-step API failed: {e}")
            return None

    def _parse_api_html(self, api_html, original_url, product_name, query):
        """Parse the HTML response from Ubuy's internal search API.
        The API returns server-rendered product card HTML.
        """
        soup = BeautifulSoup(api_html, 'html.parser')

        # Find product titles
        title_elems = soup.find_all(['h3', 'a'], class_=re.compile(r'product-title', re.I))
        if not title_elems:
            title_elems = soup.find_all('h3')

        # Also find price elements
        price_elems = soup.find_all(['span', 'div', 'h3', 'p'], class_=re.compile(r'price|cost', re.I))

        # Find all listing-product containers for structured parsing
        product_divs = soup.find_all('div', class_=re.compile(r'listing-product', re.I))

        for div in product_divs[:15]:
            div_text = div.get_text(' ', strip=True)

            # Check relevance
            if not self._is_relevant(div_text, product_name):
                continue

            # Extract title
            title_el = div.find(['h3', 'a'], class_=re.compile(r'product-title', re.I))
            if not title_el:
                title_el = div.find('h3')
            title = title_el.get_text(strip=True) if title_el else product_name

            # Extract price
            price = self._extract_price(div)

            # Extract product URL
            link = div.find('a', href=True)
            product_url = link['href'] if link else original_url
            if product_url and not product_url.startswith('http'):
                product_url = f"{self.BASE_URL}{product_url}"

            # Check for out of stock indicators
            div_lower = div_text.lower()
            out_of_stock = 'out of stock' in div_lower or 'unavailable' in div_lower

            return ScrapingResult(
                status='OUT_OF_STOCK' if out_of_stock else ('IN_STOCK' if price else 'UNKNOWN'),
                price=price,
                currency='AED',
                seller='Ubuy',
                product_title=title,
                url=product_url,
                raw_text=f'Ubuy API: {div_text[:300]}'
            )

        # Had API response but no matching NeeDoh product
        return ScrapingResult(
            status='OUT_OF_STOCK',
            url=original_url,
            product_title=product_name,
            raw_text=f'No matching NeeDoh "{query}" on Ubuy'
        )

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
