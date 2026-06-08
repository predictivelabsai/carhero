"""Send CarHero daily deals digest email via Postmark.

Usage:
    python -m scripts.daily_deals                       # uses env defaults
    python -m scripts.daily_deals --to user@example.com
    python -m scripts.daily_deals --all                 # send to all opted-in users
    python -m scripts.daily_deals --dry-run             # print HTML, don't send

The digest is designed to run after the nightly scrape finishes, so all
sections draw from freshly scraped data (default: last 36 hours).
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from utils.deals_scanner import (
    scan_deals, scan_lowest_prices, scan_new_listings, scan_price_drops,
    scan_freshness_stats, build_digest_html, build_digest_text,
)
from utils.email import send_email

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def _get_recipients(args) -> list[str]:
    """Return list of email addresses to send the digest to."""
    if not args.all:
        return [args.to]

    from db import engine
    from sqlalchemy import text
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT DISTINCT u.email
            FROM carhero.chat_users u
            LEFT JOIN carhero.user_profiles p ON p.user_id = u.id
            WHERE u.is_verified = TRUE
              AND u.email NOT LIKE '%guest%'
              AND COALESCE(p.notify_weekly_digest, TRUE) = TRUE
        """)).fetchall()
    emails = [r[0] for r in rows if r[0]]
    if not emails:
        emails = [args.to]
    return emails


def main():
    parser = argparse.ArgumentParser(description="Send CarHero deals digest")
    parser.add_argument("--to", default=os.getenv("TO_EMAIL", "carhero@predictivelabs.co.uk"))
    parser.add_argument("--from-email", default=os.getenv("FROM_EMAIL", "info@carhero.chat"))
    parser.add_argument("--dry-run", action="store_true", help="Print HTML without sending")
    parser.add_argument("--all", action="store_true", help="Send to all registered users with digest enabled")
    parser.add_argument("--deals", type=int, default=15, help="Number of top deals")
    parser.add_argument("--cheapest", type=int, default=10, help="Number of cheapest listings")
    parser.add_argument("--new", type=int, default=10, help="Number of new listings")
    parser.add_argument("--drops", type=int, default=10, help="Number of price drops")
    args = parser.parse_args()

    log.info("Scanning freshness stats...")
    stats = scan_freshness_stats()
    log.info("Stats: %s", stats)

    log.info("Scanning new listings...")
    new_listings = scan_new_listings(limit=args.new)
    log.info("Found %d new listings", len(new_listings))

    log.info("Scanning price drops...")
    price_drops = scan_price_drops(limit=args.drops)
    log.info("Found %d price drops", len(price_drops))

    log.info("Scanning price arbitrage deals...")
    deals = scan_deals(limit=args.deals)
    log.info("Found %d deals with price spread", len(deals))

    log.info("Scanning lowest prices...")
    cheapest = scan_lowest_prices(limit=args.cheapest)
    log.info("Found %d cheapest listings", len(cheapest))

    html = build_digest_html(deals, cheapest, new_listings, price_drops, stats)
    text = build_digest_text(deals, cheapest, new_listings, price_drops, stats)

    now = datetime.now()
    subject = f"CarHero Daily Deals — {now.strftime('%b %d, %Y')}"

    if args.dry_run:
        print(html)
        log.info("Dry run complete. Subject: %s", subject)
        return

    recipients = _get_recipients(args)
    log.info("Sending digest to %d recipient(s) from %s...", len(recipients), args.from_email)

    sent, failed = 0, 0
    for addr in recipients:
        result = send_email(
            to=addr,
            subject=subject,
            html_body=html,
            text_body=text,
            from_email=args.from_email,
            tag="car-deals",
        )
        if result.get("ErrorCode") == 0:
            log.info("Sent to %s (MessageID: %s)", addr, result.get("MessageID"))
            sent += 1
        else:
            log.error("Failed for %s: %s", addr, result)
            failed += 1

    log.info("Digest complete: %d sent, %d failed", sent, failed)


if __name__ == "__main__":
    main()
