#!/usr/bin/env python3
"""
NeeDoh Watch CLI - Command-line interface for interacting with the system.

Commands:
  /track <product> [under <price>]  - Subscribe to alerts for a product
  /stop <product>                   - Unsubscribe from a product
  /where <product>                  - Find where a product is available
  /seen <product> <store> [mall]    - Report a sighting
  /wishlist                         - View your subscriptions
  /status                           - View all product statuses
  /check [product]                  - Run an immediate check
  /dashboard                        - View full dashboard
  /products                         - List all tracked products
  /stores                           - List all stores
  /help                             - Show help
"""

import sys
import os
import argparse

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from data.database import (
    init_db, find_product, get_all_products, get_all_stores,
    get_listings_for_product, get_product_summary,
    get_dashboard_data, add_subscription, get_user_subscriptions,
    remove_subscription, get_recent_sightings, get_confidence_label
)
from engines.normalizer import generate_where_summary
from engines.offline_engine import OfflineEngine
from engines.checker import StockChecker
from notifications.notifier import Notifier

console = Console()
DEFAULT_USER = os.getenv('USER', 'default')


def cmd_track(args_str):
    """Subscribe to alerts for a product. Usage: /track nice cube [under 60]"""
    parts = args_str.strip()
    if not parts:
        console.print("[red]Usage: /track <product name> [under <max_price>][/]")
        return

    max_price = None
    if ' under ' in parts.lower():
        idx = parts.lower().index(' under ')
        try:
            max_price = float(parts[idx + 7:].strip())
            parts = parts[:idx].strip()
        except ValueError:
            pass

    products = find_product(parts)
    if not products:
        console.print(f"[yellow]No product found matching '{parts}'. Try a different name.[/]")
        console.print("Use [cyan]/products[/] to see all tracked products.")
        return

    product = products[0]
    product_name = product['canonical_name']
    if product['variant']:
        product_name += f" ({product['variant']})"

    email = os.getenv('EMAIL_RECIPIENTS', '').split(',')[0].strip() or None

    add_subscription(
        user_id=DEFAULT_USER,
        product_id=product['id'],
        max_price=max_price,
        notify_email=email,
        user_name=DEFAULT_USER,
    )

    price_text = f" under AED {max_price:.0f}" if max_price else ""
    console.print(Panel(
        f"✅ Now tracking [bold green]{product_name}[/]{price_text}\n"
        f"You'll be notified of restocks, price drops, and sightings.",
        title="Subscription Added"
    ))


def cmd_stop(args_str):
    """Unsubscribe from a product."""
    products = find_product(args_str.strip())
    if not products:
        console.print(f"[yellow]No product found matching '{args_str}'.[/]")
        return

    product = products[0]
    remove_subscription(DEFAULT_USER, product['id'])
    console.print(f"✅ Stopped tracking {product['canonical_name']}")


def cmd_where(args_str):
    """Find where a product is available."""
    if not args_str.strip():
        console.print("[red]Usage: /where <product name>[/]")
        return

    products = find_product(args_str.strip())
    if not products:
        console.print(f"[yellow]No product found matching '{args_str}'.[/]")
        return

    product = products[0]
    summary = get_product_summary(product['id'])

    product_name = product['canonical_name']
    if product['variant']:
        product_name += f" ({product['variant']})"

    where_text = generate_where_summary(
        product_name,
        summary['listings'],
        summary['sightings']
    )

    console.print(Panel(where_text, title=f"Where to find {product_name}"))


def cmd_seen(args_str):
    """Report a sighting. Usage: /seen nice cube virgin dubai mall"""
    parts = args_str.strip().split()
    if len(parts) < 2:
        console.print("[red]Usage: /seen <product> <store> [mall name][/]")
        console.print("Example: /seen nice cube virgin dubai mall")
        return

    # Try to parse: first find the product, then the store, then the mall
    # Simple approach: try different splits
    product_query = None
    store_name = None
    mall_name = None

    # Known store keywords
    store_keywords = {
        'amazon': 'Amazon.ae',
        'noon': 'Noon',
        'virgin': 'Virgin Megastore UAE',
    }

    # Find the store keyword
    store_idx = None
    for i, word in enumerate(parts):
        if word.lower() in store_keywords:
            store_name = store_keywords[word.lower()]
            store_idx = i
            break

    if store_idx is not None:
        product_query = ' '.join(parts[:store_idx])
        mall_parts = parts[store_idx + 1:]
        if mall_parts:
            mall_name = ' '.join(mall_parts)
    else:
        # No known store found, assume format: product store [mall]
        product_query = ' '.join(parts[:2])
        if len(parts) > 2:
            store_name = parts[2]
        if len(parts) > 3:
            mall_name = ' '.join(parts[3:])

    if not product_query:
        console.print("[red]Could not parse product name. Try: /seen <product> <store> [mall][/]")
        return

    offline = OfflineEngine()
    success, message, confidence = offline.report_sighting(
        product_query=product_query,
        store_name=store_name,
        mall_name=mall_name,
        reporter_id=DEFAULT_USER,
        reporter_name=DEFAULT_USER,
    )

    if success:
        console.print(Panel(message, title="Sighting Recorded", style="green"))
    else:
        console.print(f"[red]{message}[/]")


def cmd_wishlist(args_str):
    """View your active subscriptions."""
    subs = get_user_subscriptions(DEFAULT_USER)

    if not subs:
        console.print("[yellow]No active subscriptions. Use /track <product> to start.[/]")
        return

    table = Table(title="Your Wishlist", show_header=True)
    table.add_column("Product", style="cyan")
    table.add_column("Max Price", style="green")
    table.add_column("Notifications", style="yellow")

    for sub in subs:
        name = sub['canonical_name'] or sub['search_query'] or '?'
        if sub['variant']:
            name += f" ({sub['variant']})"
        price = f"AED {sub['max_price']:.0f}" if sub['max_price'] else "Any"
        notifs = []
        if sub['notify_online']:
            notifs.append("Online")
        if sub['notify_offline']:
            notifs.append("Offline")
        table.add_row(name, price, ', '.join(notifs))

    console.print(table)


def cmd_status(args_str):
    """View all product statuses."""
    data = get_dashboard_data()

    table = Table(title="NeeDoh Watch — Product Status", show_header=True)
    table.add_column("#", style="dim")
    table.add_column("Product", style="cyan", max_width=25)
    table.add_column("Listings", justify="center")
    table.add_column("In Stock", justify="center")
    table.add_column("Lowest Price", justify="right", style="green")
    table.add_column("Last Check", style="dim")

    for i, p in enumerate(data, 1):
        name = p['canonical_name']
        if p.get('variant'):
            name += f" ({p['variant']})"

        in_stock = p.get('in_stock_count', 0) or 0
        total = p.get('listing_count', 0) or 0
        stock_display = f"[green]{in_stock}[/]/{total}" if in_stock > 0 else f"[red]0[/]/{total}"

        price = f"AED {p['lowest_price']:.0f}" if p.get('lowest_price') else "—"

        last_check = p.get('last_check', '')
        if last_check:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(last_check)
                last_check = dt.strftime('%H:%M')
            except Exception:
                last_check = last_check[:16]

        table.add_row(str(i), name, str(total), stock_display, price, last_check or "Never")

    console.print(table)


def cmd_check(args_str):
    """Run an immediate stock check."""
    notifier = Notifier()
    checker = StockChecker(notifier=notifier)

    if args_str.strip():
        console.print(f"[cyan]Checking {args_str.strip()}...[/]")
        checker.check_single_product(args_str.strip())
    else:
        console.print("[cyan]Running full check cycle...[/]")
        stats = checker.run_check_cycle()
        console.print(f"\n✓ Done: {stats['checks']} checked, "
                      f"{stats['changes']} changes, {stats['errors']} errors")


def cmd_dashboard(args_str):
    """Show full dashboard."""
    console.print(Panel("[bold]NeeDoh Watch UAE[/] — Dashboard", style="bold blue"))

    # Product status
    cmd_status('')

    # Recent sightings across all products
    console.print("\n[bold]Recent Sightings (24h):[/]")
    products = get_all_products()
    any_sightings = False
    for product in products:
        sightings = get_recent_sightings(product['id'], hours=24)
        if sightings:
            any_sightings = True
            name = product['canonical_name']
            if product['variant']:
                name += f" ({product['variant']})"
            for s in sightings[:2]:
                loc = s['mall_name'] or s['store_full_name'] or 'Unknown'
                conf = get_confidence_label(s['confidence_score'])
                console.print(f"  👀 {name} @ {loc} — {conf} confidence")

    if not any_sightings:
        console.print("  [dim]No sightings in the last 24 hours[/]")


def cmd_products(args_str):
    """List all tracked products."""
    products = get_all_products()
    table = Table(title="Tracked Products", show_header=True)
    table.add_column("ID", style="dim")
    table.add_column("Product", style="cyan")
    table.add_column("Variant", style="yellow")
    table.add_column("Aliases", style="dim", max_width=40)

    import json
    for p in products:
        aliases = json.loads(p['aliases']) if p['aliases'] else []
        table.add_row(
            str(p['id']),
            p['canonical_name'],
            p['variant'] or '—',
            ', '.join(aliases[:3]) + ('...' if len(aliases) > 3 else '')
        )

    console.print(table)


def cmd_stores(args_str):
    """List all stores."""
    stores = get_all_stores()
    table = Table(title="Tracked Stores", show_header=True)
    table.add_column("ID", style="dim")
    table.add_column("Store", style="cyan")
    table.add_column("Type", style="yellow")
    table.add_column("City")
    table.add_column("Store Check", justify="center")
    table.add_column("Interval", justify="right")

    for s in stores:
        table.add_row(
            str(s['id']),
            s['name'],
            s['type'],
            s['city'] or '—',
            '✓' if s['supports_store_check'] else '—',
            f"{s['check_interval_minutes']}m"
        )

    console.print(table)


def cmd_help(args_str):
    """Show help."""
    help_text = """
[bold cyan]NeeDoh Watch UAE[/] — Track NeeDoh availability across UAE stores

[bold]Commands:[/]
  [green]/track[/] <product> [under <price>]  Subscribe to alerts
  [green]/stop[/] <product>                   Unsubscribe
  [green]/where[/] <product>                  Find availability
  [green]/seen[/] <product> <store> [mall]    Report a sighting
  [green]/wishlist[/]                         View subscriptions
  [green]/status[/]                           All product statuses
  [green]/check[/] [product]                  Run immediate check
  [green]/dashboard[/]                        Full dashboard
  [green]/products[/]                         List products
  [green]/stores[/]                           List stores
  [green]/help[/]                             This help

[bold]Examples:[/]
  /track nice cube
  /track fuzz ball under 60
  /where nice cube
  /seen nice cube virgin dubai mall
  /check snowball crunch
"""
    console.print(Panel(help_text, title="Help"))


COMMANDS = {
    '/track': cmd_track,
    '/stop': cmd_stop,
    '/where': cmd_where,
    '/seen': cmd_seen,
    '/wishlist': cmd_wishlist,
    '/status': cmd_status,
    '/check': cmd_check,
    '/dashboard': cmd_dashboard,
    '/products': cmd_products,
    '/stores': cmd_stores,
    '/help': cmd_help,
}


def run_interactive():
    """Run in interactive mode."""
    console.print(Panel(
        "[bold]NeeDoh Watch UAE[/]\n"
        "Track NeeDoh availability across Amazon.ae, Noon, and Virgin Megastore\n"
        "Type [green]/help[/] for commands or [green]/dashboard[/] to start",
        style="bold blue"
    ))

    while True:
        try:
            user_input = console.input("\n[bold blue]needoh>[/] ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n👋 Bye!")
            break

        if not user_input:
            continue

        if user_input.lower() in ('quit', 'exit', 'q'):
            console.print("👋 Bye!")
            break

        # Parse command
        parts = user_input.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ''

        # Add / prefix if missing
        if not cmd.startswith('/'):
            cmd = '/' + cmd

        handler = COMMANDS.get(cmd)
        if handler:
            handler(args)
        else:
            console.print(f"[red]Unknown command: {cmd}[/]. Type /help for commands.")


def run_single_command(args):
    """Run a single command from CLI arguments."""
    cmd = args[0].lower()
    if not cmd.startswith('/'):
        cmd = '/' + cmd
    rest = ' '.join(args[1:])

    handler = COMMANDS.get(cmd)
    if handler:
        handler(rest)
    else:
        console.print(f"[red]Unknown command: {cmd}[/]")
        cmd_help('')


if __name__ == "__main__":
    # Initialize DB
    init_db()

    if len(sys.argv) > 1:
        run_single_command(sys.argv[1:])
    else:
        run_interactive()
