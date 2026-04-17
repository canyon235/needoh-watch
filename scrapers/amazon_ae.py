"""
Amazon.ae scraper for NeeDoh products.
Handles search results pages and individual product pages.
"""

import re
import time
from bs4 import BeautifulSoup
from scrapers.base import BaseScraper, ScrapingResult


class AmazonAEScraper(BaseScraper):
    STORE_NAME = "Amazon.ae"

    def check_stock(self, url, product_name=None):
        """Check stock status on Amazon.ae.
        Strategy: direct fetch → proxy fetch (bypasses datacenter IP blocks).
        """
        start = time.time()

        # Try direct fetch first
        html = self.fetch_page(url)

        # If direct fails, try through Cloudflare Worker proxy
        if not html:
            proxy_resp = self.proxy_get(url, timeout=20)
            if proxy_resp and proxy_resp.status_code == 200 and len(proxy_resp.text) > 1000:
                html = proxy_resp.text

        if not html:
            return ScrapingResult(
                status='UNKNOWN', error='Failed to fetch page (direct + proxy)', url=url)

        soup = BeautifulSoup(html, 'lxml')
        duration = int((time.time() - start) * 1000)

        # Determine if this is a search page or product page
        if '/s?' in url or '/s/' in url:
            return self._parse_search_results(soup, url, product_name, html)
        else:
            return self._parse_product_page(soup, url, html)

    def _parse_search_results(self, soup, url, product_name, html):
        """Parse Amazon search results page."""
        results = []
        product_cards = soup.select('[data-component-type="s-search-result"]')

        if not product_cards:
            product_cards = soup.select('.s-result-item[data-asin]')

        if not product_cards:
            no_results = soup.find(string=re.compile(r'no results|0 results|did not match', re.I))
            if no_results:
                return ScrapingResult(
                    status='OUT_OF_STOCK',
                    raw_text='No search results found on Amazon.ae',
                    url=url
                )
            return ScrapingResult(
                status='UNKNOWN',
                raw_text=self._extract_relevant_text(soup),
                url=url
            )

        best_result = None
        for card in product_cards[:5]:
            result = self._parse_product_card(card)
            if result and self._is_relevant(result, product_name):
                if best_result is None or (result.get('price') and not best_result.get('price')):
                    best_result = result

        # If no relevant match found, report OUT_OF_STOCK — do NOT use unrelated results
        if not best_result:
            return ScrapingResult(
                status='OUT_OF_STOCK',
                raw_text=f'No matching "{product_name}" found in Amazon.ae search results',
                url=url
            )

        if best_result:
            # Build specific product URL from ASIN if available
            product_url = best_result.get('product_url') or url
            return ScrapingResult(
                status=best_result.get('status', 'UNKNOWN'),
                price=best_result.get('price'),
                seller=best_result.get('seller'),
                product_title=best_result.get('title'),
                raw_text=best_result.get('raw_text', ''),
                url=product_url,
                delivery_estimate=best_result.get('delivery')
            )

        return ScrapingResult(status='UNKNOWN', raw_text=self._extract_relevant_text(soup), url=url)

    def _parse_product_card(self, card):
        """Parse a single product card from search results."""
        result = {}
        title_el = card.select_one('h2 a span') or card.select_one('.a-text-normal')
        result['title'] = title_el.get_text(strip=True) if title_el else ''

        # Extract specific product URL from the card link
        link_el = card.select_one('h2 a') or card.select_one('a.a-link-normal[href*="/dp/"]')
        if link_el and link_el.get('href'):
            href = link_el['href']
            if href.startswith('/'):
                href = f"https://www.amazon.ae{href}"
            result['product_url'] = href

        price_el = card.select_one('.a-price .a-offscreen') or card.select_one('.a-price-whole')
        if price_el:
            result['price'] = self.parse_price(price_el.get_text())
        indicators = {
            'price_visible': result.get('price') is not None,
            'out_of_stock_text': False,
            'currently_unavailable': False,
            'add_to_cart': False,
        }
        card_text = card.get_text(' ', strip=True).lower()
        result['raw_text'] = card_text[:300]
        if 'currently unavailable' in card_text:
            indicators['currently_unavailable'] = True
        if 'out of stock' in card_text:
            indicators['out_of_stock_text'] = True
        if 'add to cart' in card_text or 'add to basket' in card_text:
            indicators['add_to_cart'] = True
        result['status'] = self.normalize_status(indicators)
        seller_el = card.select_one('.a-row.a-size-base .a-color-secondary')
        if seller_el:
            result['seller'] = seller_el.get_text(strip=True)

        # Extract delivery estimate from card text
        delivery_match = re.search(
            r'(?:get it|delivery|arrives?|free delivery)\s*(tomorrow|today|(?:sun|mon|tue|wed|thu|fri|sat)\w*,?\s*\w+\s*\d+|(?:\d+\s*-\s*\d+\s*(?:days?|business)))',
            card_text, re.I
        )
        if delivery_match:
            result['delivery'] = delivery_match.group(0).strip()

        return result

    def _parse_product_page(self, soup, url, html):
        """Parse an individual Amazon product page."""
        indicators = {
            'add_to_cart': False, 'buy_now': False,
            'out_of_stock_text': False, 'currently_unavailable': False,
            'price_visible': False, 'limited_stock': False,
        }
        title_el = soup.select_one('#productTitle')
        title = title_el.get_text(strip=True) if title_el else ''
        price = None
        price_selectors = [
            '#priceblock_ourprice', '#priceblock_dealprice',
            '.a-price .a-offscreen', '#corePrice_feature_div .a-offscreen',
            '#price_inside_buybox', '.apexPriceToPay .a-offscreen'
        ]
        for sel in price_selectors:
            el = soup.select_one(sel)
            if el:
                price = self.parse_price(el.get_text())
                if price:
                    indicators['price_visible'] = True
                    break
        add_cart = soup.select_one('#add-to-cart-button')
        buy_now = soup.select_one('#buy-now-button')
        if add_cart: indicators['add_to_cart'] = True
        if buy_now: indicators['buy_now'] = True
        page_text = soup.get_text(' ', strip=True).lower()
        if 'currently unavailable' in page_text: indicators['currently_unavailable'] = True
        if 'out of stock' in page_text: indicators['out_of_stock_text'] = True
        if re.search(r'only \d+ left', page_text): indicators['limited_stock'] = True
        seller = None
        seller_el = soup.select_one('#sellerProfileTriggerId') or soup.select_one('#merchant-info')
        if seller_el: seller = seller_el.get_text(strip=True)
        status = self.normalize_status(indicators)
        return ScrapingResult(status=status, price=price, seller=seller,
            product_title=title, raw_text=page_text[:500], url=url)

    def _is_needoh_brand(self, title):
        """Check if a product is genuinely a NeeDoh/Schylling brand item."""
        if not title:
            return False
        t = title.lower()
        return ('needoh' in t or 'nee doh' in t or 'nee-doh' in t
                or 'schylling' in t or 'nee doh' in t.replace('-', ' '))

    def _is_relevant(self, result, product_name):
        """Check if a search result matches the specific product we're looking for.
        Must be NeeDoh brand AND match the distinctive keyword."""
        if not product_name or not result.get('title'):
            return False  # Require explicit match
        title_lower = result['title'].lower()
        name_lower = product_name.lower()

        # MUST be NeeDoh/Schylling brand
        if not self._is_needoh_brand(result['title']):
            return False

        # Remove common generic words to find the distinctive keywords
        generic = {'needoh', 'nee', 'doh', 'schylling', 'stress', 'ball', 'toy', 'fidget', 'sensory'}
        keywords = [w for w in name_lower.split() if len(w) > 2 and w not in generic]

        if not keywords:
            # Product name is only generic words (e.g. "NeeDoh Blob")
            return True  # Brand check already passed above

        # ALL distinctive keywords must appear in the title
        matches = sum(1 for kw in keywords if kw in title_lower)
        return matches >= len(keywords) * 0.8

    def _extract_relevant_text(self, soup):
        text = soup.get_text(' ', strip=True)
        lower = text.lower()
        idx = lower.find('needoh')
        if idx == -1: idx = lower.find('nee doh')
        if idx >= 0:
            start = max(0, idx - 100)
            return text[start:start + 500]
        return text[:500]
