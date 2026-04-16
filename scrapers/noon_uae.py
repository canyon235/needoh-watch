"""
Noon UAE scraper for NeeDoh products.
Noon uses heavy JS rendering, so we parse what we can from the initial HTML
and fall back to API-like endpoints when possible.
"""

import re
import json
import time
from bs4 import BeautifulSoup
from scrapers.base import BaseScraper, ScrapingResult


class NoonScraper(BaseScraper):
    STORE_NAME = "Noon"

    def __init__(self):
        super().__init__()
        # Noon has a JSON API that sometimes works for search
        self.api_base = "https://www.noon.com/_svc/catalog/api/v3/u/"

    def check_stock(self, url, product_name=None):
        """Check stock on Noon UAE."""
        start = time.time()

        # Try the catalog API first for search queries
        if 'search' in url and 'q=' in url:
            result = self._try_api_search(url, product_name)
            if result and result.status != 'UNKNOWN':
                return result

        # Fall back to HTML scraping
        html = self.fetch_page(url)
        if not html:
            return ScrapingResult(
                status='UNKNOWN', error='Failed to fetch Noon page', url=url)

        soup = BeautifulSoup(html, 'lxml')

        if '/search' in url:
            return self._parse_search(soup, url, product_name, html)
        else:
            return self._parse_product(soup, url, html)

    def _try_api_search(self, url, product_name):
        """Try Noon's internal search API."""
        try:
            # Extract query from URL
            query = re.search(r'[?&]q=([^&]+)', url)
            if not query:
                return None

            search_term = query.group(1).replace('+', ' ')
            api_url = f"{self.api_base}search/?q={search_term}&locale=en-ae"

            response = self.session.get(api_url, timeout=10, headers={
                **self.session.headers,
                'Accept': 'application/json',
            })

            if response.status_code != 200:
                return None

            data = response.json()
            hits = data.get('hits', [])

            if not hits:
                return ScrapingResult(
                    status='OUT_OF_STOCK',
                    raw_text=f'No results for "{search_term}" on Noon',
                    url=url
                )

            # Find best match
            for hit in hits[:5]:
                title = hit.get('name', '') or hit.get('title', '')
                if self._is_relevant_noon(title, product_name or search_term):
                    price = hit.get('sale_price') or hit.get('price')
                    offer_price = hit.get('offer_price')
                    actual_price = offer_price or price

                    is_buyable = hit.get('is_buyable', False)
                    stock_text = hit.get('stock_text', '')

                    status = 'IN_STOCK' if is_buyable else 'OUT_OF_STOCK'
                    if stock_text and ('few left' in stock_text.lower() or 'limited' in stock_text.lower()):
                        status = 'LOW_STOCK'

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
                        url=url
                    )

            return None
        except Exception:
            return None

    def _parse_search(self, soup, url, product_name, html):
        """Parse Noon search results page (HTML fallback)."""
        # Noon renders most content via JS, so we look for embedded JSON data
        scripts = soup.find_all('script', type='application/json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and 'props' in data:
                    return self._extract_from_next_data(data, url, product_name)
            except (json.JSONDecodeError, TypeError):
                continue

        # Also check __NEXT_DATA__
        next_data = soup.find('script', id='__NEXT_DATA__')
        if next_data:
            try:
                data = json.loads(next_data.string)
                return self._extract_from_next_data(data, url, product_name)
            except (json.JSONDecodeError, TypeError):
                pass

        # Pure HTML fallback
        product_cards = soup.select('[data-qa="product-block"]') or soup.select('.productContainer')

        if not product_cards:
            page_text = soup.get_text(' ', strip=True).lower()
            if 'no results' in page_text or 'sorry' in page_text:
                return ScrapingResult(
                    status='OUT_OF_STOCK',
                    raw_text='No results found on Noon',
                    url=url
                )
            return ScrapingResult(
                status='UNKNOWN',
                raw_text=page_text[:500],
                url=url
            )

        # Parse first relevant card
        for card in product_cards[:5]:
            card_text = card.get_text(' ', strip=True)
            price_el = card.select_one('[data-qa="product-price"]') or card.select_one('.price')
            price = self.parse_price(price_el.get_text()) if price_el else self.parse_price(card_text)

            title_el = card.select_one('[data-qa="product-name"]') or card.select_one('.name')
            title = title_el.get_text(strip=True) if title_el else ''

            if price:
                return ScrapingResult(
                    status='IN_STOCK',
                    price=price,
                    product_title=title,
                    raw_text=card_text[:300],
                    url=url
                )

        return ScrapingResult(
            status='UNKNOWN',
            raw_text=soup.get_text(' ', strip=True)[:500],
            url=url
        )

    def _parse_product(self, soup, url, html):
        """Parse an individual Noon product page."""
        indicators = {
            'add_to_cart': False,
            'buy_now': False,
            'out_of_stock_text': False,
            'currently_unavailable': False,
            'price_visible': False,
        }

        page_text = soup.get_text(' ', strip=True).lower()

        # Title
        title_el = soup.select_one('h1') or soup.select_one('[data-qa="pdp-name"]')
        title = title_el.get_text(strip=True) if title_el else ''

        # Price
        price = None
        price_el = soup.select_one('[data-qa="div-price"]') or soup.select_one('.priceNow')
        if price_el:
            price = self.parse_price(price_el.get_text())
            indicators['price_visible'] = price is not None

        # Stock signals
        if 'add to cart' in page_text or 'add to bag' in page_text:
            indicators['add_to_cart'] = True
        if 'buy now' in page_text:
            indicators['buy_now'] = True
        if 'out of stock' in page_text or 'sold out' in page_text:
            indicators['out_of_stock_text'] = True
        if 'currently unavailable' in page_text:
            indicators['currently_unavailable'] = True

        # Seller
        seller = None
        seller_el = soup.select_one('[data-qa="seller-name"]')
        if seller_el:
            seller = seller_el.get_text(strip=True)

        return ScrapingResult(
            status=self.normalize_status(indicators),
            price=price,
            seller=seller,
            product_title=title,
            raw_text=page_text[:500],
            url=url
        )

    def _extract_from_next_data(self, data, url, product_name):
        """Extract product data from Next.js data blob."""
        try:
            # Navigate the nested structure
            page_props = data.get('props', {}).get('pageProps', {})
            catalog = page_props.get('catalog', {}) or page_props.get('searchResult', {})
            hits = catalog.get('hits', []) or catalog.get('products', [])

            if not hits:
                return ScrapingResult(status='OUT_OF_STOCK', raw_text='No results in Noon data', url=url)

            for hit in hits[:5]:
                title = hit.get('name', '') or hit.get('title', '')
                price = hit.get('sale_price') or hit.get('price') or hit.get('offer_price')
                is_buyable = hit.get('is_buyable', True)

                return ScrapingResult(
                    status='IN_STOCK' if is_buyable and price else 'OUT_OF_STOCK',
                    price=float(price) if price else None,
                    product_title=title,
                    raw_text=json.dumps(hit)[:500],
                    url=url
                )
        except Exception:
            pass

        return ScrapingResult(status='UNKNOWN', url=url)

    def _is_relevant_noon(self, title, query):
        """Check relevance for Noon results."""
        if not title or not query:
            return True
        title_lower = title.lower()
        keywords = [w for w in query.lower().split() if len(w) > 2]
        matches = sum(1 for kw in keywords if kw in title_lower)
        return matches >= max(1, len(keywords) * 0.4)
