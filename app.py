#!/usr/bin/env python3
"""
NeeDoh Watch UAE — Web Application
Flask-based web dashboard + API for stock monitoring.

Usage:
    python app.py                  # Start web server on port 5000
    python app.py --port 8080      # Custom port
    python app.py --seed            # Seed database before starting
"""

import sys
import os

# Force unbuffered output so Render logs show checker progress in real time
os.environ['PYTHONUNBUFFERED'] = '1'

import json
import threading
import time
import argparse
import requests as http_requests
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, jsonify, request, render_template_string

from data.database import (
    init_db, get_all_products, get_all_stores, find_product,
    get_listings_for_product, get_product_summary, get_dashboard_data,
    add_subscription, get_user_subscriptions, remove_subscription,
    get_recent_sightings, get_confidence_label, get_all_active_listings,
    get_db
)
from data.seed import seed_all
from engines.checker import StockChecker
from engines.normalizer import generate_where_summary
from engines.offline_engine import OfflineEngine
from notifications.notifier import Notifier

app = Flask(__name__)

# Global checker and notifier
notifier = Notifier()
checker = StockChecker(notifier=notifier)
offline_engine = OfflineEngine(alert_engine=checker.alert_engine)

# Background check thread
bg_thread = None
bg_running = False


# ─── HTML Dashboard (served as single page) ───

@app.route('/')
def dashboard():
    return render_template_string(DASHBOARD_HTML)


# ─── API Endpoints ───

@app.route('/api/health')
def api_health():
    """Health check endpoint — also used for self-ping to keep Render alive."""
    return jsonify({'status': 'ok', 'bg_running': bg_running})


@app.route('/api/dashboard')
def api_dashboard():
    """Get full dashboard data."""
    products = get_dashboard_data()
    # Get recent sightings count per product
    for p in products:
        sightings = get_recent_sightings(p['id'], hours=24)
        p['sighting_count_24h'] = len(sightings)
    return jsonify({'products': products, 'timestamp': datetime.utcnow().isoformat()})


@app.route('/api/products')
def api_products():
    products = get_all_products()
    return jsonify([dict(p) for p in products])


@app.route('/api/stores')
def api_stores():
    stores = get_all_stores()
    return jsonify([dict(s) for s in stores])


@app.route('/api/product/<int:product_id>')
def api_product_detail(product_id):
    summary = get_product_summary(product_id)
    if not summary['product']:
        return jsonify({'error': 'Product not found'}), 404
    return jsonify(summary)


@app.route('/api/where/<query>')
def api_where(query):
    products = find_product(query)
    if not products:
        return jsonify({'error': f'No product matching "{query}"'}), 404

    product = products[0]
    pid = product['id']
    pname = product['canonical_name']
    if product['variant']:
        pname += f" ({product['variant']})"

    summary = get_product_summary(pid)
    text = generate_where_summary(pname, summary['listings'], summary['sightings'])
    return jsonify({
        'product': pname,
        'summary_text': text,
        'listings': summary['listings'],
        'sightings': summary['sightings'],
    })


@app.route('/api/track', methods=['POST'])
def api_track():
    data = request.json or {}
    product_query = data.get('product', '')
    max_price = data.get('max_price')
    user_id = data.get('user_id', 'web_user')
    email = data.get('email', os.getenv('EMAIL_RECIPIENTS', '').split(',')[0].strip())

    products = find_product(product_query)
    if not products:
        return jsonify({'error': f'No product matching "{product_query}"'}), 404

    product = products[0]
    add_subscription(
        user_id=user_id,
        product_id=product['id'],
        max_price=float(max_price) if max_price else None,
        notify_email=email or None,
        user_name=user_id,
    )

    name = product['canonical_name']
    if product['variant']:
        name += f" ({product['variant']})"
    return jsonify({'success': True, 'product': name, 'max_price': max_price})


@app.route('/api/untrack', methods=['POST'])
def api_untrack():
    data = request.json or {}
    product_query = data.get('product', '')
    user_id = data.get('user_id', 'web_user')

    products = find_product(product_query)
    if not products:
        return jsonify({'error': 'Product not found'}), 404

    remove_subscription(user_id, products[0]['id'])
    return jsonify({'success': True})


@app.route('/api/wishlist')
def api_wishlist():
    user_id = request.args.get('user_id', 'web_user')
    subs = get_user_subscriptions(user_id)
    return jsonify([{
        'product': (s['canonical_name'] or '') + (f" ({s['variant']})" if s['variant'] else ''),
        'max_price': s['max_price'],
        'product_id': s['product_id'],
    } for s in subs])


@app.route('/api/sighting', methods=['POST'])
def api_sighting():
    data = request.json or {}
    product_query = data.get('product', '')
    store_name = data.get('store')
    mall_name = data.get('mall')
    city = data.get('city', 'Dubai')
    reporter = data.get('reporter', 'web_user')

    success, message, confidence = offline_engine.report_sighting(
        product_query=product_query,
        store_name=store_name,
        mall_name=mall_name,
        city=city,
        reporter_id=reporter,
        reporter_name=reporter,
    )
    return jsonify({'success': success, 'message': message, 'confidence': confidence})


@app.route('/api/sightings/<query>')
def api_sightings(query):
    products = find_product(query)
    if not products:
        return jsonify({'error': 'Product not found'}), 404

    sightings = get_recent_sightings(products[0]['id'], hours=48)
    return jsonify([dict(s) for s in sightings])


@app.route('/api/check', methods=['POST'])
def api_check():
    """Run an on-demand check (single product or all)."""
    data = request.json or {}
    product_query = data.get('product')

    if product_query:
        results = checker.check_single_product(product_query)
        return jsonify({'checked': len(results), 'product': product_query})
    else:
        checker.reset_stats()
        stats = checker.run_check_cycle()
        return jsonify(stats)


@app.route('/api/check/status')
def api_check_status():
    """Get last check stats and background thread status."""
    return jsonify({
        'stats': checker.get_stats(),
        'background_running': bg_running,
        'timestamp': datetime.utcnow().isoformat(),
    })


@app.route('/api/alerts')
def api_alerts():
    """Get recent alerts."""
    hours = int(request.args.get('hours', 24))
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    with get_db() as conn:
        alerts = conn.execute("""
            SELECT * FROM alerts WHERE sent_at >= ? ORDER BY sent_at DESC LIMIT 50
        """, (cutoff,)).fetchall()
    return jsonify([dict(a) for a in alerts])


@app.route('/api/diagnostics')
def api_diagnostics():
    """Show system diagnostics — useful for debugging."""
    import shutil

    diag = {
        'python_version': __import__('sys').version,
        'background_running': bg_running,
        'check_interval': 900,
        'timestamp': datetime.utcnow().isoformat(),
    }

    # Memory info
    try:
        import resource
        usage = resource.getrusage(resource.RUSAGE_SELF)
        diag['memory_mb'] = round(usage.ru_maxrss / 1024, 1)  # Linux: KB -> MB
    except Exception:
        pass

    # Disk info
    try:
        disk = shutil.disk_usage('/')
        diag['disk_free_mb'] = round(disk.free / 1024 / 1024, 1)
    except Exception:
        pass

    return jsonify(diag)


@app.route('/api/email-subscribe', methods=['POST'])
def api_email_subscribe():
    """Subscribe email to product alerts."""
    data = request.json or {}
    email = data.get('email', '').strip().lower()
    product_id = data.get('product_id')

    if not email or '@' not in email:
        return jsonify({'error': 'Valid email address is required'}), 400

    if not product_id:
        return jsonify({'error': 'Please select a specific product'}), 400

    user_id = email  # Use email directly as user_id — EmailChannel detects '@'

    # Subscribe to specific product
    add_subscription(
        user_id=user_id,
        product_id=int(product_id),
        max_price=None,
        notify_email=email,
        notify_whatsapp=None,
        user_name=email,
    )

    return jsonify({
        'success': True,
        'email': email,
        'message': f'Subscribed {email} to email alerts!'
    })


@app.route('/api/test-email', methods=['POST'])
def api_test_email():
    """Send a test email to verify email notifications work."""
    data = request.json or {}
    email = data.get('email', '').strip().lower()

    if not email or '@' not in email:
        return jsonify({'error': 'Valid email address is required'}), 400

    from notifications.notifier import EmailChannel
    channel = EmailChannel()

    if not channel.sender or not channel.password:
        return jsonify({
            'error': 'Email not configured on server. Set EMAIL_ENABLED, EMAIL_SENDER, EMAIL_PASSWORD env vars.'
        }), 500

    success = channel.send(
        email,
        "This is a test notification from NeeDoh Watch UAE!\n\n"
        "If you received this email, notifications are working correctly.\n\n"
        "You will receive alerts when:\n"
        "• A product you're tracking comes back in stock\n"
        "• A price drops significantly\n"
        "• Someone spots a product at a store near you",
        subject="✅ NeeDoh Watch — Test Notification"
    )

    if success:
        return jsonify({'success': True, 'message': f'Test email sent to {email}!'})
    else:
        return jsonify({'error': 'Failed to send email. Check server logs.'}), 500


# ─── Background checker ───

def self_ping():
    """Ping our own health endpoint to prevent Render free tier from spinning down."""
    try:
        port = int(os.environ.get('PORT', 5000))
        http_requests.get(f'http://localhost:{port}/api/health', timeout=5)
    except Exception:
        pass

def background_checker(interval=180):
    """Run stock checks in background.
    On startup: runs an aggressive initial sweep (100 listings/batch, 30s interval)
    to quickly populate all products. Then switches to normal mode (20/batch, 3 min).
    Also self-pings to prevent Render free tier from spinning down the instance.
    """
    global bg_running
    bg_running = True

    # --- Initial sweep: check all listings fast after deploy/restart ---
    print(f"🚀 Initial sweep: checking all listings quickly...", flush=True)
    sweep_done = False
    sweep_cycles = 0
    while bg_running and not sweep_done:
        try:
            checker.reset_stats()
            stats = checker.run_check_cycle(max_listings=100)  # Big batches
            sweep_cycles += 1
            checked = stats['checks']
            print(f"  ⚡ Sweep #{sweep_cycles}: {checked} checked, {stats['changes']} changes, {stats['errors']} errors", flush=True)
            if checked == 0:
                sweep_done = True  # No more listings due
        except Exception as e:
            print(f"  ✗ Sweep error: {e}", flush=True)
            sweep_done = True  # Don't loop forever on errors

        if not sweep_done:
            for _ in range(30):  # 30s between sweep batches
                if not bg_running:
                    break
                time.sleep(1)

    print(f"✅ Initial sweep complete after {sweep_cycles} cycles. Switching to normal mode.", flush=True)

    # --- Normal mode: steady checks ---
    print(f"🔄 Background checker running (interval: {interval}s)", flush=True)
    ping_counter = 0
    while bg_running:
        try:
            checker.reset_stats()
            stats = checker.run_check_cycle()
            print(f"  ✓ Background check: {stats['checks']} checked, {stats['changes']} changes, {stats['errors']} errors")
        except Exception as e:
            print(f"  ✗ Background check error: {e}")

        # Self-ping every 5 cycles (~15 min) to keep Render instance alive
        ping_counter += 1
        if ping_counter % 5 == 0:
            self_ping()

        for _ in range(interval):
            if not bg_running:
                break
            time.sleep(1)
    print("⏹ Background checker stopped")


@app.route('/api/background/start', methods=['POST'])
def start_background():
    global bg_thread, bg_running
    if bg_running:
        return jsonify({'status': 'already_running'})
    interval = request.json.get('interval', 180) if request.json else 180
    bg_thread = threading.Thread(target=background_checker, args=(interval,), daemon=True)
    bg_thread.start()
    return jsonify({'status': 'started', 'interval': interval})


@app.route('/api/background/stop', methods=['POST'])
def stop_background():
    global bg_running
    bg_running = False
    return jsonify({'status': 'stopped'})


# ─── Dashboard HTML ───

DASHBOARD_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NeeDoh Watch UAE 🎯</title>
    <link href="https://fonts.googleapis.com/css2?family=Nunito:wght@600;700;800&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }

        :root {
            --pink: #FF6B9D;
            --purple: #C084FC;
            --turquoise: #22D3EE;
            --coral: #FF8A65;
            --lime: #84CC16;
            --white: #FFFFFF;
            --light-bg: #F8F9FF;
            --light-gray: #E8EAEF;
            --dark-text: #2D3748;
            --light-text: #718096;
        }

        body {
            font-family: 'Nunito', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: linear-gradient(135deg, #FFF5F7 0%, #F3F0FF 50%, #ECFDF5 100%);
            color: var(--dark-text);
            line-height: 1.6;
            min-height: 100vh;
        }

        /* Header */
        .header {
            background: linear-gradient(135deg, #FF6B9D 0%, #C084FC 50%, #22D3EE 100%);
            padding: 24px;
            text-align: center;
            box-shadow: 0 4px 15px rgba(255, 107, 157, 0.2);
        }

        .header h1 {
            font-size: 32px;
            font-weight: 800;
            color: var(--white);
            margin: 0;
            text-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }

        .header p {
            color: rgba(255, 255, 255, 0.9);
            font-size: 14px;
            margin-top: 6px;
            font-weight: 500;
        }

        /* Container */
        .container {
            max-width: 1000px;
            margin: 0 auto;
            padding: 24px;
        }

        /* Email Alert Section */
        .email-alert-section {
            background: var(--white);
            border-radius: 16px;
            padding: 24px;
            margin-bottom: 32px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
            border: 2px solid transparent;
            background: linear-gradient(135deg, rgba(255, 107, 157, 0.05) 0%, rgba(192, 132, 252, 0.05) 100%);
        }

        .email-alert-section h2 {
            font-size: 20px;
            font-weight: 700;
            margin-bottom: 16px;
            color: var(--dark-text);
        }

        .email-input-group {
            display: flex;
            gap: 12px;
            flex-wrap: wrap;
        }

        .email-input-group input {
            flex: 1;
            min-width: 200px;
            padding: 12px 16px;
            border: 2px solid var(--light-gray);
            border-radius: 12px;
            font-size: 14px;
            font-family: inherit;
            transition: all 0.2s;
        }

        .email-input-group input:focus {
            outline: none;
            border-color: var(--pink);
            box-shadow: 0 0 0 3px rgba(255, 107, 157, 0.1);
        }

        .email-input-group button {
            padding: 12px 28px;
            background: linear-gradient(135deg, var(--pink) 0%, var(--coral) 100%);
            color: var(--white);
            border: none;
            border-radius: 12px;
            font-size: 14px;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.2s;
            box-shadow: 0 4px 12px rgba(255, 107, 157, 0.3);
        }

        .email-input-group button:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 16px rgba(255, 107, 157, 0.4);
        }

        .email-input-group button:active {
            transform: translateY(0);
        }

        .email-confirmation {
            margin-top: 12px;
            padding: 12px;
            border-radius: 8px;
            background: linear-gradient(135deg, rgba(132, 204, 22, 0.1) 0%, rgba(34, 211, 238, 0.1) 100%);
            color: var(--dark-text);
            font-size: 13px;
            font-weight: 600;
            display: none;
        }

        .email-confirmation.show {
            display: block;
        }

        /* Product Grid */
        .product-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 20px;
            margin-bottom: 32px;
        }

        .product-card {
            background: var(--white);
            border-radius: 16px;
            padding: 20px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
            transition: all 0.3s;
            border: 2px solid transparent;
            text-align: center;
            display: flex;
            flex-direction: column;
        }

        .product-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 20px rgba(0, 0, 0, 0.12);
        }

        .product-card.pink {
            border-color: rgba(255, 107, 157, 0.2);
        }

        .product-card.purple {
            border-color: rgba(192, 132, 252, 0.2);
        }

        .product-card.turquoise {
            border-color: rgba(34, 211, 238, 0.2);
        }

        .product-card.coral {
            border-color: rgba(255, 138, 101, 0.2);
        }

        .product-card.lime {
            border-color: rgba(132, 204, 22, 0.2);
        }

        .product-emoji {
            font-size: 48px;
            margin-bottom: 12px;
            text-align: center;
        }

        .product-img {
            width: 100px;
            height: 100px;
            object-fit: contain;
            border-radius: 12px;
            margin-bottom: 12px;
            background: #f8f4ff;
            padding: 4px;
            display: block;
            margin-left: auto;
            margin-right: auto;
        }

        .delivery-info {
            font-size: 11px;
            color: var(--light-text);
            margin-top: 4px;
            font-weight: 600;
        }

        .store-prices {
            display: flex;
            flex-direction: column;
            gap: 4px;
            margin-top: 8px;
            flex: 1;
            font-size: 12px;
        }

        .store-price-row {
            display: flex;
            align-items: center;
            padding: 4px 8px;
            border-radius: 6px;
            background: rgba(248, 244, 255, 0.5);
            text-align: left;
            gap: 4px;
            flex-wrap: nowrap;
        }

        .store-price-row .store-label {
            font-weight: 600;
            color: var(--light-text);
            white-space: nowrap;
            font-size: 12px;
            min-width: 0;
            flex-shrink: 0;
        }

        .store-price-row .delivery-info {
            font-size: 9px;
            color: var(--light-text);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            flex: 1;
            min-width: 0;
        }

        .store-price-row .store-price-val {
            font-weight: 800;
            color: var(--pink);
            white-space: nowrap;
            flex-shrink: 0;
            font-size: 12px;
        }

        .store-price-row .store-icon {
            width: 16px;
            height: 16px;
            margin-right: 5px;
            vertical-align: middle;
            border-radius: 3px;
            object-fit: contain;
        }

        .notify-inline {
            margin-top: auto;
            padding: 8px;
            background: rgba(102, 126, 234, 0.06);
            border-radius: 8px;
            text-align: center;
        }
        .notify-inline p {
            font-size: 11px;
            color: var(--light-text);
            margin: 0 0 6px 0;
        }
        .notify-inline-row {
            display: flex;
            gap: 4px;
        }
        .notify-inline-row input {
            flex: 1;
            padding: 6px 8px;
            border: 1.5px solid #667eea;
            border-radius: 6px;
            font-size: 12px;
            min-width: 0;
        }
        .notify-inline-row button {
            padding: 6px 10px;
            background: linear-gradient(135deg,#667eea,#764ba2);
            color: white;
            border: none;
            border-radius: 6px;
            font-weight: 700;
            cursor: pointer;
            font-size: 11px;
            white-space: nowrap;
        }

        .product-name {
            font-size: 16px;
            font-weight: 700;
            color: var(--dark-text);
            margin-bottom: 12px;
            text-align: center;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .product-status {
            display: inline-block;
            padding: 8px 14px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 700;
            margin-bottom: 12px;
            text-align: center;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .status-available {
            background: linear-gradient(135deg, rgba(132, 204, 22, 0.2) 0%, rgba(34, 211, 238, 0.1) 100%);
            color: #2D5016;
        }

        .status-out-of-stock {
            background: linear-gradient(135deg, rgba(255, 107, 157, 0.2) 0%, rgba(255, 138, 101, 0.1) 100%);
            color: #7F1D1D;
        }

        .status-checking {
            background: linear-gradient(135deg, rgba(192, 132, 252, 0.2) 0%, rgba(34, 211, 238, 0.1) 100%);
            color: #4C1D95;
        }

        .product-price {
            font-size: 24px;
            font-weight: 800;
            color: var(--pink);
            margin-bottom: 12px;
        }

        .product-stores {
            display: flex;
            flex-direction: column;
            gap: 8px;
            margin-top: 12px;
        }

        .store-link {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 8px 12px;
            background: linear-gradient(135deg, rgba(192, 132, 252, 0.1) 0%, rgba(34, 211, 238, 0.1) 100%);
            color: var(--dark-text);
            text-decoration: none;
            border-radius: 8px;
            font-size: 12px;
            font-weight: 600;
            transition: all 0.2s;
            border: 1px solid rgba(192, 132, 252, 0.2);
        }

        .store-link:hover {
            background: linear-gradient(135deg, rgba(192, 132, 252, 0.2) 0%, rgba(34, 211, 238, 0.15) 100%);
            transform: translateX(2px);
        }

        .store-link.amazon {
            background: linear-gradient(135deg, rgba(255, 159, 0, 0.1) 0%, rgba(255, 193, 7, 0.05) 100%);
            border-color: rgba(255, 159, 0, 0.2);
            color: #E65100;
        }

        .store-link.amazon:hover {
            background: linear-gradient(135deg, rgba(255, 159, 0, 0.15) 0%, rgba(255, 193, 7, 0.1) 100%);
        }

        .store-link.noon {
            background: linear-gradient(135deg, rgba(255, 80, 80, 0.1) 0%, rgba(255, 152, 0, 0.05) 100%);
            border-color: rgba(255, 80, 80, 0.2);
            color: #C62828;
        }

        .store-link.noon:hover {
            background: linear-gradient(135deg, rgba(255, 80, 80, 0.15) 0%, rgba(255, 152, 0, 0.1) 100%);
        }

        .store-link.virgin {
            background: linear-gradient(135deg, rgba(220, 20, 60, 0.1) 0%, rgba(255, 105, 180, 0.05) 100%);
            border-color: rgba(220, 20, 60, 0.2);
            color: #B71C1C;
        }

        .store-link.virgin:hover {
            background: linear-gradient(135deg, rgba(220, 20, 60, 0.15) 0%, rgba(255, 105, 180, 0.1) 100%);
        }

        .store-link.ubuy {
            background: linear-gradient(135deg, rgba(233, 30, 99, 0.1) 0%, rgba(244, 143, 177, 0.05) 100%);
            border-color: rgba(233, 30, 99, 0.2);
            color: #880E4F;
        }

        .store-link.ubuy:hover {
            background: linear-gradient(135deg, rgba(233, 30, 99, 0.15) 0%, rgba(244, 143, 177, 0.1) 100%);
        }

        .store-link.desertcart {
            background: linear-gradient(135deg, rgba(0, 150, 136, 0.1) 0%, rgba(76, 175, 80, 0.05) 100%);
            border-color: rgba(0, 150, 136, 0.2);
            color: #00695C;
        }

        .store-link.desertcart:hover {
            background: linear-gradient(135deg, rgba(0, 150, 136, 0.15) 0%, rgba(76, 175, 80, 0.1) 100%);
        }

        .store-link.disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        .store-link.disabled:hover {
            transform: none;
        }

        .buy-icon-link {
            text-decoration: none;
            font-size: 14px;
            cursor: pointer;
            transition: transform 0.2s;
        }
        .buy-icon-link:hover {
            transform: scale(1.3);
        }

        /* Action Buttons */
        .product-actions {
            display: flex;
            gap: 8px;
            margin-top: 12px;
        }

        .btn-small {
            flex: 1;
            padding: 8px 12px;
            background: var(--light-gray);
            color: var(--dark-text);
            border: none;
            border-radius: 8px;
            font-size: 12px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }

        .btn-small:hover {
            background: #D2D6DC;
            transform: translateY(-1px);
        }

        .btn-small.report {
            background: linear-gradient(135deg, rgba(255, 107, 157, 0.15) 0%, rgba(192, 132, 252, 0.1) 100%);
            color: var(--pink);
        }

        .btn-small.report:hover {
            background: linear-gradient(135deg, rgba(255, 107, 157, 0.25) 0%, rgba(192, 132, 252, 0.15) 100%);
        }

        /* Modal */
        .modal-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.4);
            z-index: 100;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.3s;
        }

        .modal-overlay.show {
            opacity: 1;
            pointer-events: all;
        }

        .modal {
            background: var(--white);
            border-radius: 20px;
            width: 100%;
            max-width: 600px;
            max-height: 90vh;
            overflow-y: auto;
            padding: 28px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.15);
            position: relative;
        }

        .modal-close {
            position: absolute;
            top: 16px;
            right: 16px;
            width: 32px;
            height: 32px;
            background: var(--light-gray);
            border: none;
            border-radius: 8px;
            font-size: 24px;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .modal-close:hover {
            background: #D2D6DC;
            transform: rotate(90deg);
        }

        .modal h2 {
            font-size: 24px;
            font-weight: 700;
            margin-bottom: 20px;
            color: var(--dark-text);
        }

        .modal h3 {
            font-size: 16px;
            font-weight: 700;
            margin: 20px 0 12px 0;
            color: var(--dark-text);
        }

        /* Forms */
        .form-group {
            margin-bottom: 18px;
        }

        .form-group label {
            display: block;
            font-size: 14px;
            font-weight: 600;
            margin-bottom: 6px;
            color: var(--dark-text);
        }

        .form-input {
            width: 100%;
            padding: 12px 14px;
            border: 2px solid var(--light-gray);
            border-radius: 10px;
            font-size: 14px;
            font-family: inherit;
            transition: all 0.2s;
        }

        .form-input:focus {
            outline: none;
            border-color: var(--purple);
            box-shadow: 0 0 0 3px rgba(192, 132, 252, 0.1);
        }

        .btn-primary {
            width: 100%;
            padding: 12px;
            background: linear-gradient(135deg, var(--pink) 0%, var(--coral) 100%);
            color: var(--white);
            border: none;
            border-radius: 10px;
            font-size: 14px;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.2s;
            margin-top: 12px;
        }

        .btn-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 16px rgba(255, 107, 157, 0.4);
        }

        .btn-primary:active {
            transform: translateY(0);
        }

        /* Store Details */
        .store-detail-row {
            background: var(--light-bg);
            padding: 14px;
            border-radius: 10px;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .store-detail-info {
            flex: 1;
        }

        .store-detail-name {
            font-weight: 700;
            color: var(--dark-text);
            margin-bottom: 4px;
        }

        .store-detail-meta {
            font-size: 12px;
            color: var(--light-text);
        }

        .store-detail-price {
            font-size: 18px;
            font-weight: 800;
            color: var(--pink);
            margin: 0 12px;
        }

        .store-detail-button {
            padding: 8px 16px;
            background: linear-gradient(135deg, var(--purple) 0%, var(--turquoise) 100%);
            color: var(--white);
            border: none;
            border-radius: 8px;
            font-size: 12px;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.2s;
            white-space: nowrap;
        }

        .store-detail-button:hover {
            transform: translateY(-1px);
            box-shadow: 0 4px 12px rgba(192, 132, 252, 0.3);
        }

        .store-detail-button.disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        /* Toast */
        .toast {
            position: fixed;
            bottom: 24px;
            right: 24px;
            z-index: 200;
            padding: 14px 20px;
            border-radius: 10px;
            background: linear-gradient(135deg, var(--pink) 0%, var(--coral) 100%);
            color: var(--white);
            font-weight: 600;
            font-size: 14px;
            box-shadow: 0 6px 16px rgba(255, 107, 157, 0.4);
            transform: translateY(120px);
            opacity: 0;
            transition: all 0.3s;
        }

        .toast.show {
            transform: translateY(0);
            opacity: 1;
        }

        /* Loading */
        .spinner {
            display: inline-block;
            width: 16px;
            height: 16px;
            border: 2px solid rgba(192, 132, 252, 0.3);
            border-top-color: var(--purple);
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        /* Responsive */
        @media (max-width: 768px) {
            .product-grid {
                grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
                gap: 16px;
            }

            .header h1 {
                font-size: 24px;
            }

            .header {
                padding: 18px;
            }

            .container {
                padding: 16px;
            }

            .email-input-group {
                flex-direction: column;
            }

            .email-input-group input,
            .email-input-group button {
                width: 100%;
            }

            .modal {
                padding: 20px;
            }

            .store-detail-row {
                flex-direction: column;
                text-align: center;
            }

            .store-detail-price {
                margin: 8px 0;
            }

            .store-detail-button {
                width: 100%;
            }
        }

        .hidden {
            display: none !important;
        }

        /* Lightbox for product images */
        .product-img {
            cursor: pointer;
            transition: transform 0.2s;
        }
        .product-img:hover {
            transform: scale(1.05);
        }
        .lightbox-overlay {
            display: none;
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0,0,0,0.85);
            z-index: 10000;
            justify-content: center;
            align-items: center;
            cursor: pointer;
        }
        .lightbox-overlay.show {
            display: flex;
        }
        .lightbox-overlay img {
            max-width: 90vw;
            max-height: 90vh;
            border-radius: 16px;
            box-shadow: 0 0 40px rgba(0,0,0,0.5);
            object-fit: contain;
        }
        .lightbox-close {
            position: fixed;
            top: 20px; right: 20px;
            color: white;
            font-size: 36px;
            cursor: pointer;
            z-index: 10001;
            background: rgba(0,0,0,0.5);
            border: none;
            border-radius: 50%;
            width: 48px;
            height: 48px;
            display: flex;
            align-items: center;
            justify-content: center;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>🎯 NeeDoh Watch UAE</h1>
        <p>Find your favorite fidget toys across all stores!</p>
    </div>

    <div class="container">
        <!-- Product Grid -->
        <div class="product-grid" id="productGrid">
            <div style="text-align: center; padding: 40px; grid-column: 1/-1;">
                <div class="spinner"></div>
                <p style="margin-top: 16px; color: var(--light-text);">Loading amazing toys...</p>
            </div>
        </div>
    </div>

    <!-- Sighting Modal -->
    <div class="modal-overlay" id="sightingModal" onclick="if(event.target.id === 'sightingModal') closeSightingModal()">
        <div class="modal">
            <button class="modal-close" onclick="closeSightingModal()">&times;</button>
            <h2>👀 I Spotted One!</h2>
            <div class="form-group">
                <label>Which toy?</label>
                <select class="form-input" id="sightProduct"></select>
            </div>
            <div class="form-group">
                <label>Store</label>
                <select class="form-input" id="sightStore">
                    <option value="Amazon.ae">Amazon.ae</option>
                    <option value="Noon">Noon</option>
                    <option value="Ubuy">Ubuy UAE</option>
                    <option value="Other">Other Store</option>
                </select>
            </div>
            <div class="form-group">
                <label>Where exactly? (Mall or store)</label>
                <input class="form-input" id="sightMall" placeholder="e.g., Dubai Mall, Mall of the Emirates">
            </div>
            <div class="form-group">
                <label>City</label>
                <select class="form-input" id="sightCity">
                    <option value="Dubai">Dubai</option>
                    <option value="Abu Dhabi">Abu Dhabi</option>
                    <option value="Sharjah">Sharjah</option>
                    <option value="Other">Other</option>
                </select>
            </div>
            <button class="btn-primary" onclick="submitSighting()">Share the News! 📢</button>
        </div>
    </div>

    <!-- Toast -->
    <div class="toast" id="toast"></div>

    <!-- Lightbox for enlarged images -->
    <div class="lightbox-overlay" id="lightbox" onclick="closeLightbox()">
        <button class="lightbox-close" onclick="closeLightbox()">&times;</button>
        <img id="lightboxImg" src="" alt="Product image">
    </div>

<script>
// Product image mapping — boxed/packaged images preferred
// Source: birdinhand.com (official Schylling distributor), with fallbacks to retailer CDNs
const PRODUCT_IMAGES = {
    // === Packaging/box images — needoh.org, birdinhand, myneedoh.com ===
    // IMPORTANT: More specific names MUST come before shorter ones
    // (e.g. "Nice Cube Swirl" before "Nice Cube") because matching uses .includes()

    // Nice Cube variants — specific names first to avoid false matches
    'Nice Cube Swirl':'https://needoh.org/images/needoh-nice-cube-swirl1.jpg',
    'Nice Cube Glow': 'https://cdn.shopify.com/s/files/1/0069/4009/8629/files/GNCBND-_NeeDoh-Nice-Cube-Glow-Package-Front-Pink.jpg',
    'Nice Cube':      'https://cdn.shopify.com/s/files/1/0069/4009/8629/files/NCBND-NeeDoh-Nice-Cube-Pkg-3QR-Blue-web.jpg',

    // Super variants — specific names first
    'Super NeeDoh Cool':'https://needoh.org/images/needoh-giant-coolcats1.jpg',
    'Super NeeDoh':   'https://needoh.org/images/needoh-giant-classic1.jpg',
    'Super Marble':   'https://cdn.shopify.com/s/files/1/0069/4009/8629/products/ScreenShot2022-08-15at1.29.56PM.png',

    // Nice Berg variants — specific first
    'Nice Berg Swirl':'https://cdn.shopify.com/s/files/1/0069/4009/8629/files/SWSNCBND-NeeDoh-Swirl-Nice-Berg-Pkg-3Q-Right_1.jpg',
    'Nice Berg':      'https://needoh.org/images/needoh-giant-niceberg1.jpg',

    // Fuzz Ball variants — most specific first
    'Fuzz Ball Wonder Waves':'https://www.curiousmindsbusybags.com/cdn/shop/files/needoh_fuzz_wonder_wave_12.jpg?v=1742476008',
    'Fuzz Ball Flower Power':'https://www.curiousmindsbusybags.com/cdn/shop/files/Needoh_flower_power_11.jpg?v=1743025259',
    'Fuzz Ball Wild Cats':'https://www.rocketcitytoys.com/cdn/shop/files/20260109100747-da2122a8-la.jpg?v=1771962470&width=800',
    'Fuzz Ball Teenie':'https://www.curiousmindsbusybags.com/cdn/shop/files/teeniefuzzball1.jpg?v=1758478762',
    'Fuzz Ball':      'https://www.curiousmindsbusybags.com/cdn/shop/files/needohfuzzball3copy.jpg?v=1742476010',

    // Glow in the Dark before other "Glow" matches
    'Glow in the Dark':'https://cdn.shopify.com/s/files/1/0069/4009/8629/products/GND-Nee-Doh-Glow-in-the-Dark-PKG-3Q-Right-web.jpg',

    // Dohnut variants — specific first
    'Dohnut Jelly':   'https://needoh.org/images/needoh-dohnuts1.jpg',
    'Dohnuts':        'https://needoh.org/images/needoh-dohnuts1.jpg',

    // Groovy variants — specific first
    'Groovy Shroom':  'https://sterlingtoystore.com/cdn/shop/files/Groovy_Shroom_Nee_Doh.png?v=1722627251&width=800',
    'Groovy Fruit':   'https://www.curiousmindsbusybags.com/cdn/shop/products/needohfruit8.jpg?v=1598371015',
    'Groovy Jewel':   'https://www.curiousmindsbusybags.com/cdn/shop/files/needohjewel2.jpg?v=1761055735',

    // Snow variants — specific first
    'Snowball':       'https://needoh.org/images/needoh-snowball-crunch1.jpg',
    'Snow Globe':     'https://littleshop.toys/cdn/shop/files/needoh-snow-globe-sqmsg24-791759.jpg?v=1730760880&width=800',

    // Color Change before other "Color" matches
    'Color Change':   'https://needoh.org/images/needoh-color-changing1.jpg',

    // All other products (alphabetical)
    'Classic':        'https://needoh.org/images/needoh-classic-groovy-glob1.jpg',
    'Gummy Bear':     'https://cdn.shopify.com/s/files/1/0069/4009/8629/files/GBND-NeeDoh-Gummy-Bear-Pkg-3Q-Right-Pink-web.jpg',
    'Cool Cats':      'https://needoh.org/images/needoh-coolcats1.jpg',
    'Gumdrop':        'https://needoh.org/images/needoh-gumdrop1.jpg',
    'Dream Drop':     'https://cdn.shopify.com/s/files/1/0069/4009/8629/files/DRDND_Image1.jpg',
    'Mac N Squeeze':  'https://myneedoh.com/wp-content/uploads/2024/10/nd10.jpg',
    'Ramen':          'https://www.curiousmindsbusybags.com/cdn/shop/products/ramennoodles7.jpg?v=1687729189',
    'Dig It Pig':     'https://needoh.org/images/needoh-digitpig1.jpg',
    'Shaggy':         'https://myneedoh.com/wp-content/uploads/2024/10/nd11.jpg',
    'Stardust':       'https://myneedoh.com/wp-content/uploads/2024/10/nd7.jpg',
    'Crystal':        'https://myneedoh.com/wp-content/uploads/2024/10/nd8.jpg',
    'Marbleez':       'https://www.curiousmindsbusybags.com/cdn/shop/files/needohmarbleez1copy.jpg?v=1775867879',
    'Nice-Sicle':     'https://www.curiousmindsbusybags.com/cdn/shop/files/needohpopsicle1copy.jpg?v=1771377353',
    'Dohjees':        'https://myneedoh.com/wp-content/uploads/2025/12/81.jpg',
    'Panic Pete':     'https://cdn.shopify.com/s/files/1/0069/4009/8629/files/NDPPST-NeeDoh-Panic-Pete-Squeeze-Green2-web.jpg',
    'Chickadeedoos':  'https://cdn11.bigcommerce.com/s-65gzldhg/images/stencil/1280x1280/products/8565/11515/chickadeedoos_blue_CDDND24__99485.1705010497.jpg?c=2',
    'Jelly Squish':   'https://needoh.org/images/needoh-jellyfish1.jpg',
    'Teenie':         'https://cdn.shopify.com/s/files/1/0069/4009/8629/files/TSNDA_Image1.jpg',
    'Peace O Cake':   'https://cdn.shopify.com/s/files/1/0069/4009/8629/files/POCND_Image2.jpg',
    'Dippin Dazzler': 'https://target.scene7.com/is/image/Target/GUEST_893acc13-f899-4ca8-bc3b-2befce010ce1?wid=800&hei=800&fmt=pjpeg',
    'Jelly Hops':     'https://www.curiousmindsbusybags.com/cdn/shop/files/needohjellyhop_36568f89-6a58-43ad-8d11-a7e91caa2f89.jpg?v=1771378337',
    'Nice Ice Baby':  'https://needoh.org/images/needoh-nice-ice-baby1.jpg',
    'Nice Cream Cone':'https://cdn.shopify.com/s/files/1/0069/4009/8629/files/NCCND_Image2.jpg',
    'Mello Mallo':    'https://needoh.org/images/needoh-mello-mallo1.jpg',
    'Booper':         'https://www.curiousmindsbusybags.com/cdn/shop/products/needohbooper1.jpg?v=1668101186',
    'Funky Pups':     'https://needoh.org/images/needoh-funkypup1.jpg',
    'Hot Shot':       'https://cdn.shopify.com/s/files/1/0069/4009/8629/files/HSTND-NeeDoh-Hot-Shots-Product-Football-Hand.jpg',
    'Squeezza Pizza': 'https://www.curiousmindsbusybags.com/cdn/shop/files/needohpizza1copy.jpg?v=1771376155',
    'Atomic':         'https://cdn.shopify.com/s/files/1/0069/4009/8629/products/AtomicNeeDoh02.jpg',
    'Sploot Splat':   'https://cdn.shopify.com/s/files/1/0069/4009/8629/files/thesplootsplat.jpg',
    'Lava Squish':    'https://www.junioredition.com/cdn/shop/files/Needoh-AW24-Lava-Squish-And-Flow-Squishy-Toy-4.jpg?v=1728899247&width=800',
    'Advent Calendar':'https://needoh.org/images/needoh-advent-calendar1.jpg',
    'Marble Egg':     'https://needoh.org/images/needoh-egg1.jpg',
    'Wonder Waves':   'https://www.curiousmindsbusybags.com/cdn/shop/files/needoh_fuzz_wonder_wave_12.jpg?v=1742476008',
    'Flower Power':   'https://www.curiousmindsbusybags.com/cdn/shop/files/Needoh_flower_power_11.jpg?v=1743025259',
    'Squeezy Peezy':  'https://www.thestorebeforetime.com/cdn/shop/files/8D5C32F6-FB36-4301-A84B-F5C488956414.png?v=1719098098&width=800',
    'Happy Snappy':   'https://cdn.shopify.com/s/files/1/0069/4009/8629/products/IMG_6400_49fe78f7-3461-4f67-bba4-f12e0cc38be1.jpg',
    'Squeeze Hearts': 'https://aneoliving.com/cdn/shop/files/Schylling-NeeDoh-Teenie-Squeeze-Hearts-Pack-of-3-Fidget-Toys.webp?v=1743012828',
    'Ripples':        'https://www.curiousmindsbusybags.com/cdn/shop/files/needohsuperripples1.jpg?v=1737322260',
    'Good Vibes':     'https://cdn.shopify.com/s/files/1/0069/4009/8629/files/GVND-Nee-Doh-Good-Vibes-Only-Package-StayGroovy-3Q-Right.jpg',
    'Wild Cats':      'https://www.rocketcitytoys.com/cdn/shop/files/20260109100747-da2122a8-la.jpg?v=1771962470&width=800',
    'Cloud Pleaser':  'https://cdn.shopify.com/s/files/1/0069/4009/8629/files/SFZBND-NeeDoh-Super-FuzzBall-Product-Group.jpg',
    'Bubble Glob':    'https://cdn.shopify.com/s/files/1/0069/4009/8629/products/BTSQ-Bubble-Glob-Nee-Doh-Lifestyle-web.jpg',
    'Baby Boos':      'https://www.rocketcitytoys.com/cdn/shop/files/NDWBB26.jpg?v=1766956087&width=800',
    'Dohzee':         'https://www.curiousmindsbusybags.com/cdn/shop/products/dohzeeneedoh2.jpg?v=1611789106',
    'Glowy Ghost':    'https://www.isaacstreasures.com/wp-content/uploads/2025/10/wp-image-77402901807484.webp',
    'Sugar Skull':    'https://cdn.shopify.com/s/files/1/0069/4009/8629/files/SSCCND-NeeDoh-SugarSkull-CoolCats-PKG-3Q-Right-White2.jpg',
    'Cool Cane':      'https://www.junioredition.com/cdn/shop/files/Schylling-AW25-Needoh-Squishmas-Cool-Cane-Squishy.jpg?v=1762518843&width=800',
    'Golden Egg':     'https://www.curiousmindsbusybags.com/cdn/shop/files/NEEDOHEGGHUNT1.jpg?v=1771378256',
    'Stickums':       'https://www.curiousmindsbusybags.com/cdn/shop/products/needohstickums1.jpg?v=1654039604',
    'Swirl':          'https://cdn.shopify.com/s/files/1/0069/4009/8629/products/SWND-Swirl-Nee-Doh-Item-GreenLime-web.jpg',
    'Gobs of Globs':  'https://cdn.shopify.com/s/files/1/0069/4009/8629/products/GGTND-Gobs-of-Globs-Pkg-3Q-Left-web.jpg',
    'Noodlies':       'https://www.curiousmindsbusybags.com/cdn/shop/products/ramennoodles7.jpg?v=1687729189',
};

// Fallback emojis if image fails to load
const PRODUCT_EMOJIS = {
    'Nice Cube Swirl': '🌀', 'Nice Cube Glow': '✨', 'Nice Cube': '🧊',
    'Super NeeDoh Cool': '🐱', 'Super NeeDoh': '💪', 'Super Marble': '🔮',
    'Nice Berg Swirl': '🌀', 'Nice Berg': '🏔️',
    'Fuzz Ball Teenie': '🧸', 'Fuzz Ball': '🧸',
    'Dohnut Jelly': '🍩', 'Dohnuts': '🍩',
    'Glow in the Dark': '🌙', 'Groovy Shroom': '🍄',
    'Groovy Fruit': '🍇', 'Groovy Jewel': '💎',
    'Snow Globe': '🎄', 'Snowball': '❄️',
    'Color Change': '🎨',
    'Classic': '🫠', 'Gummy Bear': '🐻', 'Cool Cats': '🐱',
    'Gumdrop': '🍬', 'Dream Drop': '💧', 'Mac N Squeeze': '🧀', 'Ramen': '🍜',
    'Dig It Pig': '🐷', 'Shaggy': '🦁', 'Stardust': '⭐',
    'Crystal': '💎', 'Marbleez': '🔮',
    'Nice-Sicle': '🍦',
    'Dohjees': '🎲', 'Panic Pete': '😱', 'Chickadeedoos': '🐣', 'Jelly Squish': '🍮',
    'Teenie': '🎯',
    'Peace O Cake': '🎂', 'Dippin Dazzler': '🥚', 'Jelly Hops': '🐰',
    'Nice Ice Baby': '🧊', 'Nice Cream Cone': '🍦', 'Mello Mallo': '🍡',
    'Booper': '👃', 'Funky Pups': '🐶', 'Hot Shot': '🏀',
    'Squeezza Pizza': '🍕', 'Atomic': '⚛️', 'Sploot Splat': '💥',
    'Lava Squish': '🌋', 'Advent Calendar': '🎄',
    'Marble Egg': '🥚', 'Wonder Waves': '🌊',
    'Squeezy Peezy': '😊', 'Happy Snappy': '🐊',
    'Squeeze Hearts': '💖', 'Ripples': '🌊',
    'Flower Power': '🌸', 'Good Vibes': '💝',
    'Wild Cats': '🐾', 'Cloud Pleaser': '☁️',
    'Bubble Glob': '🫧', 'Baby Boos': '👶', 'Dohzee': '😴',
    'Glowy Ghost': '👻', 'Sugar Skull': '💀', 'Cool Cane': '🍬',
    'Golden Egg': '🥇', 'Stickums': '🪄', 'Swirl': '🌀',
    'Gobs of Globs': '🫠', 'Noodlies': '🍜',
};

// Color rotation for product cards
const CARD_COLORS = ['pink', 'purple', 'turquoise', 'coral', 'lime'];
let colorIndex = 0;

let allProducts = [];

// Init on page load
document.addEventListener('DOMContentLoaded', () => {
    refreshDashboard();
    setInterval(refreshDashboard, 60000); // Auto-refresh every 60 seconds
});

// API helper
async function api(url, opts = {}) {
    const resp = await fetch(url, {
        headers: { 'Content-Type': 'application/json' },
        ...opts
    });
    return resp.json();
}

// Lightbox functions
function openLightbox(imgUrl) {
    const overlay = document.getElementById('lightbox');
    const img = document.getElementById('lightboxImg');
    img.src = imgUrl;
    overlay.classList.add('show');
    document.body.style.overflow = 'hidden';
}
function closeLightbox() {
    document.getElementById('lightbox').classList.remove('show');
    document.body.style.overflow = '';
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeLightbox(); });

// Toast notification
function toast(msg) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 3000);
}

// Refresh dashboard
async function refreshDashboard() {
    const data = await api('/api/dashboard');
    allProducts = data.products;
    renderProducts(data.products);
    populateSelects(data.products);
}

// Get image URL for product — prefers longest matching key
function getImageUrl(productName) {
    let bestMatch = null;
    let bestLen = 0;
    for (const [name, url] of Object.entries(PRODUCT_IMAGES)) {
        if (productName.includes(name) && name.length > bestLen) {
            bestMatch = url;
            bestLen = name.length;
        }
    }
    return bestMatch;
}

// Get emoji fallback for product — prefers longest matching key
function getEmoji(productName) {
    let bestMatch = '🎯';
    let bestLen = 0;
    for (const [name, emoji] of Object.entries(PRODUCT_EMOJIS)) {
        if (productName.includes(name) && name.length > bestLen) {
            bestMatch = emoji;
            bestLen = name.length;
        }
    }
    return bestMatch;
}

// Get card color
function getCardColor() {
    const color = CARD_COLORS[colorIndex % CARD_COLORS.length];
    colorIndex++;
    return color;
}

// Render products
function renderProducts(products) {
    const grid = document.getElementById('productGrid');
    colorIndex = 0;

    if (!products.length) {
        grid.innerHTML = '<div style="grid-column:1/-1; text-align:center; padding:40px; color:var(--light-text);">No toys to track yet. Check back soon!</div>';
        return;
    }

    grid.innerHTML = products.map(p => {
        const name = p.canonical_name + (p.variant ? ` (${p.variant})` : '');
        const imgUrl = getImageUrl(p.canonical_name);
        const emoji = getEmoji(p.canonical_name);
        const color = getCardColor();

        // Build per-store price rows — only show Amazon and Noon (Desertcart/Ubuy disabled for now)
        const activeStores = ['Amazon', 'Noon'];
        const storeOrder = {'Amazon': 1, 'Amazon.ae': 1, 'Noon': 2, 'Noon UAE': 2};
        const storeListings = (p.store_listings || [])
            .filter(sl => activeStores.some(s => sl.store_name.includes(s)))
            .sort((a, b) => {
                const aKey = Object.keys(storeOrder).find(k => a.store_name.includes(k)) || a.store_name;
                const bKey = Object.keys(storeOrder).find(k => b.store_name.includes(k)) || b.store_name;
                return (storeOrder[aKey] || 99) - (storeOrder[bKey] || 99);
            });

        // Count in-stock only from visible stores (not hidden ones like Desertcart)
        const inStock = storeListings.filter(sl => sl.stock_status === 'IN_STOCK').length;

        // Determine overall status
        const outOfStock = storeListings.filter(sl => sl.stock_status === 'OUT_OF_STOCK').length;
        const allUnknown = storeListings.length > 0 && storeListings.every(sl => sl.stock_status === 'UNKNOWN');

        let statusClass, statusText;
        if (inStock > 0) {
            statusClass = 'status-available';
            statusText = '✅ AVAILABLE';
        } else if (!p.last_check) {
            statusClass = 'status-checking';
            statusText = '⏳ CHECKING...';
        } else if (allUnknown) {
            statusClass = 'status-checking';
            statusText = '🔍 NOT LISTED';
        } else {
            statusClass = 'status-out-of-stock';
            statusText = '❌ OUT OF STOCK';
        }

        // Store logo URLs
        const storeLogos = {
            'Amazon': 'https://www.google.com/s2/favicons?domain=amazon.ae&sz=32',
            'Noon': 'https://www.google.com/s2/favicons?domain=noon.com&sz=32',
        };
        function storeIcon(name) {
            const key = Object.keys(storeLogos).find(k => name.includes(k));
            if (key) return `<img src="${storeLogos[key]}" class="store-icon" alt="${key}">`;
            return '';
        }

        let storePricesHtml = '';
        if (storeListings.length > 0) {
            const rows = storeListings.map(sl => {
                const storeShort = sl.store_name.replace(' UAE', '').replace(' Megastore', '');
                const price = sl.last_price ? `AED ${sl.last_price.toFixed(0)}` : (sl.stock_status === 'IN_STOCK' ? '⏳ Getting price...' : '—');
                // Use real delivery estimate from scraper (only show when product is in stock)
                let deliveryShort = '';
                if (sl.stock_status === 'IN_STOCK' && sl.delivery_estimate) {
                    deliveryShort = '📦 ' + sl.delivery_estimate;
                }
                // Buy icon — show when in stock with any URL (search or product page)
                let buyIcon = '';
                if (sl.stock_status === 'IN_STOCK' && sl.url) {
                    buyIcon = `<a href="${sl.url}" target="_blank" rel="noopener" class="buy-icon-link" title="Buy from ${storeShort}">🛒</a>`;
                }
                const icon = storeIcon(sl.store_name);
                return `<div class="store-price-row">
                    <span class="store-label">${icon}${storeShort}</span>
                    <span class="delivery-info">${deliveryShort}</span>
                    <span class="store-price-val">${price} ${buyIcon}</span>
                </div>`;
            }).join('');
            storePricesHtml = `<div class="store-prices">${rows}</div>`;
        }

        // Image with emoji fallback — centered, clickable for lightbox
        const imageHtml = imgUrl
            ? `<div style="text-align:center;"><img class="product-img" src="${imgUrl}" alt="${p.canonical_name}" onclick="openLightbox('${imgUrl.replace(/'/g, "\\'")}')" onerror="this.style.display='none';this.parentElement.nextElementSibling.style.display='block'" style="margin:0 auto;"></div><div class="product-emoji" style="display:none">${emoji}</div>`
            : `<div class="product-emoji">${emoji}</div>`;

        // WhatsApp notify inline
        const notifyHtml = `
            <div class="notify-inline">
                <p>📧 Email alert when back in stock</p>
                <div class="notify-inline-row">
                    <input type="email" id="notifyEmail_${p.id}" placeholder="your@email.com">
                    <button onclick="event.stopPropagation(); notifyProduct(${p.id})">Notify</button>
                </div>
                <div id="notifyConf_${p.id}" style="font-size:11px; margin-top:4px; color:#667eea;"></div>
            </div>`;

        return `<div class="product-card ${color}">
            ${imageHtml}
            <div class="product-name">${p.canonical_name}${p.variant ? ' ' + p.variant : ''}</div>
            <div class="product-status ${statusClass}">${statusText}</div>
            ${storePricesHtml}
            ${notifyHtml}
        </div>`;
    }).join('');
}

// Show sighting modal
function showSightingModal(productName = '') {
    const modal = document.getElementById('sightingModal');
    modal.classList.add('show');
    if (productName) {
        const select = document.getElementById('sightProduct');
        const opts = select.querySelectorAll('option');
        opts.forEach(opt => {
            if (opt.textContent.includes(productName)) {
                select.value = opt.value;
            }
        });
    }
}

function closeSightingModal() {
    document.getElementById('sightingModal').classList.remove('show');
}

// Submit sighting
async function submitSighting() {
    const product = document.getElementById('sightProduct').value;
    const store = document.getElementById('sightStore').value;
    const mall = document.getElementById('sightMall').value;
    const city = document.getElementById('sightCity').value;

    if (!mall) {
        toast('Please enter the location!');
        return;
    }

    const data = await api('/api/sighting', {
        method: 'POST',
        body: JSON.stringify({ product, store, mall, city })
    });

    if (data.success) {
        toast('🎉 Thanks for the sighting! You\'re awesome!');
        closeSightingModal();
        refreshDashboard();
    } else {
        toast('Oops! ' + (data.message || 'Something went wrong'));
    }
}

// Email subscription — subscribe to a specific product
async function notifyProduct(productId) {
    const email = document.getElementById('notifyEmail_' + productId).value.trim();

    if (!email) {
        toast('Please enter your email address!');
        return;
    }

    if (!email.includes('@') || !email.includes('.')) {
        toast('Please enter a valid email address');
        return;
    }

    const data = await api('/api/email-subscribe', {
        method: 'POST',
        body: JSON.stringify({ email, product_id: productId })
    });

    if (data.success) {
        toast('📧 You will be notified by email!');
        const conf = document.getElementById('notifyConf_' + productId);
        if (conf) {
            conf.textContent = `✅ ${data.email} will be notified!`;
        }
    } else {
        toast('Error: ' + (data.error || 'Try again'));
    }
}

// Populate product selects
function populateSelects(products) {
    const opts = products.map(p => {
        const emoji = getEmoji(p.canonical_name);
        const name = p.canonical_name + (p.variant ? ` (${p.variant})` : '');
        return `<option value="${p.canonical_name}">${emoji} ${name}</option>`;
    }).join('');

    document.getElementById('sightProduct').innerHTML = opts;
}
</script>
</body>
</html>
"""


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='NeeDoh Watch UAE — Web App')
    parser.add_argument('--port', type=int, default=5000, help='Port (default: 5000)')
    parser.add_argument('--seed', action='store_true', help='Seed database before starting')
    parser.add_argument('--host', default='0.0.0.0', help='Host (default: 0.0.0.0)')
    parser.add_argument('--debug', action='store_true', help='Debug mode')
    parser.add_argument('--auto-check', action='store_true', help='Start background checker automatically')
    args = parser.parse_args()

    init_db()
    if args.seed:
        seed_all()
    else:
        # Always ensure seed data exists
        seed_all()

    # Database migration: add Desertcart store and listings if missing
    try:
        with get_db() as conn:
            product_count = conn.execute("SELECT COUNT(*) as cnt FROM products").fetchone()['cnt']
            listing_count = conn.execute("SELECT COUNT(*) as cnt FROM listings").fetchone()['cnt']
            store_count = conn.execute("SELECT COUNT(*) as cnt FROM stores").fetchone()['cnt']

            print(f"  DB: {product_count} products, {store_count} stores, {listing_count} listings")

            # Add any new products from seed that aren't in DB yet
            from data.seed import PRODUCTS as SEED_PRODUCTS, SEARCH_TERMS, STORE_URL_TEMPLATES
            existing_names = [r['canonical_name'] for r in
                              conn.execute("SELECT canonical_name FROM products").fetchall()]
            store_rows = conn.execute("SELECT id, name FROM stores").fetchall()
            store_ids = {r['name']: r['id'] for r in store_rows}

            new_count = 0
            for idx, p in enumerate(SEED_PRODUCTS):
                if p['canonical_name'] not in existing_names:
                    cursor = conn.execute(
                        "INSERT INTO products (canonical_name, variant, aliases) VALUES (?, ?, ?)",
                        (p['canonical_name'], p.get('variant'), json.dumps(p.get('aliases', [])))
                    )
                    new_pid = cursor.lastrowid
                    # Add listings for this product on Amazon + Noon
                    term = SEARCH_TERMS.get(idx, 'needoh')
                    for store_name, sid in store_ids.items():
                        if store_name == 'Amazon.ae':
                            url = f"https://www.amazon.ae/s?k={term}"
                        elif store_name == 'Noon':
                            url = f"https://www.noon.com/uae-en/search/?q={term}"
                        elif store_name == 'Ubuy':
                            url = f"https://www.ubuy.ae/en/search?q={term}"
                        elif store_name == 'Desertcart':
                            url = f"https://www.desertcart.ae/search?query={term}"
                        else:
                            continue
                        conn.execute(
                            "INSERT INTO listings (product_id, store_id, url) VALUES (?, ?, ?)",
                            (new_pid, sid, url)
                        )
                    new_count += 1
                    print(f"  + Added: {p['canonical_name']}")

            if new_count > 0:
                print(f"  ✓ Added {new_count} new products with listings")
            else:
                print(f"  ✓ All products already in DB")

            # Migration: add Desertcart store if missing
            desertcart = conn.execute("SELECT id FROM stores WHERE name = 'Desertcart'").fetchone()
            if not desertcart:
                print("  Adding Desertcart store...")
                cursor = conn.execute(
                    """INSERT INTO stores (name, type, city, base_url, supports_store_check, check_interval_minutes)
                       VALUES ('Desertcart', 'online', 'UAE', 'https://www.desertcart.ae', 0, 15)"""
                )
                dc_store_id = cursor.lastrowid

                # Add Desertcart listings for all products
                products = conn.execute("SELECT id, canonical_name FROM products ORDER BY id").fetchall()
                from data.seed import SEARCH_TERMS
                product_list = list(products)
                for idx, product in enumerate(product_list):
                    term = SEARCH_TERMS.get(idx, 'needoh')
                    url = f"https://www.desertcart.ae/search?query={term}"
                    conn.execute(
                        "INSERT INTO listings (product_id, store_id, url) VALUES (?, ?, ?)",
                        (product['id'], dc_store_id, url)
                    )
                print(f"  ✓ Added Desertcart store + {len(product_list)} listings")
            else:
                print(f"  ✓ Desertcart store already exists")

            final_listings = conn.execute("SELECT COUNT(*) as cnt FROM listings").fetchone()['cnt']
            final_stores = conn.execute("SELECT COUNT(*) as cnt FROM stores").fetchone()['cnt']
            print(f"  ✓ DB OK: {product_count} products, {final_stores} stores, {final_listings} listings")

            # Add delivery_estimate column if missing (migration)
            try:
                conn.execute("SELECT delivery_estimate FROM listings LIMIT 1")
            except Exception:
                conn.execute("ALTER TABLE listings ADD COLUMN delivery_estimate TEXT")
                print("  ✓ Added delivery_estimate column")

            # Set known Noon product URLs for new products (from user-discovered links)
            noon_urls = {
                'NeeDoh Nice-Sicle': 'https://www.noon.com/uae-en/popsicle-squishy-toy-stress-relief-fidget-toy-soft-tpr-sensory-squeeze-ball-for-kids-adults-portable-anxiety-relief-popsicle/Z4499AFBF507B04CBA10AZ/p/',
                'NeeDoh Peace O Cake': 'https://www.noon.com/uae-en/needoh-peace-o-cake-squishy-toy-colorful-cake-shaped-stress-relief-fidget-toy/Z481EFFE77BA5C0F38735Z/p/',
                'NeeDoh Dippin Dazzler': 'https://www.noon.com/uae-en/needoh-dippin-dazzler-easter-color-changing-egg-color-random/Z52AB0A71FBDA8332EE20Z/p/',
                'NeeDoh Jelly Hops': 'https://www.noon.com/uae-en/needoh-jelly-hops-scented-squishy-bunny-fidget-toy-stress-relief-sensory-squeeze-toy-for-kids-adults-anti-anxiety-adhd-focus-desk-toy-pink/ZFC0760281D8F42A6D757Z/p/',
                'NeeDoh Advent Calendar': 'https://www.noon.com/uae-en/calendar-24-days-of-surprises-squishy-fidget-toys-set-soft-tpr-stress-relief-toys-for-kids-holiday-countdown-calendar-gift-for-boys-girls/Z8594BDDE3038AF2B9C81Z/p/',
            }
            noon_store = conn.execute("SELECT id FROM stores WHERE name = 'Noon'").fetchone()
            if noon_store:
                noon_id = noon_store['id']
                for pname, purl in noon_urls.items():
                    product = conn.execute("SELECT id FROM products WHERE canonical_name = ?", (pname,)).fetchone()
                    if product:
                        conn.execute("""
                            UPDATE listings SET url = ?, stock_status = 'IN_STOCK'
                            WHERE product_id = ? AND store_id = ? AND url LIKE '%search%'
                        """, (purl, product['id'], noon_id))
                print("  ✓ Updated known Noon product URLs")

            # Migration: Remove duplicate "Color Change Cube" (duplicate of "Color Change")
            dup = conn.execute("SELECT id FROM products WHERE canonical_name = 'NeeDoh Color Change Cube'").fetchone()
            if dup:
                conn.execute("DELETE FROM check_log WHERE listing_id IN (SELECT id FROM listings WHERE product_id = ?)", (dup['id'],))
                conn.execute("DELETE FROM alerts WHERE listing_id IN (SELECT id FROM listings WHERE product_id = ?)", (dup['id'],))
                conn.execute("DELETE FROM listings WHERE product_id = ?", (dup['id'],))
                conn.execute("DELETE FROM sightings WHERE product_id = ?", (dup['id'],))
                conn.execute("DELETE FROM subscriptions WHERE product_id = ?", (dup['id'],))
                conn.execute("DELETE FROM products WHERE id = ?", (dup['id'],))
                print("  ✓ Removed duplicate 'Color Change Cube' (same as 'Color Change')")

            # Migration: Fix conflicting aliases
            alias_fixes = {
                'NeeDoh Nice Cube': ['Nice Cube', 'Schylling Nice Cube', 'Nee Doh Nice Cube'],
                'NeeDoh Cool Cats': ['Cool Cats NeeDoh', 'Schylling Cool Cats', 'Nee Doh Cool Cats'],
                'NeeDoh Fuzz Ball': ['Fuzz Ball', 'Nee Doh Fuzz Ball', 'Needoh Fuzzball'],
            }
            for pname, aliases in alias_fixes.items():
                conn.execute("UPDATE products SET aliases = ? WHERE canonical_name = ?",
                             (json.dumps(aliases), pname))

            # Migration: Reset Noon listing URLs back to search URLs for products with no price
            # This fixes the bug where product page URLs replaced search URLs
            # but product pages can't be scraped from datacenter IPs
            noon_store_row = conn.execute("SELECT id FROM stores WHERE name = 'Noon'").fetchone()
            if noon_store_row:
                nid = noon_store_row['id']
                no_price = conn.execute("""
                    SELECT l.id, l.url, p.canonical_name FROM listings l
                    JOIN products p ON l.product_id = p.id
                    WHERE l.store_id = ? AND l.stock_status = 'IN_STOCK' AND l.last_price IS NULL
                    AND l.url NOT LIKE '%search%' AND l.url NOT LIKE '%/s?k=%'
                """, (nid,)).fetchall()
                for row in no_price:
                    # Build search URL from product name
                    search_term = row['canonical_name'].replace('NeeDoh ', 'needoh+').replace(' ', '+').lower()
                    search_url = f"https://www.noon.com/uae-en/search/?q={search_term}"
                    conn.execute("UPDATE listings SET url = ? WHERE id = ?", (search_url, row['id']))
                    print(f"  ✓ Reset Noon URL for {row['canonical_name']} (had no price)")

    except Exception as e:
        print(f"  ⚠ Database migration error: {e}")

    # Always start background checker — this is a monitoring tool
    bg_thread = threading.Thread(target=background_checker, args=(180,), daemon=True)
    bg_thread.start()
    print("  ✓ Background checker started (3 min cycle, 20 listings/batch)")

    print(f"\n{'='*50}")
    print(f"  🎯 NeeDoh Watch UAE")
    print(f"  Open http://localhost:{args.port} in your browser")
    print(f"{'='*50}\n")

    app.run(host=args.host, port=args.port, debug=args.debug)
