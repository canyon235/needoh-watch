"""
Stock Normalization & AI Interpretation Layer.
Converts messy retailer page data into clean stock statuses,
and optionally uses AI to interpret ambiguous signals.
"""

import os
import re
import json

# AI is optional - works without OpenAI key
try:
    from openai import OpenAI
    HAS_OPENAI = bool(os.getenv('OPENAI_API_KEY'))
except ImportError:
    HAS_OPENAI = False


# ── Rule-based normalization ──

# Keywords that strongly indicate stock status
IN_STOCK_SIGNALS = [
    'add to cart', 'add to bag', 'add to basket', 'buy now',
    'in stock', 'available', 'ships from', 'delivered by',
    'express delivery', 'same day delivery', 'ready to ship',
]

OUT_OF_STOCK_SIGNALS = [
    'out of stock', 'sold out', 'currently unavailable',
    'not available', 'notify me when available', 'notify me',
    'no longer available', 'discontinued', 'coming soon',
    'temporarily out of stock', 'back order',
]

LOW_STOCK_SIGNALS = [
    'only \\d+ left', 'few left', 'limited stock', 'hurry',
    'almost gone', 'selling fast', 'low stock',
]


def normalize_from_text(raw_text, price=None):
    """
    Rule-based status determination from raw page text.
    Returns (status, confidence, reason).
    """
    if not raw_text:
        return ('UNKNOWN', 0.3, 'No text to analyze')

    text = raw_text.lower()

    # Check OUT_OF_STOCK first (stronger signal)
    for signal in OUT_OF_STOCK_SIGNALS:
        if signal in text:
            return ('OUT_OF_STOCK', 0.9, f'Found "{signal}" in page text')

    # Check LOW_STOCK
    for signal in LOW_STOCK_SIGNALS:
        if re.search(signal, text):
            return ('LOW_STOCK', 0.8, f'Found "{signal}" pattern in page text')

    # Check IN_STOCK
    for signal in IN_STOCK_SIGNALS:
        if signal in text:
            return ('IN_STOCK', 0.85, f'Found "{signal}" in page text')

    # Price as a signal
    if price and price > 0:
        return ('IN_STOCK', 0.6, 'Price visible, likely in stock')

    return ('UNKNOWN', 0.3, 'No clear stock signals found')


def normalize_result(scraping_result):
    """
    Take a ScrapingResult and produce a final normalized status.
    Combines the scraper's determination with additional rule-based analysis.
    """
    # If scraper already determined status with high confidence
    if scraping_result.status in ('IN_STOCK', 'OUT_OF_STOCK', 'LOW_STOCK'):
        return scraping_result.status

    # Try rule-based on raw text
    status, confidence, reason = normalize_from_text(
        scraping_result.raw_text, scraping_result.price)

    if confidence >= 0.7:
        return status

    # If we have AI available, use it for ambiguous cases
    if HAS_OPENAI and scraping_result.raw_text:
        ai_status = ai_interpret(scraping_result)
        if ai_status and ai_status != 'UNKNOWN':
            return ai_status

    return status


# ── AI interpretation for ambiguous cases ──

def ai_interpret(scraping_result):
    """Use AI to interpret ambiguous stock status from page text."""
    if not HAS_OPENAI:
        return None

    try:
        client = OpenAI()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "system",
                "content": (
                    "You analyze e-commerce page text to determine product stock status. "
                    "Respond with ONLY one of: IN_STOCK, LOW_STOCK, OUT_OF_STOCK, UNKNOWN. "
                    "Consider price visibility, add-to-cart buttons, availability messages, "
                    "and seller information."
                )
            }, {
                "role": "user",
                "content": (
                    f"Product page text from a UAE retailer:\n\n"
                    f"{scraping_result.raw_text[:800]}\n\n"
                    f"Price found: {scraping_result.price}\n"
                    f"Store: {scraping_result.url}\n\n"
                    f"What is the stock status?"
                )
            }],
            max_tokens=20,
            temperature=0,
        )

        answer = response.choices[0].message.content.strip().upper()
        if answer in ('IN_STOCK', 'LOW_STOCK', 'OUT_OF_STOCK', 'UNKNOWN'):
            return answer
        return None
    except Exception:
        return None


def generate_alert_summary(product_name, old_status, new_status, price=None,
                           store_name=None, url=None):
    """Generate a human-readable alert message."""
    if HAS_OPENAI:
        return _ai_alert_summary(product_name, old_status, new_status, price, store_name, url)
    return _template_alert_summary(product_name, old_status, new_status, price, store_name, url)


def _template_alert_summary(product_name, old_status, new_status, price=None,
                            store_name=None, url=None):
    """Template-based alert messages (no AI needed)."""
    price_text = f" at AED {price:.0f}" if price else ""
    store_text = f" on {store_name}" if store_name else ""

    if old_status == 'OUT_OF_STOCK' and new_status == 'IN_STOCK':
        return f"🟢 RESTOCK! {product_name} is back in stock{store_text}{price_text}!"

    if old_status == 'OUT_OF_STOCK' and new_status == 'LOW_STOCK':
        return f"🟡 {product_name} is back but LOW STOCK{store_text}{price_text}. Act fast!"

    if new_status == 'OUT_OF_STOCK':
        return f"🔴 {product_name} is now out of stock{store_text}."

    if new_status == 'LOW_STOCK':
        return f"🟡 {product_name} is running low{store_text}{price_text}."

    if new_status == 'IN_STOCK':
        return f"🟢 {product_name} is in stock{store_text}{price_text}."

    return f"ℹ️ {product_name} status changed to {new_status}{store_text}."


def _ai_alert_summary(product_name, old_status, new_status, price=None,
                      store_name=None, url=None):
    """AI-powered alert summary for richer notifications."""
    try:
        client = OpenAI()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "system",
                "content": (
                    "You write short, friendly notification messages about product stock changes "
                    "for a parent tracking NeeDoh fidget toys in the UAE for their child. "
                    "Keep it to 1-2 sentences. Use emojis. Be helpful and action-oriented."
                )
            }, {
                "role": "user",
                "content": (
                    f"Product: {product_name}\n"
                    f"Store: {store_name or 'Unknown'}\n"
                    f"Old status: {old_status} → New status: {new_status}\n"
                    f"Price: {'AED ' + str(price) if price else 'Unknown'}\n"
                    f"Write a notification message."
                )
            }],
            max_tokens=100,
            temperature=0.7,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return _template_alert_summary(product_name, old_status, new_status, price, store_name, url)


def generate_where_summary(product_name, listings, sightings):
    """Generate a 'where can I find this?' summary."""
    if HAS_OPENAI:
        return _ai_where_summary(product_name, listings, sightings)
    return _template_where_summary(product_name, listings, sightings)


def _template_where_summary(product_name, listings, sightings):
    """Template-based where-to-find summary."""
    lines = [f"📍 Where to find {product_name}:\n"]

    # Online listings
    in_stock = [l for l in listings if l.get('stock_status') == 'IN_STOCK']
    low_stock = [l for l in listings if l.get('stock_status') == 'LOW_STOCK']
    out_stock = [l for l in listings if l.get('stock_status') == 'OUT_OF_STOCK']

    if in_stock:
        lines.append("🟢 IN STOCK:")
        for l in in_stock:
            price_text = f" — AED {l['last_price']:.0f}" if l.get('last_price') else ""
            lines.append(f"  • {l['store_name']}{price_text}")

    if low_stock:
        lines.append("🟡 LOW STOCK:")
        for l in low_stock:
            price_text = f" — AED {l['last_price']:.0f}" if l.get('last_price') else ""
            lines.append(f"  • {l['store_name']}{price_text}")

    if out_stock:
        lines.append("🔴 OUT OF STOCK:")
        for l in out_stock:
            lines.append(f"  • {l['store_name']}")

    # Sightings
    if sightings:
        from data.database import get_confidence_label
        lines.append("\n👀 Recent sightings:")
        for s in sightings[:5]:
            location = s.get('mall_name') or s.get('store_name') or s.get('store_full_name', 'Unknown')
            confidence = get_confidence_label(s.get('confidence_score', 0))
            hours_ago = ''
            if s.get('reported_at'):
                from datetime import datetime
                try:
                    reported = datetime.fromisoformat(s['reported_at'])
                    delta = datetime.utcnow() - reported
                    hours = delta.total_seconds() / 3600
                    if hours < 1:
                        hours_ago = f" ({int(hours * 60)}m ago)"
                    elif hours < 24:
                        hours_ago = f" ({int(hours)}h ago)"
                    else:
                        hours_ago = f" ({int(hours / 24)}d ago)"
                except Exception:
                    pass
            lines.append(f"  • {location}{hours_ago} — Confidence: {confidence}")

    if not in_stock and not low_stock and not sightings:
        lines.append("No availability found right now. We'll alert you when it appears!")

    return '\n'.join(lines)


def _ai_where_summary(product_name, listings, sightings):
    """AI-powered where-to-find summary."""
    try:
        client = OpenAI()
        data = {
            'product': product_name,
            'listings': [{'store': l.get('store_name'), 'status': l.get('stock_status'),
                          'price': l.get('last_price')} for l in listings],
            'sightings': [{'location': s.get('mall_name') or s.get('store_full_name'),
                           'confidence': s.get('confidence_score'),
                           'reported_at': s.get('reported_at')} for s in sightings[:5]],
        }

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "system",
                "content": (
                    "You summarize product availability across UAE stores for a parent "
                    "looking for NeeDoh fidget toys. Be concise, use emojis, and give a "
                    "clear recommendation on the best option. Include prices in AED."
                )
            }, {
                "role": "user",
                "content": f"Availability data:\n{json.dumps(data, indent=2)}\n\nSummarize and recommend."
            }],
            max_tokens=200,
            temperature=0.5,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return _template_where_summary(product_name, listings, sightings)
