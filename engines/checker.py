"""
Stock Checker - Orchestrates the scraping, normalization, and alerting pipeline.
Runs as the main scheduled job.
"""

import time
from datetime import datetime

from data.database import (
    get_listings_due_for_check, update_listing_status, log_check
)
from scrapers.amazon_ae import AmazonAEScraper
from scrapers.noon_uae import NoonScraper
from scrapers.desertcart_ae import DesertcartScraper
from scrapers.trendyol import TrendyolScraper
from engines.normalizer import normalize_result
from engines.alert_engine import AlertEngine
from engines.offline_engine import OfflineEngine

# Playwright fallback for JS-heavy sites
try:
    from scrapers.playwright_scraper import PlaywrightScraper, HAS_PLAYWRIGHT
except ImportError:
    HAS_PLAYWRIGHT = False


class StockChecker:
    """Main stock checking orchestrator."""

    def __init__(self, notifier=None):
        self.scrapers = {
            'Amazon.ae': AmazonAEScraper(),
            'Noon': NoonScraper(),
            'Desertcart': DesertcartScraper(),
            'Trendyol': TrendyolScraper(),
        }
        # Playwright fallback for JS-heavy sites (Desertcart=Next.js, Trendyol=Cloudflare)
        self.playwright_scraper = PlaywrightScraper() if HAS_PLAYWRIGHT else None
        self.playwright_stores = {'Noon', 'Desertcart', 'Trendyol'}
        self.alert_engine = AlertEngine(notifier=notifier)
        self.offline_engine = OfflineEngine(alert_engine=self.alert_engine)
        self.stats = {
            'checks': 0,
            'changes': 0,
            'errors': 0,
            'alerts': 0,
        }

    def run_check_cycle(self):
        """Run one complete check cycle for all due listings."""
        listings = get_listings_due_for_check()

        if not listings:
            return self.stats

        timestamp = datetime.utcnow().strftime('%H:%M:%S')
        print(f"\n[{timestamp}] Checking {len(listings)} listings...")

        for listing in listings:
            self._check_one(listing)
            # Small delay between requests to be respectful
            time.sleep(1)

        # Decay old sightings
        self.offline_engine.decay_old_sightings()

        return self.stats

    def _check_one(self, listing):
        """Check a single listing."""
        store_name = listing['store_name']
        product_name = listing['canonical_name']
        if listing['variant']:
            product_name += f" ({listing['variant']})"

        scraper = self.scrapers.get(store_name)
        if not scraper:
            print(f"  ⚠ No scraper for store: {store_name}")
            return

        start_time = time.time()

        try:
            # Scrape (requests first, Playwright fallback for JS-heavy sites)
            result = scraper.check_stock(listing['url'], product_name)

            # If result is UNKNOWN and Playwright is available, retry with browser
            # (also retry when there's an error like Cloudflare block or JS-rendering failure)
            if (result.status == 'UNKNOWN'
                    and self.playwright_scraper
                    and store_name in self.playwright_stores):
                print(f"    ↻ Retrying {store_name} with Playwright...")
                pw_result = self.playwright_scraper.check_stock(listing['url'], product_name)
                if pw_result.status != 'UNKNOWN':
                    result = pw_result

            duration_ms = int((time.time() - start_time) * 1000)

            # Normalize
            final_status = normalize_result(result)

            # Update database
            change = update_listing_status(
                listing_id=listing['id'],
                status=final_status,
                price=result.price,
                raw_text=result.raw_text,
                seller=result.seller,
                error=result.error,
                product_url=result.url,
                delivery_estimate=getattr(result, 'delivery_estimate', None)
            )

            # Log the check
            log_check(
                listing_id=listing['id'],
                status=final_status,
                price=result.price,
                raw_html=result.raw_text,
                duration_ms=duration_ms,
                error=result.error
            )

            self.stats['checks'] += 1

            # Status indicator
            status_icons = {
                'IN_STOCK': '🟢',
                'LOW_STOCK': '🟡',
                'OUT_OF_STOCK': '🔴',
                'UNKNOWN': '⚪',
            }
            icon = status_icons.get(final_status, '⚪')
            price_text = f" AED {result.price:.0f}" if result.price else ""
            changed_tag = " ← CHANGED!" if change['changed'] else ""

            print(f"  {icon} {product_name} @ {store_name}: "
                  f"{final_status}{price_text} ({duration_ms}ms){changed_tag}")

            # Evaluate for alerts
            if change['changed']:
                self.stats['changes'] += 1
                self.alert_engine.evaluate_stock_change(
                    listing=dict(listing),
                    change_result=change
                )

            # Check store availability (Virgin)
            if result.store_availability:
                self.alert_engine.evaluate_store_availability(
                    listing=dict(listing),
                    store_availability=result.store_availability
                )
                # Also record as offline signal
                self.offline_engine.record_store_page_signal(
                    product_id=listing['product_id'],
                    store_id=listing['store_id'],
                    store_name=store_name,
                    available=result.store_availability.get('has_store_check', False)
                )

        except Exception as e:
            self.stats['errors'] += 1
            duration_ms = int((time.time() - start_time) * 1000)
            print(f"  ✗ Error checking {product_name} @ {store_name}: {e}")

            update_listing_status(
                listing_id=listing['id'],
                status='UNKNOWN',
                error=str(e)
            )
            log_check(
                listing_id=listing['id'],
                status='UNKNOWN',
                duration_ms=duration_ms,
                error=str(e)
            )

    def check_single_product(self, product_name):
        """Check all listings for a specific product (on-demand)."""
        from data.database import find_product, get_listings_for_product

        products = find_product(product_name)
        if not products:
            print(f"Product not found: {product_name}")
            return []

        results = []
        for product in products:
            listings = get_listings_for_product(product['id'])
            for listing in listings:
                self._check_one(listing)
                results.append(dict(listing))
                time.sleep(0.5)

        return results

    def get_stats(self):
        return self.stats

    def reset_stats(self):
        self.stats = {'checks': 0, 'changes': 0, 'errors': 0, 'alerts': 0}
