"""
Playwright-based scraper for JS-heavy sites (Noon, Virgin).
Falls back to this when requests+BeautifulSoup can't get enough data.
"""

import re
import json
import time
from scrapers.base import BaseScraper, ScrapingResult

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


class PlaywrightScraper(BaseScraper):
    """Scraper using headless Chromium for JS-rendered pages."""

    STORE_NAME = "playwright"

    def __init__(self):
        super().__init__()
        self._browser = None
        self._playwright = None

    def _get_browser(self):
        if not HAS_PLAYWRIGHT:
            return None
        if not self._browser:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-dev-shm-usage']
            )
        return self._browser

    def close(self):
        if self._browser:
            self._browser.close()
            self._browser = None
        if self._playwright:
            self._playwright.stop()
            self._playwright = None

    def check_stock(self, url, product_name=None):
        """Check stock using headless browser."""
        if not HAS_PLAYWRIGHT:
            return ScrapingResult(
                status='UNKNOWN',
                error='Playwright not installed. Run: pip install playwright && python -m playwright install chromium',
                url=url
            )

        browser = self._get_browser()
        if not browser:
            return ScrapingResult(status='UNKNOWN', error='Could not start browser', url=url)

        page = None
        try:
            start = time.time()
            page = browser.new_page(
                user_agent=self.session.headers.get('User-Agent', ''),
                viewport={'width': 1280, 'height': 800}
            )
            page.set_default_timeout(20000)

            page.goto(url, wait_until='domcontentloaded')
            # Wait for dynamic content
            page.wait_for_timeout(3000)

            # Get full page text
            page_text = page.inner_text('body')
            page_html = page.content()
            duration = int((time.time() - start) * 1000)

            # Determine store
            if 'noon.com' in url:
                return self._parse_noon(page, page_text, page_html, url, product_name, duration)
            elif 'virginmegastore' in url:
                return self._parse_virgin(page, page_text, page_html, url, product_name, duration)
            else:
                return self._parse_generic(page, page_text, url, product_name, duration)

        except Exception as e:
            return ScrapingResult(status='UNKNOWN', error=f'Playwright error: {str(e)[:200]}', url=url)
        finally:
            if page:
                page.close()

    def _parse_noon(self, page, page_text, page_html, url, product_name, duration):
        """Parse Noon page rendered with JS."""
        lower = page_text.lower()

        # Try to extract structured data
        try:
            json_data = page.evaluate("""
                () => {
                    const el = document.querySelector('#__NEXT_DATA__');
                    if (el) return JSON.parse(el.textContent);
                    return null;
                }
            """)
            if json_data:
                return self._extract_noon_next_data(json_data, url, product_name)
        except Exception:
            pass

        # Check for product cards
        cards = page.query_selector_all('[data-qa="product-block"], .productContainer, [class*="ProductCard"]')

        if not cards and ('no results' in lower or '0 results' in lower):
            return ScrapingResult(status='OUT_OF_STOCK', raw_text='No results on Noon', url=url)

        # Parse first product card
        for card in cards[:5]:
            try:
                card_text = card.inner_text()
                card_lower = card_text.lower()

                # Title
                title_el = card.query_selector('[data-qa="product-name"], .name, h3')
                title = title_el.inner_text().strip() if title_el else ''

                if product_name and not self._is_match(title, product_name):
                    continue

                # Price
                price_el = card.query_selector('[data-qa="product-price"], .price, [class*="price"]')
                price = self.parse_price(price_el.inner_text()) if price_el else self.parse_price(card_text)

                # Stock
                indicators = {
                    'add_to_cart': 'add to' in card_lower,
                    'out_of_stock_text': 'out of stock' in card_lower or 'sold out' in card_lower,
                    'price_visible': price is not None,
                }

                return ScrapingResult(
                    status=self.normalize_status(indicators),
                    price=price,
                    product_title=title,
                    raw_text=card_text[:300],
                    url=url
                )
            except Exception:
                continue

        # Fallback: scan page text
        price = self.parse_price(page_text)
        indicators = {
            'add_to_cart': 'add to cart' in lower or 'add to bag' in lower,
            'out_of_stock_text': 'out of stock' in lower or 'sold out' in lower,
            'price_visible': price is not None,
            'buy_now': 'buy now' in lower,
        }

        return ScrapingResult(
            status=self.normalize_status(indicators),
            price=price,
            raw_text=page_text[:500],
            url=url
        )

    def _parse_virgin(self, page, page_text, page_html, url, product_name, duration):
        """Parse Virgin Megastore page rendered with JS."""
        lower = page_text.lower()

        cards = page.query_selector_all('.product-item, .product-card, [class*="ProductCard"], .search-result-item')

        if not cards and ('no results' in lower or 'no products' in lower):
            return ScrapingResult(status='OUT_OF_STOCK', raw_text='No results on Virgin', url=url)

        # Check for store availability feature
        store_availability = None
        if 'check availability' in lower or 'check in store' in lower or 'find in store' in lower:
            store_availability = {'has_store_check': True, 'stores': []}

            # Try to click "check availability" and get store data
            try:
                check_btn = page.query_selector('[class*="store-check"], [class*="StoreAvail"], button:has-text("Check")')
                if check_btn:
                    check_btn.click()
                    page.wait_for_timeout(2000)
                    store_items = page.query_selector_all('.store-availability li, [class*="store-item"]')
                    for item in store_items:
                        item_text = item.inner_text()
                        store_availability['stores'].append({
                            'name': item_text[:100],
                            'available': 'available' in item_text.lower() and 'unavailable' not in item_text.lower()
                        })
            except Exception:
                pass

        for card in cards[:5]:
            try:
                card_text = card.inner_text()
                card_lower = card_text.lower()

                title_el = card.query_selector('a[title], h2, h3, .product-name')
                title = ''
                if title_el:
                    title = title_el.get_attribute('title') or title_el.inner_text()
                    title = title.strip()

                if product_name and not self._is_match(title, product_name):
                    continue

                price_el = card.query_selector('.price, [class*="price"], .amount')
                price = self.parse_price(price_el.inner_text()) if price_el else self.parse_price(card_text)

                indicators = {
                    'add_to_cart': 'add to cart' in card_lower or 'add to bag' in card_lower,
                    'out_of_stock_text': 'out of stock' in card_lower or 'sold out' in card_lower,
                    'price_visible': price is not None,
                }

                return ScrapingResult(
                    status=self.normalize_status(indicators),
                    price=price,
                    product_title=title,
                    raw_text=card_text[:300],
                    store_availability=store_availability,
                    url=url
                )
            except Exception:
                continue

        # Fallback
        price = self.parse_price(page_text)
        indicators = {
            'add_to_cart': 'add to cart' in lower,
            'out_of_stock_text': 'out of stock' in lower or 'sold out' in lower,
            'price_visible': price is not None,
        }

        return ScrapingResult(
            status=self.normalize_status(indicators),
            price=price,
            raw_text=page_text[:500],
            store_availability=store_availability,
            url=url
        )

    def _parse_generic(self, page, page_text, url, product_name, duration):
        """Generic page parser."""
        lower = page_text.lower()
        price = self.parse_price(page_text)

        indicators = {
            'add_to_cart': 'add to cart' in lower or 'add to bag' in lower,
            'buy_now': 'buy now' in lower,
            'out_of_stock_text': 'out of stock' in lower or 'sold out' in lower,
            'currently_unavailable': 'currently unavailable' in lower,
            'price_visible': price is not None,
        }

        return ScrapingResult(
            status=self.normalize_status(indicators),
            price=price,
            raw_text=page_text[:500],
            url=url
        )

    def _extract_noon_next_data(self, data, url, product_name):
        """Extract from Noon's __NEXT_DATA__."""
        try:
            page_props = data.get('props', {}).get('pageProps', {})
            catalog = page_props.get('catalog', {}) or page_props.get('searchResult', {})
            hits = catalog.get('hits', []) or catalog.get('products', [])

            if not hits:
                return ScrapingResult(status='OUT_OF_STOCK', raw_text='No results in Noon data', url=url)

            for hit in hits[:5]:
                title = hit.get('name', '') or hit.get('title', '')
                price = hit.get('sale_price') or hit.get('price') or hit.get('offer_price')
                is_buyable = hit.get('is_buyable', True)

                if product_name and not self._is_match(title, product_name):
                    continue

                return ScrapingResult(
                    status='IN_STOCK' if is_buyable and price else 'OUT_OF_STOCK',
                    price=float(price) if price else None,
                    product_title=title,
                    seller=hit.get('seller_name'),
                    raw_text=json.dumps(hit)[:500],
                    url=url
                )

            # No match found but results exist
            hit = hits[0]
            return ScrapingResult(
                status='IN_STOCK' if hit.get('is_buyable') else 'OUT_OF_STOCK',
                price=float(hit.get('sale_price') or hit.get('price') or 0) or None,
                product_title=hit.get('name', ''),
                raw_text=json.dumps(hit)[:500],
                url=url
            )
        except Exception:
            return ScrapingResult(status='UNKNOWN', url=url)

    def _is_match(self, title, product_name):
        if not title or not product_name:
            return True
        title_lower = title.lower()
        keywords = [w for w in product_name.lower().split() if len(w) > 2]
        matches = sum(1 for kw in keywords if kw in title_lower)
        return matches >= max(1, len(keywords) * 0.4)
