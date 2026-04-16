"""
Playwright-based scraper for JS-heavy sites (Desertcart, Trendyol).
Falls back to this when requests+BeautifulSoup can't get enough data.

Uses ThreadPoolExecutor to run sync Playwright in a separate thread,
avoiding "Sync API inside asyncio loop" errors when Flask uses asyncio.
"""

import re
import json
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from scrapers.base import BaseScraper, ScrapingResult

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


class PlaywrightScraper(BaseScraper):
    """Scraper using headless Chromium for JS-rendered pages.
    Runs in a dedicated thread to avoid asyncio conflicts."""

    STORE_NAME = "playwright"

    def __init__(self):
        super().__init__()
        # Single-threaded executor — Playwright is NOT thread-safe,
        # so all calls are serialized through one worker thread.
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='playwright')

    def close(self):
        """Shut down the executor (browser closes with the thread)."""
        self._executor.shutdown(wait=False)

    def check_stock(self, url, product_name=None):
        """Check stock using headless browser in a separate thread."""
        if not HAS_PLAYWRIGHT:
            return ScrapingResult(
                status='UNKNOWN',
                error='Playwright not installed',
                url=url
            )

        try:
            future = self._executor.submit(self._check_stock_sync, url, product_name)
            return future.result(timeout=35)  # 35s hard cap
        except FuturesTimeout:
            return ScrapingResult(
                status='UNKNOWN',
                error='Playwright timed out (35s)',
                url=url
            )
        except Exception as e:
            return ScrapingResult(
                status='UNKNOWN',
                error=f'Playwright thread error: {str(e)[:200]}',
                url=url
            )

    def _check_stock_sync(self, url, product_name):
        """Actual Playwright work — runs in a clean thread without asyncio loop."""
        pw = None
        browser = None
        page = None
        try:
            start = time.time()
            pw = sync_playwright().start()
            browser = pw.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-dev-shm-usage']
            )
            page = browser.new_page(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
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
            elif 'desertcart' in url:
                return self._parse_desertcart(page, page_text, page_html, url, product_name, duration)
            elif 'trendyol' in url:
                return self._parse_trendyol(page, page_text, page_html, url, product_name, duration)
            else:
                return self._parse_generic(page, page_text, url, product_name, duration)

        except Exception as e:
            return ScrapingResult(status='UNKNOWN', error=f'Playwright error: {str(e)[:200]}', url=url)
        finally:
            if page:
                try: page.close()
                except: pass
            if browser:
                try: browser.close()
                except: pass
            if pw:
                try: pw.stop()
                except: pass

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

    def _parse_desertcart(self, page, page_text, page_html, url, product_name, duration):
        """Parse Desertcart search results rendered with JS (Next.js)."""
        lower = page_text.lower()

        # Wait extra time for JS to render products
        page.wait_for_timeout(3000)
        page_text = page.inner_text('body')
        lower = page_text.lower()

        # Check for no results
        if 'no results' in lower or 'no products found' in lower or 'sorry' in lower:
            return ScrapingResult(status='OUT_OF_STOCK', raw_text='No results on Desertcart', url=url)

        # Look for product cards/containers
        cards = page.query_selector_all(
            '.product-card, [class*="ProductCard"], [class*="product-item"], '
            '[class*="search-result"], a[href*="/products/"]'
        )

        if not cards:
            # Try broader selectors
            cards = page.query_selector_all('[class*="product"], [class*="item-card"]')

        for card in cards[:10]:
            try:
                card_text = card.inner_text()
                card_lower = card_text.lower()

                # Must contain needoh/schylling
                if 'needoh' not in card_lower and 'nee doh' not in card_lower and 'schylling' not in card_lower:
                    continue

                # Check relevance to specific product
                if product_name and not self._is_match(card_text, product_name):
                    continue

                # Extract price (AED format)
                price = self.parse_price(card_text)

                # Extract product link
                link = card.query_selector('a[href]') if card.evaluate('el => el.tagName') != 'A' else card
                product_url = None
                if link:
                    href = link.get_attribute('href') or ''
                    if href.startswith('/'):
                        product_url = f"https://www.desertcart.ae{href}"
                    elif href.startswith('http'):
                        product_url = href

                # Title extraction
                title_el = card.query_selector('h2, h3, [class*="title"], [class*="name"]')
                title = title_el.inner_text().strip() if title_el else card_text[:100]

                # Stock indicators
                indicators = {
                    'add_to_cart': 'add to cart' in card_lower or 'add to bag' in card_lower,
                    'out_of_stock_text': 'out of stock' in card_lower or 'unavailable' in card_lower,
                    'price_visible': price is not None,
                }

                # Extract delivery info
                delivery = None
                delivery_match = re.search(
                    r'(?:deliver|ship|arrives?|get it)\s*(?:by|in|on)?\s*([\w\s,\d-]+)',
                    card_text, re.I
                )
                if delivery_match:
                    delivery = delivery_match.group(0).strip()[:50]

                return ScrapingResult(
                    status=self.normalize_status(indicators),
                    price=price,
                    product_title=title,
                    raw_text=card_text[:300],
                    url=product_url or url,
                    delivery_estimate=delivery
                )
            except Exception:
                continue

        # Fallback: scan entire page text for price/stock info
        if 'needoh' in lower or 'nee doh' in lower:
            price = self.parse_price(page_text)
            indicators = {
                'add_to_cart': 'add to cart' in lower,
                'out_of_stock_text': 'out of stock' in lower,
                'price_visible': price is not None,
            }
            return ScrapingResult(
                status=self.normalize_status(indicators),
                price=price,
                raw_text=page_text[:500],
                url=url
            )

        return ScrapingResult(status='OUT_OF_STOCK', raw_text='No NeeDoh products found on Desertcart', url=url)

    def _parse_trendyol(self, page, page_text, page_html, url, product_name, duration):
        """Parse Trendyol search results (may have Cloudflare challenge first)."""
        lower = page_text.lower()

        # Check if still on Cloudflare challenge page
        if 'checking your browser' in lower or 'just a moment' in lower:
            # Wait for challenge to resolve
            page.wait_for_timeout(5000)
            page_text = page.inner_text('body')
            lower = page_text.lower()

        # Still on challenge?
        if 'checking your browser' in lower:
            return ScrapingResult(
                status='UNKNOWN',
                error='Cloudflare challenge did not resolve',
                url=url
            )

        # Check for no results
        if 'sonuç bulunamadı' in lower or 'no results' in lower:
            return ScrapingResult(status='OUT_OF_STOCK', raw_text='No results on Trendyol', url=url)

        # Look for product cards
        cards = page.query_selector_all(
            '.p-card-wrppr, [class*="ProductCard"], .prdct-cntnr-wrppr, '
            '[class*="product-card"], .p-card'
        )

        if not cards:
            cards = page.query_selector_all('[class*="product"]')

        for card in cards[:10]:
            try:
                card_text = card.inner_text()
                card_lower = card_text.lower()

                # Must contain needoh reference
                if 'needoh' not in card_lower and 'nee doh' not in card_lower and 'schylling' not in card_lower:
                    continue

                if product_name and not self._is_match(card_text, product_name):
                    continue

                # Extract price (TL format, convert to AED)
                price = None
                tl_match = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:TL|₺)', card_text)
                if tl_match:
                    try:
                        tl_price = float(tl_match.group(1).replace(',', '.'))
                        price = round(tl_price * 0.12, 2)  # TL to AED
                    except ValueError:
                        pass

                if price is None:
                    price = self.parse_price(card_text)

                # Extract product link
                link = card.query_selector('a[href]')
                product_url = None
                if link:
                    href = link.get_attribute('href') or ''
                    if href.startswith('/'):
                        product_url = f"https://www.trendyol.com{href}"
                    elif href.startswith('http'):
                        product_url = href

                # Title
                title_el = card.query_selector('[class*="name"], [class*="desc"], h3, span')
                title = title_el.inner_text().strip() if title_el else card_text[:100]

                indicators = {
                    'add_to_cart': 'sepete' in card_lower or 'add' in card_lower,
                    'out_of_stock_text': 'tükendi' in card_lower or 'out of stock' in card_lower,
                    'price_visible': price is not None,
                }

                return ScrapingResult(
                    status=self.normalize_status(indicators),
                    price=price,
                    currency='AED',
                    product_title=title,
                    raw_text=card_text[:300],
                    url=product_url or url,
                    store_availability={'Trendyol': self.normalize_status(indicators)}
                )
            except Exception:
                continue

        # Fallback
        if 'needoh' in lower or 'nee doh' in lower:
            price = self.parse_price(page_text)
            indicators = {
                'add_to_cart': 'sepete' in lower or 'add to cart' in lower,
                'out_of_stock_text': 'tükendi' in lower or 'out of stock' in lower,
                'price_visible': price is not None,
            }
            return ScrapingResult(
                status=self.normalize_status(indicators),
                price=price,
                raw_text=page_text[:500],
                url=url
            )

        return ScrapingResult(status='OUT_OF_STOCK', raw_text='No NeeDoh products found on Trendyol', url=url)

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
