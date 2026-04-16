#!/usr/bin/env python3
"""
NeeDoh Watch — Main entry point.
Runs the continuous stock monitoring system.

Usage:
    python main.py              # Start monitoring daemon
    python main.py --once       # Run one check cycle and exit
    python main.py --seed       # Seed database only
    python main.py --cli        # Interactive CLI mode
    python main.py /track nice cube  # Single CLI command
"""

import sys
import os
import time
import signal
import argparse
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from data.database import init_db
from data.seed import seed_all
from engines.checker import StockChecker
from notifications.notifier import Notifier


def run_daemon(check_interval=60):
    """Run continuous monitoring."""
    print("=" * 55)
    print("  NeeDoh Watch UAE — Stock Monitor")
    print("  Tracking NeeDoh availability across UAE stores")
    print("=" * 55)
    print(f"  Started: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  Check interval: {check_interval}s base (per-store intervals apply)")
    print("  Press Ctrl+C to stop")
    print("=" * 55)

    notifier = Notifier()
    checker = StockChecker(notifier=notifier)

    running = True

    def signal_handler(sig, frame):
        nonlocal running
        print("\n\nShutting down gracefully...")
        running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    cycle = 0
    while running:
        cycle += 1
        print(f"\nCycle {cycle} — {datetime.utcnow().strftime('%H:%M:%S UTC')}")

        try:
            checker.reset_stats()
            stats = checker.run_check_cycle()
            print(f"\nCycle {cycle} complete: "
                  f"{stats['checks']} checked, "
                  f"{stats['changes']} changes, "
                  f"{stats['errors']} errors")
        except Exception as e:
            print(f"\nCycle {cycle} error: {e}")

        if running:
            print(f"  Next check in {check_interval}s...")
            for _ in range(check_interval):
                if not running:
                    break
                time.sleep(1)

    print("\nNeeDoh Watch stopped.")


def run_once():
    """Run a single check cycle."""
    print("NeeDoh Watch — Single Check Run")
    notifier = Notifier()
    checker = StockChecker(notifier=notifier)
    stats = checker.run_check_cycle()
    print(f"\nDone: {stats['checks']} checked, "
          f"{stats['changes']} changes, {stats['errors']} errors")
    return stats


def main():
    parser = argparse.ArgumentParser(description='NeeDoh Watch UAE — Stock Monitor')
    parser.add_argument('--seed', action='store_true', help='Seed the database')
    parser.add_argument('--once', action='store_true', help='Run one check and exit')
    parser.add_argument('--cli', action='store_true', help='Interactive CLI mode')
    parser.add_argument('--interval', type=int, default=60,
                        help='Base check interval in seconds (default: 60)')
    parser.add_argument('command', nargs='*', help='CLI command to run')

    args = parser.parse_args()

    # Always ensure DB exists
    init_db()

    if args.seed:
        seed_all()
        return

    if args.cli:
        from cli import run_interactive
        run_interactive()
        return

    if args.command:
        from cli import run_single_command
        run_single_command(args.command)
        return

    if args.once:
        seed_all()
        run_once()
        return

    # Default: seed and run daemon
    seed_all()
    run_daemon(check_interval=args.interval)


if __name__ == "__main__":
    main()
