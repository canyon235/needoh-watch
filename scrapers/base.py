"""
Base scraper with shared logic for all store scrapers.
"""

import requests
import cloudscraper
import time
import re
import os
import random
import json
from bs4 import BeautifulSoup
from datetime import datetime

USER_AGENT = os.getenv("USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Upgrade-Insecure-Requests": "1",
}


class ScrapingResult:
    """Standardized result from any scraper."""

    def __init__(self, status='UNKNOWN', price=None, currency='AED',
                 seller=None, raw_text='', store_availability=None,
                 product_title=None, error=None, url=None,
                 delivery_estimate=None):
        self.status = status          # IN_STOCK, LOW_STOCK, OUT_OF_STOCK, UNKNOWN
        self.price = price            # float or None
        self.currency = currency
        self.seller = seller
        self.raw_text = raw_text      # Raw page text for AI analysis
        self.store_availability = store_availability  # Dict for offline stores
        self.product_title = product_title
        self.error = error
        self.url = url
        self.delivery_estimate = delivery_estimate  # e.g. "Tomorrow", "Wed, Apr 23"
        self.checked_at = datetime.utcnow().isoformat()

    def to_dict(self):
        return {
            'status': self.status,
            'price': self.price,
            'currency': self.currency,
            'seller': self.seller,
            'raw_text': self.raw_text[:500],
            'store_availability': self.store_availability,
            'product_title': self.product_title,
            'error': self.error,
            'url': self.url,
            'checked_at': self.checked_at,
        }

    def __repr__(self):
        return f"ScrapingResult(status={self.status}, price={self.price}, error={self.error})"


class BaseScraper:
    """Base class for all store scrapers."""

    STORE_NAME = "base"

    def __init__(self):
        # Use cloudscraper instead of plain requests — handles Cloudflare
        # and basic anti-bot protection automatically. Drop-in replacement.
        self.session = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False}
        )
        self.session.headers.update(HEADERS)

    def fetch_page(self, url, timeout=15):
        """Fetch a page with retries and error handling."""
        for attempt in range(3):
            try:
                response = self.session.get(url, timeout=timeout)
                response.raise_for_status()
                return response.text
            except requests.RequestException as e:
                if attempt < 2:
                    # Random delay between 2-5 seconds
                    delay = random.uniform(2, 5)
                    time.sleep(delay)
                    continue
                return None

    def fetch_json(self, url, timeout=10, headers=None):
        """Fetch JSON from an API endpoint with retries."""
        combined_headers = {**self.session.headers}
        combined_headers.update({
            'Accept': 'application/json',
        })
        if headers:
            combined_headers.update(headers)

        for attempt in range(3):
            try:
                response = self.session.get(url, timeout=timeout, headers=combined_headers)
                response.raise_for_status()
                return response.json()
            except requests.RequestException as e:
                if attempt < 2:
                    # Random delay between 2-5 seconds
                    delay = random.uniform(2, 5)
                    time.sleep(delay)
                    continue
                return None

    def fetch_with_cookies(self, url, base_domain, timeout=15):
        """
        Fetch a page after priming cookies from the base domain.
        This helps avoid blocks by simulating a real user session.
        """
        try:
            # First, visit the base domain to get cookies
            self.session.get(base_domain, timeout=10)
            time.sleep(random.uniform(1, 3))
        except requests.RequestException:
            pass  # Ignore errors on the primer request

        # Now fetch the actual page
        return self.fetch_page(url, timeout=timeout)

    def parse_price(self, text):
        """Extract price from messy text. Returns float or None."""
        if not text:
            return None
        # Remove currency symbols and clean up
        text = text.replace(',', '').strip()
        # Match patterns like "AED 49.00", "49.00 AED", "49", "AED49"
        patterns = [
            r'(?:AED|aed|Aed)\s*(\d+\.?\d*)',
            r'(\d+\.?\d*)\s*(?:AED|aed|Aed)',
            r'(\d+\.?\d*)',
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    price = float(match.group(1))
                    if 1 < price < 5000:  # Sanity check
                        return price
                except ValueError:
                    continue
        return None

    def check_stock(self, url, product_name=None):
        """Override in subclasses. Returns ScrapingResult."""
        raise NotImplementedError

    def normalize_status(self, indicators):
        """
        Given a dict of stock indicators, determine the status.
        indicators can include:
        - add_to_cart: bool
        - buy_now: bool
        - out_of_stock_text: bool
        - price_visible: bool
        - currently_unavailable: bool
        - limited_stock: bool
        """
        if indicators.get('currently_unavailable') or indicators.get('out_of_stock_text'):
            if not indicators.get('add_to_cart') and not indicators.get('buy_now'):
                return 'OUT_OF_STOCK'

        if indicators.get('add_to_cart') or indicators.get('buy_now'):
            if indicators.get('limited_stock'):
                return 'LOW_STOCK'
            return 'IN_STOCK'

        if indicators.get('price_visible'):
            return 'IN_STOCK'  # If price is visible, likely in stock

        return 'UNKNOWN'
