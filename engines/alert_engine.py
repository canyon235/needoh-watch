"""
Alert Engine - Triggers notifications on meaningful stock changes.
Only alerts on:
  - OUT → IN (restock)
  - Price drop below threshold
  - Store availability signal appears
  - Multiple offline sightings in same location
"""

import json
from datetime import datetime
from data.database import (
    get_subscriptions_for_product, was_alert_sent_recently,
    record_alert, get_db
)
from engines.normalizer import generate_alert_summary


class AlertEngine:
    """Evaluates stock changes and triggers alerts."""

    def __init__(self, notifier=None):
        self.notifier = notifier
        self.pending_alerts = []

    def evaluate_stock_change(self, listing, change_result):
        """
        Evaluate a stock status change and decide whether to alert.

        Args:
            listing: dict with product info (from get_listings_due_for_check)
            change_result: dict from update_listing_status with
                           changed, previous_status, new_status, old_price, new_price
        """
        if not change_result['changed']:
            return

        listing_id = listing['id']
        product_id = listing['product_id']
        product_name = f"{listing['canonical_name']}"
        if listing['variant']:
            product_name += f" ({listing['variant']})"
        store_name = listing['store_name']

        prev = change_result['previous_status']
        new = change_result['new_status']
        new_price = change_result['new_price']
        old_price = change_result['old_price']

        alerts_to_send = []

        # ── Restock alert (OUT → IN or OUT → LOW) ──
        if prev == 'OUT_OF_STOCK' and new in ('IN_STOCK', 'LOW_STOCK'):
            if not was_alert_sent_recently(listing_id, 'restock', hours=1):
                message = generate_alert_summary(
                    product_name, prev, new, new_price, store_name)
                alerts_to_send.append({
                    'type': 'restock',
                    'message': message,
                    'product_id': product_id,
                    'listing_id': listing_id,
                })

        # ── Went out of stock alert ──
        elif prev in ('IN_STOCK', 'LOW_STOCK') and new == 'OUT_OF_STOCK':
            if not was_alert_sent_recently(listing_id, 'out_of_stock', hours=2):
                message = generate_alert_summary(
                    product_name, prev, new, new_price, store_name)
                alerts_to_send.append({
                    'type': 'out_of_stock',
                    'message': message,
                    'product_id': product_id,
                    'listing_id': listing_id,
                })

        # ── Price drop alert ──
        if new_price and old_price and new_price < old_price:
            drop_pct = (old_price - new_price) / old_price * 100
            if drop_pct >= 10:  # Only alert on 10%+ drops
                if not was_alert_sent_recently(listing_id, 'price_drop', hours=4):
                    message = (
                        f"💰 Price drop! {product_name} on {store_name}: "
                        f"AED {old_price:.0f} → AED {new_price:.0f} "
                        f"({drop_pct:.0f}% off)"
                    )
                    alerts_to_send.append({
                        'type': 'price_drop',
                        'message': message,
                        'product_id': product_id,
                        'listing_id': listing_id,
                    })

        # ── Price threshold alerts ──
        if new_price:
            self._check_price_thresholds(
                product_id, product_name, store_name, new_price,
                listing_id, alerts_to_send)

        # Send all alerts
        for alert in alerts_to_send:
            self._send_alert(alert)

    def evaluate_sighting(self, sighting, product_name, sighting_count):
        """Evaluate a new sighting for alerting."""
        if sighting_count >= 2:
            location = sighting.get('mall_name') or sighting.get('store_name') or 'a store'
            city = sighting.get('city', 'Dubai')
            confidence_label = 'High' if sighting_count >= 3 else 'Medium'

            message = (
                f"👀 {sighting_count} users reported {product_name} "
                f"at {location} ({city}) today. "
                f"Confidence: {confidence_label}."
            )

            alert = {
                'type': 'sighting',
                'message': message,
                'product_id': sighting.get('product_id'),
                'sighting_id': sighting.get('id'),
            }
            self._send_alert(alert)

    def evaluate_store_availability(self, listing, store_availability):
        """Alert when Virgin's store availability check shows in-store stock."""
        if not store_availability or not store_availability.get('has_store_check'):
            return

        listing_id = listing['id']
        product_id = listing['product_id']
        product_name = listing['canonical_name']
        store_name = listing['store_name']

        if not was_alert_sent_recently(listing_id, 'store_available', hours=6):
            available_stores = [s for s in store_availability.get('stores', [])
                                if s.get('available')]

            if available_stores:
                store_list = ', '.join(s['name'][:50] for s in available_stores[:3])
                message = (
                    f"🏬 {product_name} may be available in-store! "
                    f"{store_name} shows availability at: {store_list}"
                )
            else:
                message = (
                    f"🏬 {store_name} shows in-store availability checking "
                    f"for {product_name}. Check their page for store details."
                )

            alert = {
                'type': 'store_available',
                'message': message,
                'product_id': product_id,
                'listing_id': listing_id,
            }
            self._send_alert(alert)

    def _check_price_thresholds(self, product_id, product_name, store_name,
                                price, listing_id, alerts_list):
        """Check if price is below any subscriber's max_price threshold."""
        subscribers = get_subscriptions_for_product(product_id)
        for sub in subscribers:
            if sub['max_price'] and price <= sub['max_price']:
                if not was_alert_sent_recently(listing_id, 'price_threshold', hours=6):
                    message = (
                        f"🎯 {product_name} is at AED {price:.0f} on {store_name} "
                        f"— under your AED {sub['max_price']:.0f} target!"
                    )
                    alerts_list.append({
                        'type': 'price_threshold',
                        'message': message,
                        'product_id': product_id,
                        'listing_id': listing_id,
                        'target_user': sub['user_id'],
                    })

    def _send_alert(self, alert):
        """Record alert in DB and send notification."""
        # Get subscribers for this product
        subscribers = []
        if alert.get('target_user'):
            subscribers = [alert['target_user']]
        elif alert.get('product_id'):
            subs = get_subscriptions_for_product(alert['product_id'])
            subscribers = [s['user_id'] for s in subs]

        # Record in DB
        record_alert(
            listing_id=alert.get('listing_id'),
            sighting_id=alert.get('sighting_id'),
            alert_type=alert['type'],
            message=alert['message'],
            sent_to=subscribers
        )

        # Send via notifier
        if self.notifier and subscribers:
            for user_id in subscribers:
                self.notifier.send(user_id, alert['message'])
        else:
            # Print to console if no notifier configured
            print(f"\n📢 ALERT: {alert['message']}")

        self.pending_alerts.append(alert)
