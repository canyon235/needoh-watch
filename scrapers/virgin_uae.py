"""
Virgin Megastore UAE scraper.
Virgin exposes in-store availability checking on product pages,
making it a hybrid online/offline signal source.

NOTE: Virgin uses Akamai WAF that blocks cloud server IPs.
The scraper tries multiple approaches:
1. cloudscraper (Cloudflare/Akamai bypass)
2. Direct requests with enhanced headers
3. Playwright browser automation (via checker fallback)
If all fail, it returns UNKNOWN with a link to check manually.
The main value of Virgin in this system is the offline sighting reports.
"""

import re
import json
import time
import random
from bs4 import BeautifulSoup
from scrapers.base import BaseScraper, ScrapingResult

# Try to import cloudscraper for WAF bypass
try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    HAS_CLOUDSCRAPER = False


class VirginScraper(BaseScraper):
    STORE_NAME = "Virgin Megastore UAE"

    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    ]

    def __init__(self):
        super().__init__()
        self.base_url = "https://www.virginmegastore.ae"
        # Create cloudscraper session if available
        if HAS_CLOUDSCRAPER:
            self.cloud_session = cloudscraper.create_scraper(
                browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False}
            )
        else:
            self.cloud_session = None

    def check_stock(self, url, product_name=None):
        """Check stock on Virgin Megastore UAE."""
        html = self._fetch_virgin_page(url)

        if not html:
            # All methods failed — return UNKNOWN with helpful info
            # Virgin is still valuable for offline sighting reports
            return ScrapingResult(
                status='UNKNOWN',
                error='Virgin website requires manual check (WAF protection)',
                raw_text='Virgin Megastore blocks automated checks. '
                         'Use "I Spotted One" to report sightings from physical stores.',
                url=url
            )

        soup = BeautifulSoup(html, 'lxml')

        if '/search' in url:
            return self._parse_search(soup, url, product_name, html)
        else:
            return self._parse_product(soup, url, html)

    def _fetch_virgin_page(self, url):
        """Try multiple methods to fetch a Virgin page."""
        # Method 1: cloudscraper (handles many WAF challenges)
        if self.cloud_session:
            try:
                response = self.cloud_session.get(url, timeout=15)
                if response.status_code == 200 and len(response.text) > 1000:
                    return response.text
            except Exception:
                pass

        # Method 2: Direct request with enhanced headers and different user agents
        for attempt, ua in enumerate(self.USER_AGENTS):
            try:
                headers = {
                    'User-Agent': ua,
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9,ar;q=0.8',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Referer': 'https://www.virginmegastore.ae/',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'same-origin',
                    'Sec-Fetch-User': '?1',
                    'Upgrade-Insecure-Requests': '1',
                    'Connection': 'keep-alive',
                }
                response = self.session.get(url, headers=headers, timeout=12)
                if response.status_code == 200 and len(response.text) > 1000:
                    return response.text
            except Exception:
                pass

            if attempt < len(self.USER_AGENTS) - 1:
                time.sleep(random.uniform(2, 4))

        return None

    def _parse_search(self, soup, url, product_name, html):
        """Parse Virgin search results."""
        product_cards = (
            soup.select('.product-item') or
            soup.select('.product-card') or
            soup.select('[class*="ProductCard"]') or
            soup.select('.search-result-item')
        )

        page_text = soup.get_text(' ', strip=True)

        if not product_cards:
            lower = page_text.lower()
            if 'no results' in lower or 'no products' in lower or '0 results' in lower:
                return ScrapingResult(
                    status='OUT_OF_STOCK',
                    raw_text='No results found on Virgin Megastore',
                    url=url
                )

            # Try to find embedded JSON data
            scripts = soup.find_all('script')
            for script in scripts:
                if script.string and ('product' in (script.string or '').lower()):
                    try:
                        if 'application/ld+json' in str(script):
                            data = json.loads(script.string)
                            return self._parse_json_ld(data, url)
                    except (json.JSONDecodeError, TypeError):
                        continue

            return ScrapingResult(
                status='UNKNOWN',
                raw_text=page_text[:500],
                url=url
            )

        # Parse product cards
        for card in product_cards[:5]:
            card_text = card.get_text(' ', strip=True)
            card_lower = card_text.lower()

            title_el = card.select_one('a[title]') or card.select_one('h2') or card.select_one('h3')
            title = (title_el.get('title') or title_el.get_text(strip=True)) if title_el else ''

            if product_name and not self._is_relevant(title, product_name):
                continue

            price = None
            price_el = (card.select_one('.price') or card.select_one('[class*="price"]')
                        or card.select_one('.amount'))
            if price_el:
                price = self.parse_price(price_el.get_text())

            indicators = {
                'add_to_cart': 'add to cart' in card_lower or 'add to bag' in card_lower,
                'out_of_stock_text': 'out of stock' in card_lower or 'sold out' in card_lower,
                'price_visible': price is not None,
            }

            store_check = (
                'check availability' in card_lower or
                'check in store' in card_lower or
                'store availability' in card_lower
            )

            status = self.normalize_status(indicators)

            return ScrapingResult(
                status=status,
                price=price,
                product_title=title,
                raw_text=card_text[:300],
                store_availability={'has_store_check': store_check} if store_check else None,
                url=url
            )

        return ScrapingResult(
            status='UNKNOWN',
            raw_text=page_text[:500],
            url=url
        )

    def _parse_product(self, soup, url, html):
        """Parse an individual Virgin product page."""
        indicators = {
            'add_to_cart': False,
            'buy_now': False,
            'out_of_stock_text': False,
            'currently_unavailable': False,
            'price_visible': False,
            'limited_stock': False,
        }

        page_text = soup.get_text(' ', strip=True)
        lower = page_text.lower()

        title_el = soup.select_one('h1') or soup.select_one('.product-title')
        title = title_el.get_text(strip=True) if title_el else ''

        price = None
        price_selectors = [
            '.product-price', '.price-box .price', '[class*="price"] .amount',
            '[itemprop="price"]', '.special-price .price'
        ]
        for sel in price_selectors:
            el = soup.select_one(sel)
            if el:
                price = self.parse_price(el.get_text())
                if price:
                    indicators['price_visible'] = True
                    break

        if 'add to cart' in lower or 'add to bag' in lower:
            indicators['add_to_cart'] = True
        if 'buy now' in lower:
            indicators['buy_now'] = True
        if 'out of stock' in lower or 'sold out' in lower:
            indicators['out_of_stock_text'] = True
        if 'currently unavailable' in lower or 'notify me' in lower:
            indicators['currently_unavailable'] = True
        if 'limited stock' in lower or 'few left' in lower:
            indicators['limited_stock'] = True

        store_availability = self._check_store_availability(soup, lower)

        seller = None
        seller_el = soup.select_one('[itemprop="brand"]') or soup.select_one('.brand-name')
        if seller_el:
            seller = seller_el.get_text(strip=True)

        return ScrapingResult(
            status=self.normalize_status(indicators),
            price=price,
            seller=seller,
            product_title=title,
            raw_text=page_text[:500],
            store_availability=store_availability,
            url=url
        )

    def _check_store_availability(self, soup, page_text_lower):
        """Check for Virgin's in-store availability feature."""
        availability = {
            'has_store_check': False,
            'stores': [],
        }

        store_check_indicators = [
            'check availability in store',
            'check store availability',
            'available in store',
            'in-store availability',
            'find in store',
            'check in store',
        ]

        for indicator in store_check_indicators:
            if indicator in page_text_lower:
                availability['has_store_check'] = True
                break

        store_sections = (
            soup.select('.store-availability') or
            soup.select('[class*="store-check"]') or
            soup.select('[class*="StoreAvailability"]')
        )

        for section in store_sections:
            store_items = section.select('li') or section.select('.store-item')
            for item in store_items:
                item_text = item.get_text(' ', strip=True)
                is_available = (
                    'available' in item_text.lower() and
                    'unavailable' not in item_text.lower() and
                    'not available' not in item_text.lower()
                )
                availability['stores'].append({
                    'name': item_text[:100],
                    'available': is_available,
                })

        return availability if availability['has_store_check'] else None

    def _parse_json_ld(self, data, url):
        """Parse JSON-LD structured data."""
        if isinstance(data, list):
            data = data[0] if data else {}

        if data.get('@type') in ('Product', 'ProductGroup'):
            offers = data.get('offers', {})
            if isinstance(offers, list):
                offers = offers[0] if offers else {}

            availability = offers.get('availability', '')
            price = offers.get('price')
            status = 'IN_STOCK'
            if 'OutOfStock' in availability:
                status = 'OUT_OF_STOCK'
            elif 'InStock' in availability:
                status = 'IN_STOCK'

            return ScrapingResult(
                status=status,
                price=float(price) if price else None,
                product_title=data.get('name', ''),
                raw_text=json.dumps(data)[:500],
                url=url
            )

        return ScrapingResult(status='UNKNOWN', url=url)

    def _is_relevant(self, title, product_name):
        if not title or not product_name:
            return True
        title_lower = title.lower()
        keywords = [w for w in product_name.lower().split() if len(w) > 2]
        matches = sum(1 for kw in keywords if kw in title_lower)
        return matches >= max(1, len(keywords) * 0.4)
