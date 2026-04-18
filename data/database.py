"""
NeeDoh Watch - SQLite Database Layer
Handles all database operations: schema creation, CRUD for products, stores,
listings, subscriptions, sightings, and alert history.
"""

import sqlite3
import os
import json
from datetime import datetime, timedelta
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "needoh_watch.db")


@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create all tables if they don't exist."""
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                canonical_name TEXT NOT NULL,
                variant TEXT,
                aliases TEXT,  -- JSON array
                category TEXT DEFAULT 'needoh',
                image_url TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS stores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                type TEXT CHECK(type IN ('online', 'offline', 'hybrid')) DEFAULT 'online',
                city TEXT,
                mall TEXT,
                base_url TEXT,
                supports_store_check INTEGER DEFAULT 0,
                check_interval_minutes INTEGER DEFAULT 10,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS listings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                store_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                last_price REAL,
                currency TEXT DEFAULT 'AED',
                stock_status TEXT CHECK(stock_status IN ('IN_STOCK', 'LOW_STOCK', 'OUT_OF_STOCK', 'UNKNOWN')) DEFAULT 'UNKNOWN',
                previous_status TEXT,
                raw_text TEXT,
                seller_name TEXT,
                last_checked_at TEXT,
                last_changed_at TEXT,
                check_count INTEGER DEFAULT 0,
                error_count INTEGER DEFAULT 0,
                last_error TEXT,
                delivery_estimate TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (product_id) REFERENCES products(id),
                FOREIGN KEY (store_id) REFERENCES stores(id),
                UNIQUE(product_id, store_id, url)
            );

            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                user_name TEXT,
                product_id INTEGER,
                search_query TEXT,
                max_price REAL,
                preferred_stores TEXT,  -- JSON array of store IDs
                preferred_city TEXT,
                notify_online INTEGER DEFAULT 1,
                notify_offline INTEGER DEFAULT 1,
                notify_email TEXT,
                notify_whatsapp TEXT,
                active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (product_id) REFERENCES products(id)
            );

            CREATE TABLE IF NOT EXISTS sightings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                store_id INTEGER,
                store_name TEXT,
                mall_name TEXT,
                city TEXT DEFAULT 'Dubai',
                reported_at TEXT DEFAULT (datetime('now')),
                photo_url TEXT,
                reporter_id TEXT,
                reporter_name TEXT,
                notes TEXT,
                confidence_score INTEGER DEFAULT 25,
                confirmed_count INTEGER DEFAULT 1,
                source TEXT CHECK(source IN ('user', 'store_page', 'delivery_proxy')) DEFAULT 'user',
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (product_id) REFERENCES products(id),
                FOREIGN KEY (store_id) REFERENCES stores(id)
            );

            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id INTEGER,
                sighting_id INTEGER,
                alert_type TEXT NOT NULL,
                message TEXT NOT NULL,
                details TEXT,
                sent_to TEXT,
                sent_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (listing_id) REFERENCES listings(id),
                FOREIGN KEY (sighting_id) REFERENCES sightings(id)
            );

            CREATE TABLE IF NOT EXISTS check_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id INTEGER NOT NULL,
                status TEXT,
                price REAL,
                raw_html_snippet TEXT,
                checked_at TEXT DEFAULT (datetime('now')),
                duration_ms INTEGER,
                error TEXT,
                FOREIGN KEY (listing_id) REFERENCES listings(id)
            );

            CREATE TABLE IF NOT EXISTS page_views (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL,
                ip TEXT,
                user_agent TEXT,
                referrer TEXT,
                country TEXT,
                visited_at TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_page_views_visited ON page_views(visited_at);
            CREATE INDEX IF NOT EXISTS idx_listings_product ON listings(product_id);
            CREATE INDEX IF NOT EXISTS idx_listings_store ON listings(store_id);
            CREATE INDEX IF NOT EXISTS idx_listings_status ON listings(stock_status);
            CREATE INDEX IF NOT EXISTS idx_sightings_product ON sightings(product_id);
            CREATE INDEX IF NOT EXISTS idx_sightings_reported ON sightings(reported_at);
            CREATE INDEX IF NOT EXISTS idx_subscriptions_product ON subscriptions(product_id);
            CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_id);
            CREATE INDEX IF NOT EXISTS idx_alerts_sent ON alerts(sent_at);
        """)
    print("Database initialized")


def get_all_products():
    with get_db() as conn:
        return conn.execute("SELECT * FROM products ORDER BY canonical_name").fetchall()


def find_product(query):
    query_lower = f"%{query.lower()}%"
    with get_db() as conn:
        results = conn.execute("""
            SELECT * FROM products
            WHERE LOWER(canonical_name) LIKE ?
               OR LOWER(variant) LIKE ?
               OR LOWER(aliases) LIKE ?
            ORDER BY canonical_name
        """, (query_lower, query_lower, query_lower)).fetchall()
        return results


def add_product(canonical_name, variant=None, aliases=None, category='needoh', image_url=None):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO products (canonical_name, variant, aliases, category, image_url)
            VALUES (?, ?, ?, ?, ?)
        """, (canonical_name, variant, json.dumps(aliases or []), category, image_url))


def get_all_stores():
    with get_db() as conn:
        return conn.execute("SELECT * FROM stores ORDER BY name").fetchall()


def get_store_by_name(name):
    with get_db() as conn:
        return conn.execute("SELECT * FROM stores WHERE LOWER(name) LIKE ?",
                            (f"%{name.lower()}%",)).fetchone()


def get_listings_for_product(product_id):
    with get_db() as conn:
        return conn.execute("""
            SELECT l.*, p.canonical_name, p.variant,
                   s.name as store_name, s.type as store_type
            FROM listings l
            JOIN stores s ON l.store_id = s.id
            JOIN products p ON l.product_id = p.id
            WHERE l.product_id = ?
            ORDER BY s.name
        """, (product_id,)).fetchall()


def get_all_active_listings():
    with get_db() as conn:
        return conn.execute("""
            SELECT l.*, p.canonical_name, p.variant, s.name as store_name,
                   s.type as store_type, s.check_interval_minutes
            FROM listings l
            JOIN products p ON l.product_id = p.id
            JOIN stores s ON l.store_id = s.id
            ORDER BY l.last_checked_at ASC NULLS FIRST
        """).fetchall()


def get_listings_due_for_check():
    with get_db() as conn:
        return conn.execute("""
            SELECT l.*, p.canonical_name, p.variant, s.name as store_name,
                   s.type as store_type, s.check_interval_minutes, s.base_url
            FROM listings l
            JOIN products p ON l.product_id = p.id
            JOIN stores s ON l.store_id = s.id
            WHERE l.last_checked_at IS NULL
               OR (julianday('now') - julianday(l.last_checked_at)) * 24 * 60
                  >= s.check_interval_minutes
               OR (l.stock_status = 'IN_STOCK' AND l.last_price IS NULL
                   AND (julianday('now') - julianday(l.last_checked_at)) * 24 * 60 >= 2)
            ORDER BY
                CASE WHEN l.stock_status = 'IN_STOCK' AND l.last_price IS NULL THEN 0 ELSE 1 END,
                l.last_checked_at ASC NULLS FIRST
        """).fetchall()


def update_listing_status(listing_id, status, price=None, raw_text=None, seller=None, error=None, product_url=None, delivery_estimate=None):
    with get_db() as conn:
        old = conn.execute("SELECT stock_status, last_price FROM listings WHERE id = ?",
                           (listing_id,)).fetchone()
        previous_status = old['stock_status'] if old else None
        now = datetime.utcnow().isoformat()

        # Prevent status regression: don't overwrite a definitive status with UNKNOWN
        # This handles flaky scrapers that sometimes fail to find a product card
        if status == 'UNKNOWN' and previous_status in ('IN_STOCK', 'LOW_STOCK', 'OUT_OF_STOCK'):
            status = previous_status  # Keep the last known good status

        # Only count as "changed" if we had a previous definitive status
        # This prevents false alerts on first check after deploy/DB reset
        changed = (previous_status is not None and previous_status != status)
        conn.execute("""
            UPDATE listings SET
                stock_status = ?, previous_status = ?,
                last_price = COALESCE(?, last_price),
                raw_text = COALESCE(?, raw_text),
                seller_name = COALESCE(?, seller_name),
                url = CASE WHEN ? IS NOT NULL AND ? NOT LIKE '%/s?k=%' AND ? NOT LIKE '%/search?q=%' AND ? NOT LIKE '%/search?query=%' AND ? NOT LIKE '%/sr?q=%' THEN ? ELSE url END,
                last_checked_at = ?,
                last_changed_at = CASE WHEN ? THEN ? ELSE last_changed_at END,
                check_count = check_count + 1,
                error_count = CASE WHEN ? IS NOT NULL THEN error_count + 1 ELSE error_count END,
                last_error = ?,
                delivery_estimate = COALESCE(?, delivery_estimate)
            WHERE id = ?
        """, (status, previous_status, price, raw_text, seller,
              product_url, product_url, product_url, product_url, product_url, product_url,
              now, changed, now, error, error, delivery_estimate, listing_id))
        return {'changed': changed, 'previous_status': previous_status, 'new_status': status,
                'old_price': old['last_price'] if old else None, 'new_price': price}


def log_check(listing_id, status, price=None, raw_html=None, duration_ms=None, error=None):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO check_log (listing_id, status, price, raw_html_snippet, duration_ms, error)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (listing_id, status, price, raw_html[:2000] if raw_html else None, duration_ms, error))


def add_subscription(user_id, product_id=None, search_query=None, max_price=None,
                     notify_email=None, notify_whatsapp=None, user_name=None):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO subscriptions
            (user_id, user_name, product_id, search_query, max_price, notify_email, notify_whatsapp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, user_name, product_id, search_query, max_price, notify_email, notify_whatsapp))


def get_subscriptions_for_product(product_id):
    with get_db() as conn:
        return conn.execute("SELECT * FROM subscriptions WHERE product_id = ? AND active = 1",
                            (product_id,)).fetchall()


def get_user_subscriptions(user_id):
    with get_db() as conn:
        return conn.execute("""
            SELECT s.*, p.canonical_name, p.variant
            FROM subscriptions s LEFT JOIN products p ON s.product_id = p.id
            WHERE s.user_id = ? AND s.active = 1
        """, (user_id,)).fetchall()


def remove_subscription(user_id, product_id):
    with get_db() as conn:
        conn.execute("UPDATE subscriptions SET active = 0 WHERE user_id = ? AND product_id = ?",
                     (user_id, product_id))


def unsubscribe_email(email):
    """Unsubscribe an email from all alerts."""
    with get_db() as conn:
        conn.execute("UPDATE subscriptions SET active = 0 WHERE user_id = ? OR notify_email = ?",
                     (email, email))
        return conn.execute("SELECT changes()").fetchone()[0]


def add_sighting(product_id, store_id=None, store_name=None, mall_name=None,
                 city='Dubai', reporter_id=None, reporter_name=None,
                 photo_url=None, notes=None, source='user'):
    confidence = compute_sighting_confidence(product_id, store_id, source, photo_url)
    with get_db() as conn:
        conn.execute("""
            INSERT INTO sightings
            (product_id, store_id, store_name, mall_name, city, reporter_id,
             reporter_name, photo_url, notes, confidence_score, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (product_id, store_id, store_name, mall_name, city, reporter_id,
              reporter_name, photo_url, notes, confidence, source))
        return confidence


def get_recent_sightings(product_id, hours=48):
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    with get_db() as conn:
        return conn.execute("""
            SELECT si.*, s.name as store_full_name
            FROM sightings si LEFT JOIN stores s ON si.store_id = s.id
            WHERE si.product_id = ? AND si.reported_at >= ?
            ORDER BY si.reported_at DESC
        """, (product_id, cutoff)).fetchall()


def compute_sighting_confidence(product_id, store_id=None, source='user', photo_url=None):
    score = 25
    if source == 'store_page':
        score += 50
    elif source == 'delivery_proxy':
        score += 30
    if photo_url:
        score += 10
    if store_id:
        cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()
        with get_db() as conn:
            confirmations = conn.execute("""
                SELECT COUNT(*) as cnt FROM sightings
                WHERE product_id = ? AND store_id = ? AND reported_at >= ?
            """, (product_id, store_id, cutoff)).fetchone()
            if confirmations:
                score += min(confirmations['cnt'] * 15, 45)
    return min(score, 100)


def get_confidence_label(score):
    if score >= 80: return "High"
    elif score >= 50: return "Medium"
    else: return "Low"


def record_alert(listing_id=None, sighting_id=None, alert_type='restock',
                 message='', details=None, sent_to=None):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO alerts (listing_id, sighting_id, alert_type, message, details, sent_to)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (listing_id, sighting_id, alert_type, message,
              json.dumps(details) if details else None,
              json.dumps(sent_to) if sent_to else None))


def was_alert_sent_recently(listing_id, alert_type, hours=1):
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    with get_db() as conn:
        result = conn.execute("""
            SELECT COUNT(*) as cnt FROM alerts
            WHERE listing_id = ? AND alert_type = ? AND sent_at >= ?
        """, (listing_id, alert_type, cutoff)).fetchone()
        return result['cnt'] > 0


def get_product_summary(product_id):
    with get_db() as conn:
        product = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        listings = get_listings_for_product(product_id)
        sightings = get_recent_sightings(product_id)
        return {'product': dict(product) if product else None,
                'listings': [dict(l) for l in listings],
                'sightings': [dict(s) for s in sightings]}


def get_dashboard_data():
    with get_db() as conn:
        products = conn.execute("""
            SELECT p.*,
                   COUNT(DISTINCT l.id) as listing_count,
                   SUM(CASE WHEN l.stock_status = 'IN_STOCK' THEN 1 ELSE 0 END) as in_stock_count,
                   MIN(CASE WHEN l.last_price > 0 THEN l.last_price ELSE NULL END) as lowest_price,
                   MAX(l.last_checked_at) as last_check
            FROM products p LEFT JOIN listings l ON p.id = l.product_id
            GROUP BY p.id ORDER BY p.canonical_name
        """).fetchall()

        result = []
        for p in products:
            pd = dict(p)
            # Get per-store listing details for this product
            listings = conn.execute("""
                SELECT l.stock_status, l.last_price, l.url, l.delivery_estimate,
                       l.previous_status, l.last_changed_at,
                       s.name as store_name
                FROM listings l JOIN stores s ON l.store_id = s.id
                WHERE l.product_id = ?
                ORDER BY s.name
            """, (pd['id'],)).fetchall()
            pd['store_listings'] = [dict(l) for l in listings]
            result.append(pd)
        return result
