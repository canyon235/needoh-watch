"""
Seed data for NeeDoh Watch MVP.
13 verified NeeDoh SKUs across 4 UAE-accessible stores.
Products verified against https://myneedoh.com
"""

from data.database import init_db, get_db
import json


PRODUCTS = [
    {"canonical_name": "Nice Cube", "variant": None, "aliases": ["NeeDoh Nice Cube", "Schylling Nice Cube", "Nee Doh Nice Cube", "Nice Ice Baby", "Swirl Nice Cube"]},
    {"canonical_name": "Snowball Crunch", "variant": None, "aliases": ["NeeDoh Snowball Crunch", "Snowball Crunch Needoh", "NeeDoh Snow Ball"]},
    {"canonical_name": "Dohnuts", "variant": None, "aliases": ["NeeDoh Dohnuts", "Nee Doh Dohnuts", "Needoh Donuts"]},
    {"canonical_name": "Teenie Needoh", "variant": "Pack", "aliases": ["Teenie Pack", "NeeDoh Teenie", "Mini Needoh", "Teenie Gobs of Globs", "Rainboh Teenie"]},
    {"canonical_name": "Gummy Bear", "variant": None, "aliases": ["NeeDoh Gummy Bear", "Nee Doh Gummy Bear"]},
    {"canonical_name": "Fuzz Ball", "variant": None, "aliases": ["NeeDoh Fuzz Ball", "Nee Doh Fuzz Ball", "Needoh Fuzzball"]},
    {"canonical_name": "Ramen Noodlies", "variant": None, "aliases": ["NeeDoh Ramen Noodlies", "Nee Doh Ramen", "Needoh Ramen"]},
    {"canonical_name": "Cool Cats", "variant": None, "aliases": ["NeeDoh Cool Cats", "Nee Doh Cool Cats"]},
    {"canonical_name": "Dig It Pig", "variant": None, "aliases": ["NeeDoh Dig It Pig", "Nee Doh Pig"]},
    {"canonical_name": "Mac N Squeeze", "variant": None, "aliases": ["NeeDoh Mac N Squeeze", "Mac and Squeeze", "Needoh Mac N Cheese"]},
    {"canonical_name": "Groovy Fruit", "variant": None, "aliases": ["NeeDoh Groovy Fruit", "Nee Doh Groovy Fruit"]},
    {"canonical_name": "NeeDoh Blob", "variant": "Original", "aliases": ["Nee Doh", "NeeDoh Original", "Schylling NeeDoh"]},
    {"canonical_name": "Super Needoh", "variant": "Jumbo", "aliases": ["Super NeeDoh", "Jumbo Needoh", "Large Needoh"]},
]

STORES = [
    {
        "name": "Amazon.ae",
        "type": "online",
        "city": "UAE",
        "base_url": "https://www.amazon.ae",
        "supports_store_check": 0,
        "check_interval_minutes": 5
    },
    {
        "name": "Noon",
        "type": "online",
        "city": "UAE",
        "base_url": "https://www.noon.com",
        "supports_store_check": 0,
        "check_interval_minutes": 5
    },
    {
        "name": "Desertcart",
        "type": "online",
        "city": "UAE",
        "base_url": "https://www.desertcart.ae",
        "supports_store_check": 0,
        "check_interval_minutes": 10
    },
    {
        "name": "Trendyol",
        "type": "online",
        "city": "UAE",
        "base_url": "https://www.trendyol.com",
        "supports_store_check": 0,
        "check_interval_minutes": 15
    },
]

# Product URLs per store (real search/category pages)
# Store indices: 0=Amazon.ae, 1=Noon, 2=Desertcart, 3=Trendyol
LISTINGS = [
    # Amazon.ae listings (store_idx=0)
    {"product_idx": 0, "store_idx": 0, "url": "https://www.amazon.ae/s?k=needoh+nice+cube"},
    {"product_idx": 1, "store_idx": 0, "url": "https://www.amazon.ae/s?k=needoh+snowball+crunch"},
    {"product_idx": 2, "store_idx": 0, "url": "https://www.amazon.ae/s?k=needoh+dohnuts"},
    {"product_idx": 3, "store_idx": 0, "url": "https://www.amazon.ae/s?k=needoh+teenie"},
    {"product_idx": 4, "store_idx": 0, "url": "https://www.amazon.ae/s?k=needoh+gummy+bear"},
    {"product_idx": 5, "store_idx": 0, "url": "https://www.amazon.ae/s?k=needoh+fuzz+ball"},
    {"product_idx": 6, "store_idx": 0, "url": "https://www.amazon.ae/s?k=needoh+ramen+noodlies"},
    {"product_idx": 7, "store_idx": 0, "url": "https://www.amazon.ae/s?k=needoh+cool+cats"},
    {"product_idx": 8, "store_idx": 0, "url": "https://www.amazon.ae/s?k=needoh+dig+it+pig"},
    {"product_idx": 9, "store_idx": 0, "url": "https://www.amazon.ae/s?k=needoh+mac+n+squeeze"},
    {"product_idx": 10, "store_idx": 0, "url": "https://www.amazon.ae/s?k=needoh+groovy+fruit"},
    {"product_idx": 11, "store_idx": 0, "url": "https://www.amazon.ae/s?k=needoh"},
    {"product_idx": 12, "store_idx": 0, "url": "https://www.amazon.ae/s?k=super+needoh"},

    # Noon listings (store_idx=1)
    {"product_idx": 0, "store_idx": 1, "url": "https://www.noon.com/uae-en/search/?q=needoh+nice+cube"},
    {"product_idx": 1, "store_idx": 1, "url": "https://www.noon.com/uae-en/search/?q=needoh+snowball+crunch"},
    {"product_idx": 2, "store_idx": 1, "url": "https://www.noon.com/uae-en/search/?q=needoh+dohnuts"},
    {"product_idx": 3, "store_idx": 1, "url": "https://www.noon.com/uae-en/search/?q=needoh+teenie"},
    {"product_idx": 4, "store_idx": 1, "url": "https://www.noon.com/uae-en/search/?q=needoh+gummy+bear"},
    {"product_idx": 5, "store_idx": 1, "url": "https://www.noon.com/uae-en/search/?q=needoh+fuzz+ball"},
    {"product_idx": 6, "store_idx": 1, "url": "https://www.noon.com/uae-en/search/?q=needoh+ramen"},
    {"product_idx": 11, "store_idx": 1, "url": "https://www.noon.com/uae-en/search/?q=needoh"},

    # Desertcart listings (store_idx=2) — JS-rendered, uses Playwright
    {"product_idx": 0, "store_idx": 2, "url": "https://www.desertcart.ae/search/needoh+nice+cube"},
    {"product_idx": 1, "store_idx": 2, "url": "https://www.desertcart.ae/search/needoh+snowball"},
    {"product_idx": 2, "store_idx": 2, "url": "https://www.desertcart.ae/search/needoh+dohnuts"},
    {"product_idx": 3, "store_idx": 2, "url": "https://www.desertcart.ae/search/needoh+teenie"},
    {"product_idx": 4, "store_idx": 2, "url": "https://www.desertcart.ae/search/needoh+gummy+bear"},
    {"product_idx": 5, "store_idx": 2, "url": "https://www.desertcart.ae/search/needoh+fuzz+ball"},
    {"product_idx": 6, "store_idx": 2, "url": "https://www.desertcart.ae/search/needoh+ramen"},
    {"product_idx": 11, "store_idx": 2, "url": "https://www.desertcart.ae/search/needoh"},
    {"product_idx": 12, "store_idx": 2, "url": "https://www.desertcart.ae/search/super+needoh"},

    # Trendyol listings (store_idx=3) — Cloudflare-protected, uses Playwright
    {"product_idx": 0, "store_idx": 3, "url": "https://www.trendyol.com/sr?q=needoh+nice+cube"},
    {"product_idx": 4, "store_idx": 3, "url": "https://www.trendyol.com/sr?q=needoh+gummy+bear"},
    {"product_idx": 5, "store_idx": 3, "url": "https://www.trendyol.com/sr?q=needoh+fuzz+ball"},
    {"product_idx": 11, "store_idx": 3, "url": "https://www.trendyol.com/sr?q=needoh"},
    {"product_idx": 2, "store_idx": 3, "url": "https://www.trendyol.com/sr?q=needoh+dohnuts"},
    {"product_idx": 12, "store_idx": 3, "url": "https://www.trendyol.com/sr?q=super+needoh"},
]


def seed_all():
    """Seed the database with all initial data."""
    init_db()

    with get_db() as conn:
        # Check if already seeded
        count = conn.execute("SELECT COUNT(*) as cnt FROM products").fetchone()['cnt']
        if count > 0:
            print(f"Database already has {count} products. Skipping seed.")
            return

        # Insert products
        product_ids = []
        for p in PRODUCTS:
            cursor = conn.execute(
                "INSERT INTO products (canonical_name, variant, aliases) VALUES (?, ?, ?)",
                (p['canonical_name'], p['variant'], json.dumps(p['aliases']))
            )
            product_ids.append(cursor.lastrowid)
        print(f"✓ Seeded {len(PRODUCTS)} products")

        # Insert stores
        store_ids = []
        for s in STORES:
            cursor = conn.execute(
                """INSERT INTO stores (name, type, city, mall, base_url, supports_store_check, check_interval_minutes)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (s['name'], s['type'], s['city'], s.get('mall'), s['base_url'],
                 s['supports_store_check'], s['check_interval_minutes'])
            )
            store_ids.append(cursor.lastrowid)
        print(f"✓ Seeded {len(STORES)} stores")

        # Insert listings
        for l in LISTINGS:
            conn.execute(
                "INSERT INTO listings (product_id, store_id, url) VALUES (?, ?, ?)",
                (product_ids[l['product_idx']], store_ids[l['store_idx']], l['url'])
            )
        print(f"✓ Seeded {len(LISTINGS)} listings")

    print("\n✓ Database seeded successfully!")


if __name__ == "__main__":
    seed_all()
