"""
Seed data for NeeDoh Watch MVP.
26 verified NeeDoh products by Schylling, across 3 UAE stores.
Products verified against schylling.com, myneedoh.com, and squeeze.toys
"""

from data.database import init_db, get_db
import json


PRODUCTS = [
    # 0 - Classic
    {"canonical_name": "NeeDoh Classic", "variant": "Groovy Glob", "aliases": ["NeeDoh Groovy Glob", "Nee Doh", "NeeDoh Original", "Schylling NeeDoh", "Groovy Glob"]},
    # 1 - Nice Cube
    {"canonical_name": "NeeDoh Nice Cube", "variant": None, "aliases": ["Nice Cube", "Schylling Nice Cube", "Nee Doh Nice Cube"]},
    # 2 - Gummy Bear
    {"canonical_name": "NeeDoh Gummy Bear", "variant": None, "aliases": ["Gummy Bear NeeDoh", "Schylling Gummy Bear", "Nee Doh Gummy Bear"]},
    # 3 - Cool Cats
    {"canonical_name": "NeeDoh Cool Cats", "variant": None, "aliases": ["Cool Cats NeeDoh", "Schylling Cool Cats", "Nee Doh Cool Cats"]},
    # 4 - Gumdrop
    {"canonical_name": "NeeDoh Gumdrop", "variant": None, "aliases": ["Gumdrop NeeDoh", "Schylling Gumdrop", "Textured Gumdrop"]},
    # 5 - Dream Drop
    {"canonical_name": "NeeDoh Dream Drop", "variant": None, "aliases": ["Dream Drop NeeDoh", "Schylling Dream Drop", "Nee Doh Dream Drop"]},
    # 6 - Mac N Squeeze
    {"canonical_name": "NeeDoh Mac N Squeeze", "variant": None, "aliases": ["Mac N Squeeze", "Mac and Squeeze", "Needoh Mac N Cheese", "Mac N Squeeze NeeDoh"]},
    # 7 - Ramen Noodlies
    {"canonical_name": "NeeDoh Ramen Noodlies", "variant": None, "aliases": ["Ramen Noodlies", "Nee Doh Ramen", "Needoh Ramen", "Noodlies NeeDoh"]},
    # 8 - Dig It Pig
    {"canonical_name": "NeeDoh Dig It Pig", "variant": None, "aliases": ["Dig It Pig", "Nee Doh Pig", "NeeDoh Pig"]},
    # 9 - Shaggy
    {"canonical_name": "NeeDoh Shaggy", "variant": None, "aliases": ["Shaggy NeeDoh", "Shaggy Groovy Glob", "Nee Doh Shaggy"]},
    # 10 - Fuzz Ball
    {"canonical_name": "NeeDoh Fuzz Ball", "variant": None, "aliases": ["Fuzz Ball", "Nee Doh Fuzz Ball", "Needoh Fuzzball"]},
    # 11 - Stardust
    {"canonical_name": "NeeDoh Stardust", "variant": None, "aliases": ["Stardust NeeDoh", "Stardust Shimmer", "Nee Doh Stardust"]},
    # 12 - Crystal
    {"canonical_name": "NeeDoh Crystal", "variant": None, "aliases": ["Crystal NeeDoh", "Nee Doh Crystal"]},
    # 13 - Marbleez
    {"canonical_name": "NeeDoh Marbleez", "variant": None, "aliases": ["Marbleez NeeDoh", "Mellow Marble NeeDoh", "Nee Doh Marbleez"]},
    # 14 - Groovy Fruit
    {"canonical_name": "NeeDoh Groovy Fruit", "variant": None, "aliases": ["Groovy Fruit", "Nee Doh Groovy Fruit", "Fruit NeeDoh"]},
    # 15 - Snowball Crunch
    {"canonical_name": "NeeDoh Snowball Crunch", "variant": None, "aliases": ["Snowball Crunch", "Snow Ball NeeDoh", "Nee Doh Snowball"]},
    # 16 - Glow in the Dark
    {"canonical_name": "NeeDoh Glow in the Dark", "variant": None, "aliases": ["Glow in the Dark NeeDoh", "Glow NeeDoh", "Nee Doh Glow"]},
    # 17 - Dohnuts
    {"canonical_name": "NeeDoh Dohnuts", "variant": None, "aliases": ["Dohnuts", "Jelly Donut NeeDoh", "Nee Doh Dohnuts", "Needoh Donuts", "Dohnut Holes"]},
    # 18 - Nice-Sicle
    {"canonical_name": "NeeDoh Nice-Sicle", "variant": None, "aliases": ["Nice-Sicle", "Nice Sicle NeeDoh", "Nee Doh Popsicle"]},
    # 19 - Color Change Cube (DUPLICATE of #66, removed via migration)
    {"canonical_name": "NeeDoh Color Change Cube", "variant": None, "aliases": ["Color Change Cube", "Colour Changing Cube", "Color Changing NeeDoh"]},
    # 20 - Dohjees
    {"canonical_name": "NeeDoh Dohjees", "variant": None, "aliases": ["Dohjees", "NeeDoh Collectible", "Nee Doh Dohjees"]},
    # 21 - Panic Pete
    {"canonical_name": "NeeDoh Panic Pete", "variant": None, "aliases": ["Panic Pete", "Panic Pete NeeDoh", "Nee Doh Panic Pete"]},
    # 22 - Chickadeedoos
    {"canonical_name": "NeeDoh Chickadeedoos", "variant": None, "aliases": ["Chickadeedoos", "Chickadee NeeDoh", "Nee Doh Chickadeedoos"]},
    # 23 - Jelly Squish
    {"canonical_name": "NeeDoh Jelly Squish", "variant": None, "aliases": ["Jelly Squish", "Jelly NeeDoh", "Nee Doh Jelly Squish"]},
    # 24 - Super NeeDoh
    {"canonical_name": "Super NeeDoh", "variant": "Jumbo", "aliases": ["Super NeeDoh", "Jumbo Needoh", "Large Needoh", "Super Nee Doh"]},
    # 25 - Teenie
    {"canonical_name": "NeeDoh Teenie", "variant": "Pack", "aliases": ["Teenie Pack", "Teenie NeeDoh", "Mini Needoh", "Teenie Gobs of Globs", "Rainboh Teenie", "Hot Shot Teenie"]},
    # 26 - Peace O Cake
    {"canonical_name": "NeeDoh Peace O Cake", "variant": None, "aliases": ["Peace O Cake", "Peace of Cake", "Piece of Cake NeeDoh", "Nee Doh Peace Cake"]},
    # 27 - Dippin Dazzler
    {"canonical_name": "NeeDoh Dippin Dazzler", "variant": None, "aliases": ["Dippin Dazzler", "Dazzler Eggs", "Dippin Dazzler Eggs", "Color Changing Egg"]},
    # 28 - Jelly Hops
    {"canonical_name": "NeeDoh Jelly Hops", "variant": None, "aliases": ["Jelly Hops", "Squishy Bunny", "Jelly Hops Bunny", "Nee Doh Jelly Hops"]},
    # 29 - Nice Ice Baby
    {"canonical_name": "NeeDoh Nice Ice Baby", "variant": None, "aliases": ["Nice Ice Baby", "Ice Baby NeeDoh", "Crushed Ice NeeDoh"]},
    # 30 - Nice Cream Cone
    {"canonical_name": "NeeDoh Nice Cream Cone", "variant": None, "aliases": ["Nice Cream Cone", "Ice Cream Cone NeeDoh", "Nice Cream"]},
    # 31 - Mello Mallo
    {"canonical_name": "NeeDoh Mello Mallo", "variant": None, "aliases": ["Mello Mallo", "Color Change Mello Mallo", "Marshmallow NeeDoh"]},
    # 32 - Nice Berg
    {"canonical_name": "NeeDoh Nice Berg", "variant": None, "aliases": ["Nice Berg", "Niceberg", "Nice Berg Swirl", "Nice Berg Glitter"]},
    # 33 - Booper
    {"canonical_name": "NeeDoh Booper", "variant": None, "aliases": ["Booper", "Booper NeeDoh", "Nee Doh Booper"]},
    # 34 - Funky Pups
    {"canonical_name": "NeeDoh Funky Pups", "variant": None, "aliases": ["Funky Pups", "Funky Pup", "Teenie Funky Pups", "Nee Doh Funky Pups"]},
    # 35 - Hot Shot
    {"canonical_name": "NeeDoh Hot Shot", "variant": None, "aliases": ["Hot Shot", "Hot Shots", "Hot Shot Sports", "Hot Shots Football"]},
    # 36 - Squeezza Pizza
    {"canonical_name": "NeeDoh Squeezza Pizza", "variant": None, "aliases": ["Squeezza Pizza", "Pizza NeeDoh", "Squeeze Pizza"]},
    # 37 - Atomic
    {"canonical_name": "NeeDoh Atomic", "variant": None, "aliases": ["Atomic NeeDoh", "Atomic Squeeze", "Nee Doh Atomic"]},
    # 38 - Sploot Splat
    {"canonical_name": "NeeDoh Sploot Splat", "variant": None, "aliases": ["Sploot Splat", "Sploot NeeDoh", "Nee Doh Sploot"]},
    # 39 - Lava Squish
    {"canonical_name": "NeeDoh Lava Squish", "variant": None, "aliases": ["Lava Squish", "Lava Squish N Flow", "Lava NeeDoh"]},
    # 40 - Advent Calendar
    {"canonical_name": "NeeDoh Advent Calendar", "variant": None, "aliases": ["Advent Calendar", "Squishmas Calendar", "24 Days NeeDoh", "NeeDoh Calendar"]},
    # 41 - Nice Cube Swirl
    {"canonical_name": "NeeDoh Nice Cube Swirl", "variant": None, "aliases": ["Nice Cube Swirl", "Swirl Cube", "Swirl Nice Cube"]},
    # 42 - Marble Egg
    {"canonical_name": "NeeDoh Marble Egg", "variant": None, "aliases": ["Marble Egg", "Magic Colour Egg", "Easter Egg NeeDoh"]},
    # 43 - Fuzz Ball Wonder Waves
    {"canonical_name": "NeeDoh Fuzz Ball Wonder Waves", "variant": None, "aliases": ["Wonder Waves", "Fuzz Ball Wonder Waves", "Wavy Fuzz Ball"]},
    # 44 - Dohnut Jelly Squeeze
    {"canonical_name": "NeeDoh Dohnut Jelly Squeeze", "variant": None, "aliases": ["Dohnut Jelly Squeeze", "Jelly Donut", "Dohnut Jelly"]},
    # 45 - Fuzz Ball Teenie
    {"canonical_name": "NeeDoh Fuzz Ball Teenie", "variant": None, "aliases": ["Fuzz Ball Teenie", "Teenie Fuzz Ball", "Mini Fuzz Ball"]},
    # 46 - Groovy Shroom
    {"canonical_name": "NeeDoh Groovy Shroom", "variant": None, "aliases": ["Groovy Shroom", "Mushroom NeeDoh", "Nee Doh Shroom"]},
    # 47 - Squeezy Peezy
    {"canonical_name": "NeeDoh Squeezy Peezy", "variant": None, "aliases": ["Squeezy Peezy", "Squeezy Peasy", "Nee Doh Squeezy Peezy"]},
    # 48 - Happy Snappy
    {"canonical_name": "NeeDoh Happy Snappy", "variant": None, "aliases": ["Happy Snappy", "Nee Doh Happy Snappy", "Snappy NeeDoh"]},
    # 49 - Squeeze Hearts
    {"canonical_name": "NeeDoh Squeeze Hearts", "variant": None, "aliases": ["Squeeze Hearts", "Color Change Heart", "Sparkle Squeeze Hearts"]},
    # 50 - Super NeeDoh Ripples
    {"canonical_name": "Super NeeDoh Ripples", "variant": None, "aliases": ["Super Ripples", "Ripples NeeDoh", "Super NeeDoh Ripples"]},
    # 51 - Snow Globe
    {"canonical_name": "NeeDoh Snow Globe", "variant": None, "aliases": ["Snow Globe", "Squishmas Snow Globe", "Christmas Snow Globe", "Squish N Snow Globe"]},
    # 52 - Super Cool Cats
    {"canonical_name": "Super NeeDoh Cool Cats", "variant": None, "aliases": ["Super Cool Cats", "Cool Cats Super", "Jumbo Cool Cats"]},
    # 53 - Fuzz Ball Flower Power
    {"canonical_name": "NeeDoh Fuzz Ball Flower Power", "variant": None, "aliases": ["Flower Power", "Fuzz Ball Flower Power", "Flower Fuzz Ball"]},
    # 54 - Good Vibes Only Heart
    {"canonical_name": "NeeDoh Good Vibes Only Heart", "variant": None, "aliases": ["Good Vibes Only", "Good Vibes Heart", "Heart NeeDoh"]},
    # 55 - Fuzz Ball Wild Cats
    {"canonical_name": "NeeDoh Fuzz Ball Wild Cats", "variant": None, "aliases": ["Fuzz Ball Wild Cats", "Wild Cats Fuzz Ball", "Fuzzy Cats"]},
    # 56 - Groovy Jewel
    {"canonical_name": "NeeDoh Groovy Jewel", "variant": None, "aliases": ["Groovy Jewel", "Jewel NeeDoh", "Globby Jewel"]},
    # 57 - (removed: Cloud Pleaser — product not verified)
    # 58 - Bubble Glob
    {"canonical_name": "NeeDoh Bubble Glob", "variant": None, "aliases": ["Bubble Glob", "Bubble NeeDoh", "Nee Doh Bubble"]},
    # 59 - Baby Boos
    {"canonical_name": "NeeDoh Baby Boos", "variant": None, "aliases": ["Baby Boos", "Baby Boo NeeDoh", "Nee Doh Baby Boos"]},
    # 60 - Dohzee
    {"canonical_name": "NeeDoh Dohzee", "variant": None, "aliases": ["Dohzee", "Dozy NeeDoh", "Nee Doh Dohzee"]},
    # 61 - Glowy Ghost
    {"canonical_name": "NeeDoh Glowy Ghost", "variant": None, "aliases": ["Glowy Ghost", "Glow Ghost", "Ghost NeeDoh"]},
    # 62 - Sugar Skull Cats
    {"canonical_name": "NeeDoh Sugar Skull Cats", "variant": None, "aliases": ["Sugar Skull Cats", "Sugar Skull", "Skull Cats NeeDoh"]},
    # 63 - Cool Cane
    {"canonical_name": "NeeDoh Cool Cane", "variant": None, "aliases": ["Cool Cane", "Candy Cane NeeDoh", "Christmas Cane"]},
    # 64 - Golden Egg Hunt
    {"canonical_name": "NeeDoh Golden Egg Hunt", "variant": None, "aliases": ["Golden Egg Hunt", "Egg Hunt", "Easter Egg Hunt NeeDoh"]},
    # 65 - Nice Cube Glow
    {"canonical_name": "NeeDoh Nice Cube Glow", "variant": None, "aliases": ["Nice Cube Glow", "Glitter Glow Cube", "Nice Cube Glitter"]},
    # 66 - Color Change
    {"canonical_name": "NeeDoh Color Change", "variant": None, "aliases": ["Color Change", "Colour Change", "Color Changing NeeDoh Ball"]},
    # 67 - Stickums
    {"canonical_name": "NeeDoh Stickums", "variant": None, "aliases": ["Stickums", "Nee Doh Stickums", "Sticky NeeDoh"]},
    # 68 - Swirl
    {"canonical_name": "NeeDoh Swirl", "variant": None, "aliases": ["NeeDoh Swirl", "Swirl Ball", "Nee Doh Swirl"]},
]

STORES = [
    {
        "name": "Amazon.ae",
        "type": "online",
        "city": "UAE",
        "base_url": "https://www.amazon.ae",
        "supports_store_check": 0,
        "check_interval_minutes": 720
    },
    {
        "name": "Noon",
        "type": "online",
        "city": "UAE",
        "base_url": "https://www.noon.com",
        "supports_store_check": 0,
        "check_interval_minutes": 720
    },
]

# Generate listings: every product on every store
# Store indices: 0=Amazon.ae, 1=Noon, 2=Ubuy
SEARCH_TERMS = {
    0: "needoh",               # NeeDoh Classic
    1: "needoh+nice+cube",     # Nice Cube
    2: "needoh+gummy+bear",    # Gummy Bear
    3: "needoh+cool+cats",     # Cool Cats
    4: "needoh+gumdrop",       # Gumdrop
    5: "needoh+dream+drop",    # Dream Drop
    6: "needoh+mac+n+squeeze", # Mac N Squeeze
    7: "needoh+ramen+noodlies",# Ramen Noodlies
    8: "needoh+dig+it+pig",    # Dig It Pig
    9: "needoh+shaggy",        # Shaggy
    10: "needoh+fuzz+ball",    # Fuzz Ball
    11: "needoh+stardust",     # Stardust
    12: "needoh+crystal",      # Crystal
    13: "needoh+marbleez",     # Marbleez
    14: "needoh+groovy+fruit", # Groovy Fruit
    15: "needoh+snowball+crunch", # Snowball Crunch
    16: "needoh+glow+in+the+dark", # Glow in the Dark
    17: "needoh+dohnuts",      # Dohnuts
    18: "needoh+nice+sicle",   # Nice-Sicle
    19: "needoh+color+change+cube", # Color Change Cube
    20: "needoh+dohjees",      # Dohjees
    21: "needoh+panic+pete",   # Panic Pete
    22: "needoh+chickadeedoos",# Chickadeedoos
    23: "needoh+jelly+squish", # Jelly Squish
    24: "super+needoh",        # Super NeeDoh
    25: "needoh+teenie",       # Teenie
    26: "needoh+peace+o+cake", # Peace O Cake
    27: "needoh+dippin+dazzler", # Dippin Dazzler
    28: "needoh+jelly+hops",   # Jelly Hops
    29: "needoh+nice+ice+baby", # Nice Ice Baby
    30: "needoh+nice+cream+cone", # Nice Cream Cone
    31: "needoh+mello+mallo",  # Mello Mallo
    32: "needoh+nice+berg",    # Nice Berg
    33: "needoh+booper",       # Booper
    34: "needoh+funky+pups",   # Funky Pups
    35: "needoh+hot+shot",     # Hot Shot
    36: "needoh+squeezza+pizza", # Squeezza Pizza
    37: "needoh+atomic",       # Atomic
    38: "needoh+sploot+splat", # Sploot Splat
    39: "needoh+lava+squish",  # Lava Squish
    40: "needoh+advent+calendar", # Advent Calendar
    41: "needoh+nice+cube+swirl", # Nice Cube Swirl
    42: "needoh+marble+egg",   # Marble Egg
    43: "needoh+fuzz+ball+wonder+waves", # Fuzz Ball Wonder Waves
    44: "needoh+dohnut+jelly+squeeze", # Dohnut Jelly Squeeze
    45: "needoh+fuzz+ball+teenie", # Fuzz Ball Teenie
    46: "needoh+groovy+shroom",  # Groovy Shroom
    47: "needoh+squeezy+peezy",  # Squeezy Peezy
    48: "needoh+happy+snappy",   # Happy Snappy
    49: "needoh+squeeze+hearts", # Squeeze Hearts
    50: "super+needoh+ripples",  # Super NeeDoh Ripples
    51: "needoh+snow+globe",     # Snow Globe
    52: "super+needoh+cool+cats", # Super Cool Cats
    53: "needoh+fuzz+ball+flower+power", # Fuzz Ball Flower Power
    54: "needoh+good+vibes+heart", # Good Vibes Only Heart
    55: "needoh+fuzz+ball+wild+cats", # Fuzz Ball Wild Cats
    56: "needoh+groovy+jewel",   # Groovy Jewel
    # 57 removed (Cloud Pleaser) — indices shifted down by 1
    57: "needoh+bubble+glob",    # Bubble Glob
    58: "needoh+baby+boos",      # Baby Boos
    59: "needoh+dohzee",         # Dohzee
    60: "needoh+glowy+ghost",    # Glowy Ghost
    61: "needoh+sugar+skull+cats", # Sugar Skull Cats
    62: "needoh+cool+cane",      # Cool Cane
    63: "needoh+golden+egg+hunt", # Golden Egg Hunt
    64: "needoh+nice+cube+glow", # Nice Cube Glow
    65: "needoh+color+change",   # Color Change
    66: "needoh+stickums",       # Stickums
    67: "needoh+swirl",          # Swirl
}

STORE_URL_TEMPLATES = {
    0: "https://www.amazon.ae/s?k={term}",
    1: "https://www.noon.com/uae-en/search/?q={term}",
}

def _generate_listings():
    """Generate all product×store listing combinations."""
    listings = []
    for product_idx, term in SEARCH_TERMS.items():
        for store_idx, url_template in STORE_URL_TEMPLATES.items():
            listings.append({
                "product_idx": product_idx,
                "store_idx": store_idx,
                "url": url_template.format(term=term),
            })
    return listings

LISTINGS = _generate_listings()


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
        print(f"✓ Seeded {len(LISTINGS)} listings ({len(PRODUCTS)} products × {len(STORES)} stores)")

    print("\n✓ Database seeded successfully!")


if __name__ == "__main__":
    seed_all()
