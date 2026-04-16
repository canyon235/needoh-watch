"""
Scraper for Trendyol (trendyol.com) - Turkish e-commerce platform.
Handles Cloudflare protection with proxy fallback for blocked IPs.
"""

import re
from bs4 import BeautifulSoup
from scrapers.base import BaseScraper, ScrapingResult, HEADERS, PROXY_URL

# Approximate conversion rate: 1 TL = 0.12 AED
TL_TO_AED = 0.12


class TrendyolScraper(BaseScraper):
    """Scraper for Trendyol with Cloudflare bypass attempts."""

    STORE_NAME = "Trendyol"

    def __init__(self):
        super().__init__()
        # Enhanced headers to work around Cloudflare
        self.session.headers.update({
            "Referer": "https://www.trendyol.com/",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        })

    def check_stock(self, url, product_name=None):
        """
        Check stock for a product on Trendyol.
        Attempts direct HTTP request first, falls back to UNKNOWN if blocked.
        """
        if not url:
            return ScrapingResult(
                status='UNKNOWN',
                error='No URL provided',
                store_availability={'Trendyol': 'UNKNOWN'}
            )

        try:
            # Attempt direct fetch first
            html = self.fetch_page(url, timeout=15)

            # If direct fails, try through proxy (Trendyol blocks datacenter IPs)
            if html is None:
                proxy_resp = self.proxy_get(url, timeout=20)
                if proxy_resp and proxy_resp.status_code == 200:
                    html = proxy_resp.text

            if html is None:
                return ScrapingResult(
                    status='UNKNOWN',
                    error='Failed to fetch page (blocked by Cloudflare)',
                    url=url,
                    store_availability={'Trendyol': 'UNKNOWN'}
                )

            # Check for Cloudflare blocks
            if 'cloudflare' in html.lower() or 'error 403' in html.lower():
                return ScrapingResult(
                    status='UNKNOWN',
                    error='Cloudflare protection detected - Playwright needed for JavaScript rendering',
                    url=url,
                    store_availability={'Trendyol': 'UNKNOWN'},
                    raw_text=html[:300]
                )

            # Try to parse the page
            result = self._parse_product_page(html, url, product_name)
            return result

        except Exception as e:
            return ScrapingResult(
                status='UNKNOWN',
                error=f'Exception during scraping: {str(e)}',
                url=url,
                store_availability={'Trendyol': 'UNKNOWN'}
            )

    def search_products(self, query):
        """
        Search for products on Trendyol.
        Returns list of ScrapingResult objects for matching products.
        """
        search_url = f"https://www.trendyol.com/sr?q={query}"

        try:
            html = self.fetch_page(search_url, timeout=15)

            # If direct fails or blocked, try proxy
            if html is None or 'cloudflare' in (html or '').lower():
                proxy_resp = self.proxy_get(search_url, timeout=20)
                if proxy_resp and proxy_resp.status_code == 200:
                    html = proxy_resp.text

            if html is None:
                return [ScrapingResult(
                    status='UNKNOWN',
                    error='Failed to fetch search results',
                    url=search_url,
                    store_availability={'Trendyol': 'UNKNOWN'}
                )]

            # Check for Cloudflare blocks (even after proxy)
            if 'cloudflare' in html.lower() or 'error 403' in html.lower():
                return [ScrapingResult(
                    status='UNKNOWN',
                    error='Cloudflare protection - IP blocked',
                    url=search_url,
                    store_availability={'Trendyol': 'UNKNOWN'}
                )]

            results = self._parse_search_results(html, search_url, query)
            return results

        except Exception as e:
            return [ScrapingResult(
                status='UNKNOWN',
                error=f'Search exception: {str(e)}',
                url=search_url,
                store_availability={'Trendyol': 'UNKNOWN'}
            )]

    def _parse_product_page(self, html, url, product_name=None):
        """Parse a single product page and extract stock/price info."""
        soup = BeautifulSoup(html, 'html.parser')

        # Try to extract product title
        title = product_name
        if not title:
            title_tag = soup.find('h1') or soup.find('span', class_=re.compile('product.*title'))
            if title_tag:
                title = title_tag.get_text(strip=True)

        # Look for price information
        price = None
        currency = 'TL'  # Default to Turkish Lira

        # Try common price patterns
        price_patterns = [
            ('span', re.compile(r'price|fiyat', re.I)),
            ('div', re.compile(r'price|fiyat', re.I)),
            ('p', re.compile(r'price|fiyat', re.I)),
        ]

        for tag_name, class_pattern in price_patterns:
            price_elem = soup.find(tag_name, class_=class_pattern)
            if price_elem:
                price_text = price_elem.get_text(strip=True)
                price = self._parse_trendyol_price(price_text)
                if price:
                    break

        # Check stock indicators
        indicators = self._check_stock_indicators(soup, html)

        # Determine status
        status = self.normalize_status(indicators)

        # Convert TL to AED if needed
        final_price = price
        final_currency = currency
        if price and currency == 'TL':
            final_price = price * TL_TO_AED
            final_currency = 'AED'

        return ScrapingResult(
            status=status,
            price=final_price,
            currency=final_currency,
            product_title=title,
            url=url,
            raw_text=html[:1000],
            store_availability={'Trendyol': status}
        )

    def _parse_search_results(self, html, search_url, query):
        """Parse search results page and extract product listings."""
        soup = BeautifulSoup(html, 'html.parser')
        results = []

        # Look for product containers with common class patterns
        product_selectors = [
            {'name': 'div', 'class': re.compile(r'product.*card|p-card-wrppr', re.I)},
            {'name': 'div', 'class': re.compile(r'product-info', re.I)},
            {'name': 'a', 'class': re.compile(r'product-link', re.I)},
            {'name': 'div', 'class': 'p-card'},
        ]

        products = []
        for selector in product_selectors:
            found = soup.find_all(
                selector['name'],
                class_=selector['class'] if 'class' in selector else None
            )
            if found:
                products = found
                break

        if not products:
            return [ScrapingResult(
                status='UNKNOWN',
                error='Could not parse product containers from search results',
                url=search_url,
                store_availability={'Trendyol': 'UNKNOWN'}
            )]

        # Extract data from each product (limit to first 10)
        for product in products[:10]:
            try:
                # Extract title
                title_elem = product.find('span', class_=re.compile('name', re.I)) or \
                            product.find('h3') or \
                            product.find('a')
                title = title_elem.get_text(strip=True) if title_elem else 'Unknown'

                # Check relevance to query
                if not self._is_relevant(title, query):
                    continue

                # Extract price
                price_elem = product.find('span', class_=re.compile('price|fiyat', re.I))
                price = None
                currency = 'TL'

                if price_elem:
                    price_text = price_elem.get_text(strip=True)
                    price = self._parse_trendyol_price(price_text)

                # Check stock status
                indicators = self._check_stock_indicators(product, str(product))
                status = self.normalize_status(indicators)

                # Convert TL to AED
                final_price = price
                final_currency = currency
                if price and currency == 'TL':
                    final_price = price * TL_TO_AED
                    final_currency = 'AED'

                # Extract product link
                link_elem = product.find('a', href=True)
                product_url = None
                if link_elem:
                    href = link_elem.get('href', '')
                    if href.startswith('http'):
                        product_url = href
                    elif href.startswith('/'):
                        product_url = f"https://www.trendyol.com{href}"

                result = ScrapingResult(
                    status=status,
                    price=final_price,
                    currency=final_currency,
                    product_title=title,
                    url=product_url or search_url,
                    raw_text=str(product)[:500],
                    store_availability={'Trendyol': status}
                )
                results.append(result)

            except Exception as e:
                # Skip problematic products, continue with next
                continue

        if not results:
            return [ScrapingResult(
                status='UNKNOWN',
                error='No relevant products found in search results',
                url=search_url,
                store_availability={'Trendyol': 'UNKNOWN'}
            )]

        return results

    def _parse_trendyol_price(self, text):
        """
        Extract price from Trendyol price text.
        Handles Turkish Lira (TL) and AED formats.
        Returns float or None.
        """
        if not text:
            return None

        text = text.strip().replace(',', '')

        # Try TL patterns (Turkish Lira uses comma as decimal)
        tl_patterns = [
            r'(\d+(?:[.,]\d+)?)\s*(?:TL|₺)',
            r'(?:TL|₺)\s*(\d+(?:[.,]\d+)?)',
        ]

        for pattern in tl_patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    price_str = match.group(1).replace(',', '.')
                    price = float(price_str)
                    if 1 < price < 5000:
                        return price
                except ValueError:
                    continue

        # Try AED patterns (fallback)
        aed_patterns = [
            r'(\d+\.?\d*)\s*(?:AED|د\.إ)',
            r'(?:AED|د\.إ)\s*(\d+\.?\d*)',
        ]

        for pattern in aed_patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    price = float(match.group(1))
                    if 1 < price < 5000:
                        return price
                except ValueError:
                    continue

        # Fallback: try to extract any number
        numbers = re.findall(r'\d+(?:[.,]\d+)?', text)
        if numbers:
            try:
                price = float(numbers[0].replace(',', '.'))
                if 1 < price < 5000:
                    return price
            except ValueError:
                pass

        return None

    def _check_stock_indicators(self, soup, html_str):
        """Detect stock-related indicators in the HTML."""
        indicators = {
            'add_to_cart': False,
            'buy_now': False,
            'out_of_stock_text': False,
            'price_visible': False,
            'currently_unavailable': False,
            'limited_stock': False,
        }

        html_lower = str(html_str).lower()

        # Check for add to cart button
        add_cart = soup.find('button', class_=re.compile(r'cart|add', re.I))
        if add_cart and 'sepete' in html_lower:  # "sepete" = "to cart" in Turkish
            indicators['add_to_cart'] = True

        # Check for out of stock indicators
        oos_keywords = ['out of stock', 'stokta yok', 'tükendi', 'satış dışı']
        for keyword in oos_keywords:
            if keyword in html_lower:
                indicators['out_of_stock_text'] = True
                break

        # Check for currently unavailable
        unavailable_keywords = ['currently unavailable', 'şu anda kullanılamıyor', 'hazırlanıyor']
        for keyword in unavailable_keywords:
            if keyword in html_lower:
                indicators['currently_unavailable'] = True
                break

        # Check if price is visible
        if re.search(r'\d+(?:[.,]\d+)?(?:\s*TL|₺|AED|د\.إ)', html_lower):
            indicators['price_visible'] = True

        # Check for limited stock
        limited_keywords = ['limited', 'sınırlı', 'sadece', 'only']
        for keyword in limited_keywords:
            if keyword in html_lower:
                indicators['limited_stock'] = True
                break

        return indicators

    def _is_relevant(self, product_title, query):
        """
        Check if a product title is relevant to the search query.
        Returns True if the title contains key words from the query.
        """
        if not product_title or not query:
            return True

        title_lower = product_title.lower()
        query_lower = query.lower()

        # If title contains the full query, it's relevant
        if query_lower in title_lower:
            return True

        # Check if at least one significant word from query is in title
        query_words = [w for w in query_lower.split() if len(w) > 2]
        if query_words:
            matches = sum(1 for word in query_words if word in title_lower)
            return matches >= 1  # At least one word match

        return True
