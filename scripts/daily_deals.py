"""Send CarHero car deals digest email via Postmark.

Usage:
    python -m scripts.daily_deals                       # uses env defaults
    python -m scripts.daily_deals --to user@example.com
    python -m scripts.daily_deals --dry-run              # print HTML, don't send

Schedule via cron (3x daily at 07:00, 13:00, 19:00 UTC):
    0 7 * * *  cd /path/to/carhero && python -m scripts.daily_deals
    0 13 * * * cd /path/to/carhero && python -m scripts.daily_deals
    0 19 * * * cd /path/to/carhero && python -m scripts.daily_deals
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
    scan_deals, scan_lowest_prices,
    build_digest_html, build_digest_text,
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
    args = parser.parse_args()

    log.info("Scanning price deals...")
    deals = scan_deals(limit=args.deals)
    log.info(f"Found {len(deals)} deals with price spread")

    log.info("Scanning lowest prices...")
    cheapest = scan_lowest_prices(limit=args.cheapest)
    log.info(f"Found {len(cheapest)} cheapest listings")

    html = build_digest_html(deals, cheapest)
    text = build_digest_text(deals, cheapest)

    now = datetime.now()
    period = "Morning" if now.hour < 12 else ("Afternoon" if now.hour < 17 else "Evening")
    subject = f"CarHero {period} Deals -- {now.strftime('%b %d, %Y')}"

    if args.dry_run:
        print(html)
        log.info(f"Dry run complete. Subject: {subject}")
        return

    recipients = _get_recipients(args)
    log.info(f"Sending digest to {len(recipients)} recipient(s) from {args.from_email}...")

    sent, failed = 0, 0
    for email in recipients:
        result = send_email(
            to=email,
            subject=subject,
            html_body=html,
            text_body=text,
            from_email=args.from_email,
            tag="car-deals",
        )
        if result.get("ErrorCode") == 0:
            log.info(f"Sent to {email} (MessageID: {result.get('MessageID')})")
            sent += 1
        else:
            log.error(f"Failed for {email}: {result}")
            failed += 1

    log.info(f"Digest complete: {sent} sent, {failed} failed")


if __name__ == "__main__":
    main()
