"""
Scraper for Desertcart UAE (desertcart.ae).
Desertcart is fully JS-rendered, so we use ScraperAPI with render=true
to get the actual page content. Search URL approach.
"""

import os
import re
import json
import time
import requests
from urllib.parse import quote_plus
from bs4 import BeautifulSoup
from scrapers.base import BaseScraper, ScrapingResult, HEADERS, PROXY_URL

SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "")


class DesertcartScraper(BaseScraper):
    """Scraper for Desertcart.ae using ScraperAPI for JS rendering."""

    STORE_NAME = "Desertcart"
    BASE_URL = "https://www.desertcart.ae"

    def check_stock(self, url, product_name=None):
        """
        Check stock for a NeeDoh product on Desertcart.
        Strategy:
          1. For search URLs: use ScraperAPI with render=true to get JS-rendered HTML
          2. For product URLs: same approach
          3. Parse the rendered HTML for product data
        """
        try:
            # Extract search query from URL
            query = None
            if '?query=' in url:
                query = url.split('?query=')[1].split('&')[0].replace('+', ' ')
            elif '/search/' in url:
                query = url.split('/search/')[-1].split('?')[0].replace('+', ' ')

            # Try ScraperAPI with JS rendering
            if SCRAPER_API_KEY:
                result = self._scraperapi_fetch(url, product_name, query)
                if result and result.status != 'UNKNOWN':
                    return result

            # Fallback: try proxy
            html = None
            proxy_resp = self.proxy_get(url, timeout=20)
            if proxy_resp and proxy_resp.status_code == 200 and len(proxy_resp.text) > 2000:
                html = proxy_resp.text

            # Fallback: direct fetch (unlikely to work for JS site)
            if not html:
                html = self.fetch_page(url, timeout=15)

            if html and len(html) > 2000:
                return self._parse_html(html, url, product_name, query)

            return ScrapingResult(
                status='UNKNOWN',
                error='Failed to fetch Desertcart page (all methods failed)',
                url=url,
                product_title=product_name
            )

        except Exception as e:
            return ScrapingResult(
                status='UNKNOWN',
                error=f'Exception: {str(e)[:200]}',
                url=url,
                product_title=product_name
            )

    def _scraperapi_fetch(self, url, product_name, query):
        """Fetch Desertcart page via ScraperAPI with JS rendering enabled."""
        try:
            # ScraperAPI with render=true for JS-rendered pages
            scraper_url = (
                f"https://api.scraperapi.com/"
                f"?api_key={SCRAPER_API_KEY}"
                f"&url={quote_plus(url)}"
                f"&render=true"
                f"&country_code=ae"
            )

            # Retry logic for 499 errors
            max_retries = 2
            response = None
            for attempt in range(max_retries + 1):
                response = requests.get(scraper_url, timeout=90)  # longer timeout for JS render
                if response.status_code == 499 and attempt < max_retries:
                    wait = 3 + attempt * 2
                    print(f"  Desertcart ScraperAPI 499 — retrying in {wait}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait)
                    continue
                break

            if not response or response.status_code != 200:
                print(f"  Desertcart ScraperAPI returned {response.status_code if response else 'no response'}")
                return None

            html = response.text
            if len(html) < 2000:
                print(f"  Desertcart ScraperAPI returned too little HTML ({len(html)} chars)")
                return None

            return self._parse_html(html, url, product_name, query)

        except requests.Timeout:
            print("  Desertcart ScraperAPI timed out")
            return None
        except Exception as e:
            print(f"  Desertcart ScraperAPI error: {e}")
            return None

    def _parse_html(self, html, url, product_name, query):
        """Parse Desertcart HTML (search page or product page) for NeeDoh products."""
        soup = BeautifulSoup(html, 'html.parser')
        page_text = soup.get_text(' ', strip=True)

        # Check for __NEXT_DATA__ (Next.js app — may have structured data)
        next_data = soup.find('script', id='__NEXT_DATA__')
        if next_data and next_data.string:
            result = self._parse_next_data(next_data.string, url, product_name)
            if result and result.status != 'UNKNOWN':
                return result

        # Check if this is a search results page
        if '/search' in url or '?query=' in url:
            return self._parse_search_html(soup, html, url, product_name)

        # Product page
        return self._parse_product_html(soup, html, url, product_name)

    def _parse_next_data(self, json_str, url, product_name):
        """Try to extract product data from Next.js __NEXT_DATA__ script."""
        try:
            data = json.loads(json_str)
            props = data.get('props', {}).get('pageProps', {})

            # Search results
            products = (props.get('products', []) or
                       props.get('searchResults', []) or
                       props.get('items', []) or
                       props.get('data', {}).get('products', []) if isinstance(props.get('data'), dict) else [])

            if not products and isinstance(props.get('data'), dict):
                products = props['data'].get('products', [])

            for p in (products or [])[:15]:
                title = p.get('title', '') or p.get('name', '') or p.get('productName', '')
                if not self._is_relevant(title, product_name):
                    continue

                price = p.get('price') or p.get('salePrice') or p.get('currentPrice')
                if isinstance(price, str):
                    price = self._parse_price_value(price)
                elif isinstance(price, (int, float)):
                    price = float(price)

                out_of_stock = p.get('outOfStock', False) or p.get('soldOut', False)
                product_url = p.get('url', '') or p.get('slug', '')
                if product_url and not product_url.startswith('http'):
                    product_url = f"{self.BASE_URL}{product_url}" if product_url.startswith('/') else f"{self.BASE_URL}/{product_url}"

                # Extract delivery info
                delivery = p.get('deliveryDate', '') or p.get('estimatedDelivery', '')

                return ScrapingResult(
                    status='OUT_OF_STOCK' if out_of_stock else ('IN_STOCK' if price else 'UNKNOWN'),
                    price=price,
                    currency='AED',
                    seller='Desertcart',
                    product_title=title,
                    url=product_url or url,
                    raw_text=f'Desertcart NEXT_DATA: {title}',
                    delivery_estimate=delivery if delivery else None
                )

            # Single product page
            product = props.get('product', {})
            if product:
                title = product.get('title', '') or product.get('name', '')
                price = product.get('price') or product.get('salePrice')
                if isinstance(price, str):
                    price = self._parse_price_value(price)
                elif isinstance(price, (int, float)):
                    price = float(price)
                out_of_stock = product.get('outOfStock', False)
                delivery = product.get('deliveryDate', '') or product.get('estimatedDelivery', '')

                return ScrapingResult(
                    status='OUT_OF_STOCK' if out_of_stock else ('IN_STOCK' if price else 'UNKNOWN'),
                    price=price,
                    currency='AED',
                    seller='Desertcart',
                    product_title=title,
                    url=url,
                    raw_text=f'Desertcart product: {title}',
                    delivery_estimate=delivery if delivery else None
                )

        except (json.JSONDecodeError, KeyError, TypeError):
            pass

        return None

    def _parse_search_html(self, soup, html, url, product_name):
        """Parse search results from rendered HTML."""
        # Look for product cards/containers
        product_cards = soup.find_all('div', class_=re.compile(
            r'product-card|ProductCard|product-item|search-product|listing', re.I
        ))

        # Also try common patterns
        if not product_cards:
            product_cards = soup.find_all('a', href=re.compile(r'/products/\d+'))

        if not product_cards:
            # Try finding any link to a product page
            all_links = soup.find_all('a', href=re.compile(r'/products/'))
            seen = set()
            product_cards = []
            for link in all_links:
                href = link.get('href', '')
                if href not in seen:
                    seen.add(href)
                    # Get the parent container
                    parent = link.find_parent('div')
                    if parent and parent not in product_cards:
                        product_cards.append(parent)

        for card in product_cards[:15]:
            card_text = card.get_text(' ', strip=True)

            if not self._is_relevant(card_text, product_name):
                continue

            # Extract title
            title_el = card.find(['h2', 'h3', 'h4', 'a'], string=re.compile(r'needoh|nee.?doh|schylling', re.I))
            if not title_el:
                title_el = card.find(['h2', 'h3', 'h4'])
            if not title_el:
                title_el = card.find('a', href=re.compile(r'/products/'))
            title = title_el.get_text(strip=True) if title_el else product_name

            # Extract price
            price = self._extract_price_from_element(card)

            # Extract URL
            link = card.find('a', href=re.compile(r'/products/'))
            if not link:
                link = card.find('a', href=True)
            product_url = link['href'] if link else url
            if product_url and not product_url.startswith('http'):
                product_url = f"{self.BASE_URL}{product_url}"

            # Check stock indicators
            card_lower = card_text.lower()
            out_of_stock = 'out of stock' in card_lower or 'unavailable' in card_lower or 'sold out' in card_lower

            # Extract delivery
            delivery = self._extract_delivery(card, card_lower)

            return ScrapingResult(
                status='OUT_OF_STOCK' if out_of_stock else ('IN_STOCK' if price else 'UNKNOWN'),
                price=price,
                currency='AED',
                seller='Desertcart',
                product_title=title,
                url=product_url,
                raw_text=f'Desertcart search: {card_text[:300]}',
                delivery_estimate=delivery
            )

        # Check the full page text for any NeeDoh mention
        page_text = soup.get_text(' ', strip=True).lower()
        if 'needoh' in page_text or 'nee doh' in page_text:
            # Products exist but we couldn't parse the cards — try broader approach
            price = self._extract_price_from_element(soup)
            return ScrapingResult(
                status='IN_STOCK' if price else 'UNKNOWN',
                price=price,
                currency='AED',
                seller='Desertcart',
                product_title=product_name,
                url=url,
                raw_text=f'Desertcart search (broad): {page_text[:300]}'
            )

        return ScrapingResult(
            status='OUT_OF_STOCK',
            url=url,
            product_title=product_name,
            raw_text='No matching NeeDoh product found on Desertcart'
        )

    def _parse_product_html(self, soup, html, url, product_name):
        """Parse a single Desertcart product page."""
        page_text = soup.get_text(' ', strip=True)
        page_lower = page_text.lower()

        # Title
        title_el = soup.find('h1')
        title = title_el.get_text(strip=True) if title_el else product_name

        # Price
        price = self._extract_price_from_element(soup)

        # Delivery
        delivery = self._extract_delivery(soup, page_lower)

        # JSON-LD structured data
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                ld = json.loads(script.string)
                if isinstance(ld, dict) and ld.get('@type') == 'Product':
                    offers = ld.get('offers', {})
                    if isinstance(offers, list):
                        offers = offers[0] if offers else {}
                    if isinstance(offers, dict):
                        if not price and offers.get('price'):
                            price = float(offers['price'])
                        avail = offers.get('availability', '')
                        if 'InStock' in avail:
                            return ScrapingResult(
                                status='IN_STOCK', price=price, currency='AED',
                                seller='Desertcart', product_title=title,
                                url=url, raw_text=page_text[:500],
                                delivery_estimate=delivery
                            )
                        elif 'OutOfStock' in avail:
                            return ScrapingResult(
                                status='OUT_OF_STOCK', price=price, currency='AED',
                                seller='Desertcart', product_title=title,
                                url=url, raw_text=page_text[:500],
                                delivery_estimate=delivery
                            )
            except (json.JSONDecodeError, ValueError, TypeError):
                continue

        # Standard indicators
        indicators = {
            'out_of_stock_text': 'out of stock' in page_lower or 'sold out' in page_lower,
            'add_to_cart': 'add to cart' in page_lower or 'add to basket' in page_lower,
            'buy_now': 'buy now' in page_lower,
            'price_visible': price is not None,
            'currently_unavailable': 'currently unavailable' in page_lower or 'not available' in page_lower,
        }

        status = self.normalize_status(indicators)

        return ScrapingResult(
            status=status,
            price=price,
            currency='AED',
            seller='Desertcart',
            product_title=title,
            url=url,
            raw_text=page_text[:500],
            delivery_estimate=delivery
        )

    def _extract_price_from_element(self, elem):
        """Extract AED price from an element."""
        text = elem.get_text(' ', strip=True)

        # AED patterns
        patterns = [
            r'AED\s*(\d+(?:\.\d+)?)',
            r'(\d+(?:\.\d+)?)\s*AED',
            r'(?:Price|price)[:\s]*AED\s*(\d+(?:\.\d+)?)',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.I)
            if match:
                try:
                    price = float(match.group(1))
                    if 1 < price < 5000:
                        return price
                except ValueError:
                    continue

        # Try price elements with CSS classes
        price_elems = elem.find_all(['span', 'div', 'p'], class_=re.compile(r'price|cost|amount', re.I))
        for pe in price_elems:
            price = self.parse_price(pe.get_text(strip=True))
            if price:
                return price

        return None

    def _parse_price_value(self, text):
        """Parse a price string to float."""
        if not text:
            return None
        text = re.sub(r'[^\d.]', '', str(text))
        try:
            val = float(text)
            return val if 1 < val < 5000 else None
        except ValueError:
            return None

    def _extract_delivery(self, elem, text_lower):
        """Extract delivery estimate from page element."""
        patterns = [
            r'(?:estimated delivery|delivery by|arrives?|delivered? by)\s*[:\-]?\s*(.{5,60}?)(?:\.|<|$)',
            r'(?:get it by|expected delivery)\s*[:\-]?\s*(.{5,60}?)(?:\.|<|$)',
            r'(\d+\s*-\s*\d+\s*(?:business\s*)?days?)',
            r'(delivery in \d+.*?days?)',
        ]
        for pattern in patterns:
            match = re.search(pattern, text_lower, re.I)
            if match:
                return match.group(1).strip()[:80]

        # Check for delivery elements
        delivery_el = elem.find(['div', 'span', 'p'], class_=re.compile(r'delivery|shipping|dispatch', re.I))
        if delivery_el:
            text = delivery_el.get_text(strip=True)
            if len(text) < 100 and ('day' in text.lower() or 'deliver' in text.lower()):
                return text

        return None

    def _is_relevant(self, text, product_name):
        """Check if text mentions a NeeDoh product."""
        if not text:
            return False
        text_lower = text.lower()

        # Must mention needoh or schylling
        if 'needoh' not in text_lower and 'nee doh' not in text_lower and 'nee-doh' not in text_lower and 'schylling' not in text_lower:
            return False

        return True
