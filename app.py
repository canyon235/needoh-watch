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
import json
import threading
import time
import argparse
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


# ─── Background checker ───

def background_checker(interval=120):
    """Run stock checks in background."""
    global bg_running
    bg_running = True
    print(f"🔄 Background checker started (interval: {interval}s)")
    while bg_running:
        try:
            checker.reset_stats()
            stats = checker.run_check_cycle()
            print(f"  ✓ Background check: {stats['checks']} checked, {stats['changes']} changes")
        except Exception as e:
            print(f"  ✗ Background check error: {e}")
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
    interval = request.json.get('interval', 120) if request.json else 120
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
    <title>NeeDoh Watch UAE</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }

        :root {
            --bg: #0f1117;
            --surface: #1a1d27;
            --surface2: #242736;
            --border: #2e3144;
            --text: #e4e4e7;
            --text-dim: #8b8d9e;
            --accent: #7c5cfc;
            --accent-light: #9b82fc;
            --green: #22c55e;
            --yellow: #eab308;
            --red: #ef4444;
            --blue: #3b82f6;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Inter', sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
            min-height: 100vh;
        }

        /* Header */
        .header {
            background: linear-gradient(135deg, #1e1b4b 0%, #312e81 50%, #4c1d95 100%);
            padding: 20px 24px;
            border-bottom: 1px solid var(--border);
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 12px;
        }
        .header h1 {
            font-size: 22px;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .header-actions {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }

        /* Buttons */
        .btn {
            padding: 8px 16px;
            border-radius: 8px;
            border: 1px solid var(--border);
            background: var(--surface2);
            color: var(--text);
            cursor: pointer;
            font-size: 13px;
            font-weight: 500;
            transition: all 0.15s;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }
        .btn:hover { background: var(--border); }
        .btn-primary {
            background: var(--accent);
            border-color: var(--accent);
            color: white;
        }
        .btn-primary:hover { background: var(--accent-light); }
        .btn-sm { padding: 4px 10px; font-size: 12px; }
        .btn-green { background: #166534; border-color: #166534; }
        .btn-red { background: #991b1b; border-color: #991b1b; }

        /* Layout */
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }

        /* Stats row */
        .stats-row {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 12px;
            margin-bottom: 20px;
        }
        .stat-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 16px;
            text-align: center;
        }
        .stat-value { font-size: 28px; font-weight: 700; }
        .stat-label { font-size: 12px; color: var(--text-dim); margin-top: 2px; text-transform: uppercase; letter-spacing: 0.5px; }

        /* Tabs */
        .tabs {
            display: flex;
            gap: 4px;
            margin-bottom: 16px;
            border-bottom: 1px solid var(--border);
            padding-bottom: 0;
        }
        .tab {
            padding: 10px 18px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 500;
            color: var(--text-dim);
            border-bottom: 2px solid transparent;
            transition: all 0.15s;
        }
        .tab:hover { color: var(--text); }
        .tab.active {
            color: var(--accent-light);
            border-bottom-color: var(--accent);
        }

        /* Cards */
        .card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            overflow: hidden;
            margin-bottom: 16px;
        }
        .card-header {
            padding: 14px 18px;
            border-bottom: 1px solid var(--border);
            display: flex;
            align-items: center;
            justify-content: space-between;
            font-weight: 600;
        }

        /* Product table */
        .product-grid {
            display: grid;
            gap: 12px;
        }
        .product-row {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 16px;
            display: grid;
            grid-template-columns: 1fr auto auto auto;
            align-items: center;
            gap: 16px;
            transition: all 0.15s;
            cursor: pointer;
        }
        .product-row:hover { border-color: var(--accent); background: var(--surface2); }
        .product-name { font-weight: 600; font-size: 15px; }
        .product-variant { color: var(--text-dim); font-size: 13px; }

        /* Status badges */
        .badge {
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .badge-in-stock { background: rgba(34,197,94,0.15); color: var(--green); }
        .badge-low-stock { background: rgba(234,179,8,0.15); color: var(--yellow); }
        .badge-out-of-stock { background: rgba(239,68,68,0.15); color: var(--red); }
        .badge-unknown { background: rgba(139,141,158,0.15); color: var(--text-dim); }

        .price { font-weight: 600; color: var(--green); font-size: 15px; }
        .price-none { color: var(--text-dim); }

        /* Modal */
        .modal-overlay {
            position: fixed; top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0,0,0,0.7); z-index: 100;
            display: flex; align-items: center; justify-content: center;
            padding: 20px;
        }
        .modal {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 16px;
            width: 100%; max-width: 580px;
            max-height: 80vh; overflow-y: auto;
            padding: 24px;
        }
        .modal h2 { margin-bottom: 16px; }
        .modal-close {
            float: right; cursor: pointer; font-size: 24px;
            color: var(--text-dim); border: none; background: none;
        }
        .modal-close:hover { color: var(--text); }

        /* Forms */
        .form-group { margin-bottom: 14px; }
        .form-group label { display: block; font-size: 13px; color: var(--text-dim); margin-bottom: 4px; }
        .form-input {
            width: 100%; padding: 10px 12px;
            background: var(--surface2); border: 1px solid var(--border);
            border-radius: 8px; color: var(--text); font-size: 14px;
        }
        .form-input:focus { outline: none; border-color: var(--accent); }
        select.form-input { cursor: pointer; }

        /* Detail panel */
        .detail-stores { display: grid; gap: 10px; margin: 12px 0; }
        .store-row {
            display: flex; align-items: center; justify-content: space-between;
            padding: 12px; background: var(--surface2); border-radius: 8px;
        }
        .store-name { font-weight: 500; }

        /* Sightings */
        .sighting-item {
            padding: 12px; background: var(--surface2); border-radius: 8px;
            margin-bottom: 8px;
        }
        .sighting-location { font-weight: 500; }
        .sighting-meta { font-size: 12px; color: var(--text-dim); margin-top: 4px; }

        /* Alerts */
        .alert-item {
            padding: 12px 16px; border-bottom: 1px solid var(--border);
            font-size: 14px;
        }
        .alert-item:last-child { border-bottom: none; }
        .alert-time { font-size: 12px; color: var(--text-dim); }
        .alert-type {
            font-size: 11px; padding: 2px 8px; border-radius: 12px;
            background: var(--surface2); margin-left: 8px;
        }

        /* Toast */
        .toast {
            position: fixed; bottom: 20px; right: 20px; z-index: 200;
            padding: 12px 20px; border-radius: 10px;
            background: var(--accent); color: white;
            font-weight: 500; font-size: 14px;
            transform: translateY(100px); opacity: 0;
            transition: all 0.3s;
        }
        .toast.show { transform: translateY(0); opacity: 1; }

        /* Loading */
        .spinner {
            display: inline-block; width: 16px; height: 16px;
            border: 2px solid var(--border); border-top-color: var(--accent);
            border-radius: 50%; animation: spin 0.8s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }

        /* Responsive */
        @media (max-width: 768px) {
            .product-row { grid-template-columns: 1fr; gap: 8px; }
            .header { padding: 14px; }
            .header h1 { font-size: 18px; }
            .container { padding: 12px; }
            .stats-row { grid-template-columns: repeat(2, 1fr); }
        }

        .hidden { display: none !important; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🎯 NeeDoh Watch UAE</h1>
        <div class="header-actions">
            <button class="btn" onclick="refreshDashboard()">↻ Refresh</button>
            <button class="btn btn-primary" onclick="runCheck()">⚡ Check Now</button>
            <button class="btn" id="bgBtn" onclick="toggleBackground()">▶ Auto-Check</button>
            <button class="btn" onclick="showTrackModal()">+ Track</button>
            <button class="btn" onclick="showSightingModal()">👁 Report Sighting</button>
        </div>
    </div>

    <div class="container">
        <!-- Stats -->
        <div class="stats-row" id="statsRow">
            <div class="stat-card"><div class="stat-value" id="statTotal">—</div><div class="stat-label">Products</div></div>
            <div class="stat-card"><div class="stat-value" id="statInStock" style="color:var(--green)">—</div><div class="stat-label">In Stock</div></div>
            <div class="stat-card"><div class="stat-value" id="statOutStock" style="color:var(--red)">—</div><div class="stat-label">Out of Stock</div></div>
            <div class="stat-card"><div class="stat-value" id="statSightings" style="color:var(--yellow)">—</div><div class="stat-label">Sightings (24h)</div></div>
            <div class="stat-card"><div class="stat-value" id="statLowest" style="color:var(--green)">—</div><div class="stat-label">Lowest Price</div></div>
        </div>

        <!-- Tabs -->
        <div class="tabs">
            <div class="tab active" onclick="switchTab('products', this)">Products</div>
            <div class="tab" onclick="switchTab('alerts', this)">Alerts</div>
            <div class="tab" onclick="switchTab('wishlist', this)">Wishlist</div>
        </div>

        <!-- Products Tab -->
        <div id="tab-products">
            <div class="product-grid" id="productGrid">
                <div style="text-align:center; padding:40px; color:var(--text-dim)">
                    <div class="spinner"></div> Loading products...
                </div>
            </div>
        </div>

        <!-- Alerts Tab -->
        <div id="tab-alerts" class="hidden">
            <div class="card">
                <div class="card-header">Recent Alerts <span class="badge badge-unknown" id="alertCount">0</span></div>
                <div id="alertsList" style="max-height:500px; overflow-y:auto;">
                    <div class="alert-item" style="color:var(--text-dim)">Loading alerts...</div>
                </div>
            </div>
        </div>

        <!-- Wishlist Tab -->
        <div id="tab-wishlist" class="hidden">
            <div class="card">
                <div class="card-header">Your Tracked Products</div>
                <div id="wishlistContent" style="padding:16px;">
                    <div style="color:var(--text-dim)">Loading...</div>
                </div>
            </div>
        </div>
    </div>

    <!-- Product Detail Modal -->
    <div class="modal-overlay hidden" id="productModal" onclick="if(event.target===this)closeModal()">
        <div class="modal">
            <button class="modal-close" onclick="closeModal()">&times;</button>
            <div id="modalContent">Loading...</div>
        </div>
    </div>

    <!-- Track Modal -->
    <div class="modal-overlay hidden" id="trackModal" onclick="if(event.target===this)closeTrackModal()">
        <div class="modal">
            <button class="modal-close" onclick="closeTrackModal()">&times;</button>
            <h2>Track a Product</h2>
            <div class="form-group">
                <label>Product</label>
                <select class="form-input" id="trackProduct"></select>
            </div>
            <div class="form-group">
                <label>Max Price (AED) — optional</label>
                <input class="form-input" id="trackPrice" type="number" placeholder="e.g. 60">
            </div>
            <div class="form-group">
                <label>Your Email (for alerts)</label>
                <input class="form-input" id="trackEmail" type="email" placeholder="you@example.com">
            </div>
            <button class="btn btn-primary" onclick="submitTrack()" style="width:100%; margin-top:8px">Start Tracking</button>
        </div>
    </div>

    <!-- Sighting Modal -->
    <div class="modal-overlay hidden" id="sightingModal" onclick="if(event.target===this)closeSightingModal()">
        <div class="modal">
            <button class="modal-close" onclick="closeSightingModal()">&times;</button>
            <h2>👁 Report a Sighting</h2>
            <div class="form-group">
                <label>Product</label>
                <select class="form-input" id="sightProduct"></select>
            </div>
            <div class="form-group">
                <label>Store</label>
                <select class="form-input" id="sightStore">
                    <option value="Amazon.ae">Amazon.ae</option>
                    <option value="Noon">Noon</option>
                    <option value="Virgin Megastore UAE">Virgin Megastore UAE</option>
                    <option value="Other">Other</option>
                </select>
            </div>
            <div class="form-group">
                <label>Mall / Location</label>
                <input class="form-input" id="sightMall" placeholder="e.g. Dubai Mall, Mall of the Emirates">
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
            <button class="btn btn-primary" onclick="submitSighting()" style="width:100%; margin-top:8px">Submit Sighting</button>
        </div>
    </div>

    <!-- Toast -->
    <div class="toast" id="toast"></div>

<script>
let allProducts = [];
let bgRunning = false;

// ─── Init ───
document.addEventListener('DOMContentLoaded', () => {
    refreshDashboard();
    loadAlerts();
    loadWishlist();
    checkBgStatus();
});

// ─── API helpers ───
async function api(url, opts = {}) {
    const resp = await fetch(url, {
        headers: { 'Content-Type': 'application/json' },
        ...opts
    });
    return resp.json();
}

function toast(msg) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 3000);
}

// ─── Dashboard ───
async function refreshDashboard() {
    const data = await api('/api/dashboard');
    allProducts = data.products;
    renderStats(data.products);
    renderProducts(data.products);
    populateProductSelects(data.products);
}

function renderStats(products) {
    const total = products.length;
    const inStock = products.filter(p => (p.in_stock_count || 0) > 0).length;
    const outStock = products.filter(p => (p.in_stock_count || 0) === 0 && (p.listing_count || 0) > 0).length;
    const sightings = products.reduce((sum, p) => sum + (p.sighting_count_24h || 0), 0);
    const prices = products.map(p => p.lowest_price).filter(p => p && p > 0);
    const lowest = prices.length ? `AED ${Math.min(...prices).toFixed(0)}` : '—';

    document.getElementById('statTotal').textContent = total;
    document.getElementById('statInStock').textContent = inStock;
    document.getElementById('statOutStock').textContent = outStock;
    document.getElementById('statSightings').textContent = sightings;
    document.getElementById('statLowest').textContent = lowest;
}

function renderProducts(products) {
    const grid = document.getElementById('productGrid');
    if (!products.length) {
        grid.innerHTML = '<div style="text-align:center; padding:40px; color:var(--text-dim)">No products tracked yet.</div>';
        return;
    }

    grid.innerHTML = products.map(p => {
        const name = p.canonical_name;
        const variant = p.variant ? `<span class="product-variant">${p.variant}</span>` : '';
        const inStock = p.in_stock_count || 0;
        const total = p.listing_count || 0;
        const price = p.lowest_price ? `<span class="price">AED ${p.lowest_price.toFixed(0)}</span>` : '<span class="price-none">—</span>';

        let statusClass, statusText;
        if (inStock > 0) { statusClass = 'badge-in-stock'; statusText = `${inStock}/${total} In Stock`; }
        else if (!p.last_check) { statusClass = 'badge-unknown'; statusText = 'Not Checked'; }
        else { statusClass = 'badge-out-of-stock'; statusText = 'Out of Stock'; }

        const sightings = p.sighting_count_24h ? `<span style="color:var(--yellow); font-size:12px">👁 ${p.sighting_count_24h}</span>` : '';

        return `<div class="product-row" onclick="showProduct(${p.id})">
            <div><div class="product-name">${name} ${variant}</div></div>
            <div>${sightings}</div>
            <div><span class="badge ${statusClass}">${statusText}</span></div>
            <div>${price}</div>
        </div>`;
    }).join('');
}

// ─── Product Detail ───
async function showProduct(id) {
    document.getElementById('productModal').classList.remove('hidden');
    document.getElementById('modalContent').innerHTML = '<div style="text-align:center; padding:20px"><div class="spinner"></div></div>';

    const data = await api(`/api/product/${id}`);
    if (data.error) {
        document.getElementById('modalContent').innerHTML = `<p>${data.error}</p>`;
        return;
    }

    const p = data.product;
    const name = p.canonical_name + (p.variant ? ` (${p.variant})` : '');

    let storesHtml = data.listings.map(l => {
        const statusClass = l.stock_status === 'IN_STOCK' ? 'badge-in-stock'
            : l.stock_status === 'OUT_OF_STOCK' ? 'badge-out-of-stock'
            : l.stock_status === 'LOW_STOCK' ? 'badge-low-stock' : 'badge-unknown';
        const price = l.last_price ? `AED ${l.last_price.toFixed(0)}` : '—';
        const checked = l.last_checked_at ? new Date(l.last_checked_at + 'Z').toLocaleTimeString() : 'Never';
        return `<div class="store-row">
            <div>
                <div class="store-name">${l.store_name}</div>
                <div style="font-size:12px; color:var(--text-dim)">Checked: ${checked}</div>
            </div>
            <div style="text-align:right">
                <span class="badge ${statusClass}">${l.stock_status || 'UNKNOWN'}</span>
                <div style="font-size:14px; margin-top:4px; font-weight:600">${price}</div>
            </div>
        </div>`;
    }).join('');

    let sightingsHtml = '';
    if (data.sightings.length > 0) {
        sightingsHtml = '<h3 style="margin:16px 0 8px">👁 Recent Sightings</h3>' +
            data.sightings.slice(0, 5).map(s => {
                const loc = s.mall_name || s.store_full_name || s.store_name || 'Unknown';
                const conf = s.confidence_score >= 80 ? 'High' : s.confidence_score >= 50 ? 'Medium' : 'Low';
                const confColor = s.confidence_score >= 80 ? 'var(--green)' : s.confidence_score >= 50 ? 'var(--yellow)' : 'var(--red)';
                const time = s.reported_at ? new Date(s.reported_at + 'Z').toLocaleString() : '';
                return `<div class="sighting-item">
                    <div class="sighting-location">📍 ${loc}</div>
                    <div class="sighting-meta">
                        <span style="color:${confColor}; font-weight:600">${conf} confidence</span>
                        (${s.confidence_score}/100) · ${time}
                    </div>
                </div>`;
            }).join('');
    }

    document.getElementById('modalContent').innerHTML = `
        <h2 style="margin-bottom:16px">${name}</h2>
        <h3 style="margin-bottom:8px">Store Availability</h3>
        <div class="detail-stores">${storesHtml || '<div style="color:var(--text-dim)">No listings yet</div>'}</div>
        ${sightingsHtml}
        <div style="margin-top:16px; display:flex; gap:8px">
            <button class="btn btn-primary btn-sm" onclick="runProductCheck('${p.canonical_name}')">⚡ Check Now</button>
            <button class="btn btn-sm" onclick="trackFromModal('${p.canonical_name}')">+ Track</button>
        </div>
    `;
}

function closeModal() { document.getElementById('productModal').classList.add('hidden'); }

async function runProductCheck(name) {
    toast('Checking...');
    await api('/api/check', { method: 'POST', body: JSON.stringify({ product: name }) });
    toast('Check complete!');
    closeModal();
    refreshDashboard();
}

// ─── Track ───
function populateProductSelects(products) {
    const opts = products.map(p => {
        const name = p.canonical_name + (p.variant ? ` (${p.variant})` : '');
        return `<option value="${p.canonical_name}">${name}</option>`;
    }).join('');
    document.getElementById('trackProduct').innerHTML = opts;
    document.getElementById('sightProduct').innerHTML = opts;
}

function showTrackModal() { document.getElementById('trackModal').classList.remove('hidden'); }
function closeTrackModal() { document.getElementById('trackModal').classList.add('hidden'); }

function trackFromModal(name) {
    closeModal();
    showTrackModal();
    document.getElementById('trackProduct').value = name;
}

async function submitTrack() {
    const product = document.getElementById('trackProduct').value;
    const price = document.getElementById('trackPrice').value;
    const email = document.getElementById('trackEmail').value;

    const data = await api('/api/track', {
        method: 'POST',
        body: JSON.stringify({ product, max_price: price || null, email })
    });

    if (data.success) {
        toast(`Now tracking ${data.product}!`);
        closeTrackModal();
        loadWishlist();
    } else {
        toast(data.error || 'Failed to track');
    }
}

// ─── Sightings ───
function showSightingModal() { document.getElementById('sightingModal').classList.remove('hidden'); }
function closeSightingModal() { document.getElementById('sightingModal').classList.add('hidden'); }

async function submitSighting() {
    const product = document.getElementById('sightProduct').value;
    const store = document.getElementById('sightStore').value;
    const mall = document.getElementById('sightMall').value;
    const city = document.getElementById('sightCity').value;

    const data = await api('/api/sighting', {
        method: 'POST',
        body: JSON.stringify({ product, store, mall, city })
    });

    toast(data.message || (data.success ? 'Sighting recorded!' : 'Error'));
    closeSightingModal();
    refreshDashboard();
}

// ─── Alerts ───
async function loadAlerts() {
    const data = await api('/api/alerts?hours=48');
    const list = document.getElementById('alertsList');
    document.getElementById('alertCount').textContent = data.length;

    if (!data.length) {
        list.innerHTML = '<div class="alert-item" style="color:var(--text-dim)">No alerts in the last 48 hours</div>';
        return;
    }

    list.innerHTML = data.map(a => {
        const time = a.sent_at ? new Date(a.sent_at + 'Z').toLocaleString() : '';
        const typeColors = {
            restock: 'var(--green)', price_drop: 'var(--blue)',
            out_of_stock: 'var(--red)', sighting: 'var(--yellow)',
            store_available: 'var(--accent)', price_threshold: 'var(--blue)'
        };
        const color = typeColors[a.alert_type] || 'var(--text-dim)';
        return `<div class="alert-item">
            <div>${a.message}</div>
            <div style="margin-top:4px">
                <span class="alert-time">${time}</span>
                <span class="alert-type" style="color:${color}">${a.alert_type}</span>
            </div>
        </div>`;
    }).join('');
}

// ─── Wishlist ───
async function loadWishlist() {
    const data = await api('/api/wishlist');
    const el = document.getElementById('wishlistContent');

    if (!data.length) {
        el.innerHTML = '<div style="color:var(--text-dim); padding:20px; text-align:center">No tracked products. Click "+ Track" to start.</div>';
        return;
    }

    el.innerHTML = data.map(s => `
        <div class="store-row" style="margin-bottom:8px">
            <div>
                <div class="store-name">${s.product}</div>
                <div style="font-size:12px; color:var(--text-dim)">
                    ${s.max_price ? `Max: AED ${s.max_price}` : 'Any price'}
                </div>
            </div>
            <button class="btn btn-sm btn-red" onclick="untrack('${s.product}')">Remove</button>
        </div>
    `).join('');
}

async function untrack(product) {
    await api('/api/untrack', { method: 'POST', body: JSON.stringify({ product }) });
    toast('Removed from wishlist');
    loadWishlist();
}

// ─── Background checker ───
async function checkBgStatus() {
    const data = await api('/api/check/status');
    bgRunning = data.background_running;
    updateBgBtn();
}

function updateBgBtn() {
    const btn = document.getElementById('bgBtn');
    if (bgRunning) {
        btn.textContent = '⏸ Stop Auto';
        btn.classList.add('btn-green');
    } else {
        btn.textContent = '▶ Auto-Check';
        btn.classList.remove('btn-green');
    }
}

async function toggleBackground() {
    if (bgRunning) {
        await api('/api/background/stop', { method: 'POST' });
        bgRunning = false;
        toast('Auto-check stopped');
    } else {
        await api('/api/background/start', { method: 'POST', body: JSON.stringify({ interval: 120 }) });
        bgRunning = true;
        toast('Auto-check started (every 2 min)');
    }
    updateBgBtn();
}

async function runCheck() {
    toast('Running full check...');
    const data = await api('/api/check', { method: 'POST', body: '{}' });
    toast(`Done! ${data.checks || 0} checked, ${data.changes || 0} changes`);
    refreshDashboard();
    loadAlerts();
}

// ─── Tabs ───
function switchTab(tab, el) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    el.classList.add('active');
    ['products', 'alerts', 'wishlist'].forEach(t => {
        document.getElementById('tab-' + t).classList.toggle('hidden', t !== tab);
    });
    if (tab === 'alerts') loadAlerts();
    if (tab === 'wishlist') loadWishlist();
}

// Auto-refresh every 30s
setInterval(() => {
    refreshDashboard();
}, 30000);
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

    if args.auto_check:
        bg_thread = threading.Thread(target=background_checker, args=(120,), daemon=True)
        bg_thread.start()

    print(f"\n{'='*50}")
    print(f"  🎯 NeeDoh Watch UAE")
    print(f"  Open http://localhost:{args.port} in your browser")
    print(f"{'='*50}\n")

    app.run(host=args.host, port=args.port, debug=args.debug)
