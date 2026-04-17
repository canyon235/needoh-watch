"""
Scraper for Ubuy UAE (ubuy.ae) - International shopping platform.
Uses ScraperAPI for reliable fetching since Ubuy blocks datacenter IPs
and the old two-step CSRF approach timed out on Render.
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

# Approximate conversion rates to AED
KWD_TO_AED = 12.0   # 1 KWD ≈ 12 AED
USD_TO_AED = 3.67    # 1 USD ≈ 3.67 AED


class UbuyScraper(BaseScraper):
    """Scraper for Ubuy UAE using ScraperAPI."""

    STORE_NAME = "Ubuy"
    BASE_URL = "https://www.ubuy.ae"

    def check_stock(self, url, product_name=None):
        """
        Check stock for a NeeDoh product on Ubuy.
        Strategy:
          1. ScraperAPI with render=true (JS-rendered)
          2. Proxy fallback
          3. Direct fetch fallback
        """
        try:
            # Try ScraperAPI first (most reliable)
            if SCRAPER_API_KEY:
                result = self._scraperapi_fetch(url, product_name)
                if result and result.status != 'UNKNOWN':
                    return result

            # Fallback: proxy
            html = None
            proxy_resp = self.proxy_get(url, timeout=20)
            if proxy_resp and proxy_resp.status_code == 200 and len(proxy_resp.text) > 2000:
                html = proxy_resp.text

            # Fallback: direct
            if not html:
                html = self.fetch_page(url, timeout=15)

            if html and len(html) > 2000:
                soup = BeautifulSoup(html, 'html.parser')
                if '/search' in url or '/s/' in url:
                    return self._parse_search_page(soup, html, url, product_name)
                else:
                    return self._parse_product_page(soup, html, url, product_name)

            return ScrapingResult(
                status='UNKNOWN',
                error='Failed to fetch Ubuy page (all methods failed)',
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

    def _scraperapi_fetch(self, url, product_name):
        """Fetch Ubuy via ScraperAPI with JS rendering."""
        try:
            scraper_url = (
                f"https://api.scraperapi.com/"
                f"?api_key={SCRAPER_API_KEY}"
                f"&url={quote_plus(url)}"
                f"&render=true"
                f"&country_code=ae"
            )

            max_retries = 2
            response = None
            for attempt in range(max_retries + 1):
                response = requests.get(scraper_url, timeout=80)
                if response.status_code == 499 and attempt < max_retries:
                    wait = 3 + attempt * 2
                    print(f"  Ubuy ScraperAPI 499 — retrying in {wait}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait)
                    continue
                break

            if not response or response.status_code != 200:
                print(f"  Ubuy ScraperAPI returned {response.status_code if response else 'no response'}")
                return None

            html = response.text
            if len(html) < 2000:
                return None

            soup = BeautifulSoup(html, 'html.parser')

            if '/search' in url or '/s/' in url:
                return self._parse_search_page(soup, html, url, product_name)
            else:
                return self._parse_product_page(soup, html, url, product_name)

        except requests.Timeout:
            print("  Ubuy ScraperAPI timed out")
            return None
        except Exception as e:
            print(f"  Ubuy ScraperAPI error: {e}")
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

        # Look for product containers
        products = soup.find_all('div', class_=re.compile(r'product-card|product-item|prd-card|listing-product', re.I))
        if not products:
            products = soup.find_all('div', class_=re.compile(r'product', re.I))

        for item in products[:15]:
            item_text = item.get_text(' ', strip=True)

            if not self._is_relevant(item_text, product_name):
                continue

            # Extract title
            title_elem = item.find(['h3', 'h2']) or item.find('a', class_=re.compile(r'title|name|product-title', re.I))
            if not title_elem:
                title_elem = item.find('a', href=True)
            title = title_elem.get_text(strip=True) if title_elem else product_name

            # Extract price
            price = self._extract_price(item)

            # Extract URL
            link = item.find('a', href=True)
            product_url = link['href'] if link else url
            if product_url and not product_url.startswith('http'):
                product_url = f"{self.BASE_URL}{product_url}"

            # Check stock
            item_lower = item_text.lower()
            out_of_stock = 'out of stock' in item_lower or 'unavailable' in item_lower

            # Extract delivery
            delivery = self._extract_delivery_text(item, item_lower)

            return ScrapingResult(
                status='OUT_OF_STOCK' if out_of_stock else ('IN_STOCK' if price else 'UNKNOWN'),
                price=price,
                currency='AED',
                seller='Ubuy',
                product_title=title,
                url=product_url,
                raw_text=item_text[:500],
                delivery_estimate=delivery
            )

        # No matching product found
        return ScrapingResult(
            status='OUT_OF_STOCK',
            url=url,
            product_title=product_name,
            raw_text='No matching NeeDoh product found in Ubuy search'
        )

    def _parse_product_page(self, soup, html, url, product_name):
        """Parse a single Ubuy product page."""
        page_text = soup.get_text(' ', strip=True).lower()

        # Extract title from h1
        title_elem = soup.find('h1')
        title = title_elem.get_text(strip=True) if title_elem else product_name

        # Extract price
        price = self._extract_price(soup)

        # Extract delivery estimate
        delivery = self._extract_delivery_text(soup, page_text)

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
                                status='IN_STOCK', price=price, currency='AED',
                                seller='Ubuy', product_title=title, url=url,
                                raw_text=page_text[:500], delivery_estimate=delivery
                            )
                        elif 'OutOfStock' in avail:
                            return ScrapingResult(
                                status='OUT_OF_STOCK', price=price, currency='AED',
                                seller='Ubuy', product_title=title, url=url,
                                raw_text=page_text[:500], delivery_estimate=delivery
                            )
            except (json.JSONDecodeError, ValueError, TypeError):
                continue

        # Check stock indicators
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
            delivery_estimate=delivery
        )

    def _extract_price(self, soup_or_elem):
        """Extract price from a page element, converting KWD/USD to AED."""
        all_text = soup_or_elem.get_text(' ', strip=True)

        # Try AED first
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

        # Try KWD → convert to AED
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
                        return round(kwd_price * KWD_TO_AED, 2)
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
                        return round(usd_price * USD_TO_AED, 2)
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

    def _extract_delivery_text(self, elem, text_lower):
        """Extract delivery estimate from Ubuy page."""
        patterns = [
            r'(?:estimated delivery|delivery by|arrives?|ships? in|delivered? by)\s*[:\-]?\s*(.{5,60}?)(?:\.|<|$)',
            r'(?:get it by|expected delivery)\s*[:\-]?\s*(.{5,60}?)(?:\.|<|$)',
            r'(\d+\s*-\s*\d+\s*(?:business\s*)?days?)',
            r'(free shipping.*?(?:\d+\s*days?|tomorrow|today))',
        ]
        for pattern in patterns:
            match = re.search(pattern, text_lower, re.I)
            if match:
                return match.group(1).strip()[:80]

        delivery_elem = elem.find(['div', 'span', 'p'], class_=re.compile(r'delivery|shipping|dispatch', re.I))
        if delivery_elem:
            text = delivery_elem.get_text(strip=True)
            if len(text) < 100:
                return text

        return None

    def _is_relevant(self, text, product_name):
        """Check if text is relevant to a NeeDoh product."""
        if not text or not product_name:
            return True

        text_lower = text.lower()
        if 'needoh' not in text_lower and 'nee doh' not in text_lower and 'nee-doh' not in text_lower and 'schylling' not in text_lower:
            return False

        return True
