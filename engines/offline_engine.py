"""
Offline Availability Engine.
Manages community sightings, store-page availability signals,
and confidence scoring for offline/in-store stock.
"""

from datetime import datetime, timedelta
from data.database import (
    add_sighting, get_recent_sightings, find_product,
    get_store_by_name, get_db, get_confidence_label,
    compute_sighting_confidence
)


class OfflineEngine:
    """Manages offline availability signals and community sightings."""

    def __init__(self, alert_engine=None):
        self.alert_engine = alert_engine

    def report_sighting(self, product_query, store_name=None, mall_name=None,
                        city='Dubai', reporter_id=None, reporter_name=None,
                        photo_url=None, notes=None):
        """
        Process a user-submitted sighting.
        Returns (success, message, confidence_score).
        """
        # Find the product
        products = find_product(product_query)
        if not products:
            return (False, f"Could not find a product matching '{product_query}'. "
                          f"Try a different name.", 0)

        product = products[0]  # Best match
        product_id = product['id']
        product_name = product['canonical_name']
        if product['variant']:
            product_name += f" ({product['variant']})"

        # Find the store if specified
        store_id = None
        if store_name:
            store = get_store_by_name(store_name)
            if store:
                store_id = store['id']

        # Add the sighting
        confidence = add_sighting(
            product_id=product_id,
            store_id=store_id,
            store_name=store_name,
            mall_name=mall_name,
            city=city,
            reporter_id=reporter_id,
            reporter_name=reporter_name,
            photo_url=photo_url,
            notes=notes,
            source='user'
        )

        confidence_label = get_confidence_label(confidence)

        # Check if this triggers an alert (multiple sightings)
        recent = get_recent_sightings(product_id, hours=24)
        same_location = [s for s in recent
                         if (s['mall_name'] == mall_name and mall_name)
                         or (s['store_id'] == store_id and store_id)]

        if self.alert_engine and len(same_location) >= 2:
            self.alert_engine.evaluate_sighting(
                sighting={
                    'product_id': product_id,
                    'mall_name': mall_name,
                    'store_name': store_name,
                    'city': city,
                },
                product_name=product_name,
                sighting_count=len(same_location)
            )

        location = mall_name or store_name or city
        message = (
            f"✅ Sighting recorded! {product_name} at {location}. "
            f"Confidence: {confidence_label} ({confidence}/100)."
        )

        if len(same_location) > 1:
            message += f"\n📊 {len(same_location)} total reports at this location today."

        return (True, message, confidence)

    def record_store_page_signal(self, product_id, store_id, store_name,
                                 available=True, mall_name=None):
        """Record an availability signal from a store's web page."""
        if available:
            add_sighting(
                product_id=product_id,
                store_id=store_id,
                store_name=store_name,
                mall_name=mall_name,
                source='store_page'
            )

    def record_delivery_proxy(self, product_id, store_id, store_name, city='Dubai'):
        """Record a delivery/fulfillment proxy signal."""
        add_sighting(
            product_id=product_id,
            store_id=store_id,
            store_name=store_name,
            city=city,
            source='delivery_proxy'
        )

    def get_offline_status(self, product_query):
        """
        Get the current offline availability status for a product.
        Returns (product_name, sightings_summary, overall_confidence).
        """
        products = find_product(product_query)
        if not products:
            return (None, "Product not found.", 0)

        product = products[0]
        product_id = product['id']
        product_name = product['canonical_name']
        if product['variant']:
            product_name += f" ({product['variant']})"

        # Get recent sightings
        sightings = get_recent_sightings(product_id, hours=48)

        if not sightings:
            return (product_name, "No recent sightings in the last 48 hours.", 0)

        # Group by location
        locations = {}
        for s in sightings:
            loc = s['mall_name'] or s['store_full_name'] or s['store_name'] or 'Unknown'
            if loc not in locations:
                locations[loc] = {
                    'count': 0,
                    'latest': s['reported_at'],
                    'best_confidence': s['confidence_score'],
                    'source': s['source'],
                    'has_photo': False,
                }
            locations[loc]['count'] += 1
            if s['confidence_score'] > locations[loc]['best_confidence']:
                locations[loc]['best_confidence'] = s['confidence_score']
            if s['photo_url']:
                locations[loc]['has_photo'] = True

        # Build summary
        lines = []
        overall_confidence = 0
        for loc, data in sorted(locations.items(),
                                key=lambda x: x[1]['best_confidence'], reverse=True):
            conf_label = get_confidence_label(data['best_confidence'])
            source_tag = ""
            if data['source'] == 'store_page':
                source_tag = " [store page]"
            elif data['source'] == 'delivery_proxy':
                source_tag = " [delivery signal]"

            photo_tag = " 📷" if data['has_photo'] else ""
            count_tag = f" ({data['count']} reports)" if data['count'] > 1 else ""

            # Time since latest report
            try:
                reported = datetime.fromisoformat(data['latest'])
                delta = datetime.utcnow() - reported
                hours = delta.total_seconds() / 3600
                if hours < 1:
                    time_tag = f"{int(hours * 60)}m ago"
                elif hours < 24:
                    time_tag = f"{int(hours)}h ago"
                else:
                    time_tag = f"{int(hours / 24)}d ago"
            except Exception:
                time_tag = "recently"

            lines.append(
                f"  📍 {loc}: {conf_label} confidence{count_tag} "
                f"— {time_tag}{source_tag}{photo_tag}"
            )

            if data['best_confidence'] > overall_confidence:
                overall_confidence = data['best_confidence']

        summary = f"👀 Offline sightings for {product_name}:\n" + '\n'.join(lines)
        return (product_name, summary, overall_confidence)

    def decay_old_sightings(self):
        """
        Reduce confidence of old unconfirmed sightings.
        Run this periodically (e.g., every hour).
        """
        cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()
        with get_db() as conn:
            conn.execute("""
                UPDATE sightings
                SET confidence_score = MAX(0, confidence_score - 20)
                WHERE reported_at < ?
                  AND confidence_score > 0
                  AND confirmed_count <= 1
            """, (cutoff,))
            updated = conn.execute("SELECT changes()").fetchone()[0]
            if updated > 0:
                print(f"  ↘ Decayed confidence for {updated} old sightings")
