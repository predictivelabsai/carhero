"""Car Deals Scanner -- finds fresh daily deals from the latest scrape run.

Freshness is relative to the most recent scrape, not wall-clock time.
This ensures stats and sections always reflect real data even if the
last scrape was days ago.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from urllib.parse import quote

log = logging.getLogger(__name__)

BASE_URL = os.getenv("SERVICE_URL_CARHERO", "https://carhero.chat")

COUNTRY_LABELS = {
    "GB": "UK", "DE": "Germany", "EU": "Other EU",
    "EE": "Estonia", "LT": "Lithuania", "LV": "Latvia", "SE": "Sweden",
    "PL": "Poland", "ES": "Spain", "NL": "Netherlands", "FI": "Finland",
    "DK": "Denmark", "IE": "Ireland", "NO": "Norway", "PT": "Portugal",
    "RO": "Romania",
}
PROVIDER_LABELS = {
    "autotrader": "AutoTrader",
    "mobile_de": "mobile.de",
    "autoscout24": "AutoScout24",
    "autohero": "Autohero",
    "theparking": "TheParking",
    "auto24_ee": "Auto24.ee",
    "auto24_lt": "Auto24.lt",
    "auto24_lv": "Auto24.lv",
    "blocket": "Blocket.se",
    "otomoto": "Otomoto.pl",
    "coches": "Coches.net",
    "marktplaats": "Marktplaats.nl",
    "nettiauto": "Nettiauto.com",
    "bilbasen": "Bilbasen.dk",
    "donedeal": "DoneDeal.ie",
    "finn": "Finn.no",
    "standvirtual": "Standvirtual.com",
    "autovit": "Autovit.ro",
}


def _scrape_cutoff(db) -> str:
    """Compute the cutoff timestamp for 'latest scrape run'.

    Returns a SQL expression string. The cutoff is MAX(scraped_at) minus
    a 4-hour buffer to cover the span of a single scrape run across all
    providers.  This means stats always reflect the most recent run,
    even if it happened days ago.
    """
    from sqlalchemy import text
    row = db.execute(text(
        "SELECT MAX(scraped_at) FROM carhero.car_listings WHERE status = 'active'"
    )).scalar()
    if not row:
        return "NOW() - INTERVAL '1 day'"
    return f"TIMESTAMP '{row}' - INTERVAL '4 hours'"


def scan_new_listings(limit: int = 10) -> list[dict]:
    """Listings first seen in the latest scrape run."""
    from db import SessionLocal
    from sqlalchemy import text

    db = SessionLocal()
    try:
        cutoff = _scrape_cutoff(db)
        sql = text(f"""
            SELECT make, model, variant, year, mileage_km, price_eur,
                   country, provider, fuel_type, transmission, source_url
            FROM carhero.car_listings
            WHERE status = 'active' AND price_eur > 0
              AND created_at > ({cutoff})
            ORDER BY md5(make || model || CURRENT_DATE::text), price_eur ASC
            LIMIT :lim
        """)
        return [dict(r._mapping) for r in db.execute(sql, {"lim": limit})]
    finally:
        db.close()


def scan_price_drops(limit: int = 10) -> list[dict]:
    """Listings whose price dropped in the latest scrape vs their previous price."""
    from db import SessionLocal
    from sqlalchemy import text

    db = SessionLocal()
    try:
        cutoff = _scrape_cutoff(db)
        sql = text(f"""
            SELECT l.make, l.model, l.variant, l.year, l.mileage_km,
                   l.price_eur, l.country, l.provider, l.fuel_type,
                   l.transmission, l.source_url,
                   ph.price_eur AS old_price,
                   (ph.price_eur - l.price_eur) AS drop_eur,
                   ROUND(((ph.price_eur - l.price_eur) / ph.price_eur * 100)::numeric, 1) AS drop_pct
            FROM carhero.car_listings l
            JOIN carhero.price_history ph ON ph.listing_id = l.id
            WHERE l.status = 'active' AND l.price_eur > 0
              AND ph.recorded_at > ({cutoff})
              AND ph.price_eur > l.price_eur
            ORDER BY (ph.price_eur - l.price_eur)::float / ph.price_eur DESC
            LIMIT :lim
        """)
        return [dict(r._mapping) for r in db.execute(sql, {"lim": limit})]
    finally:
        db.close()


def scan_deals(limit: int = 15) -> list[dict]:
    """Price arbitrage: same make/model with biggest spread across sources.

    Uses listings from the latest scrape run.
    """
    from db import SessionLocal
    from sqlalchemy import text

    db = SessionLocal()
    try:
        cutoff = _scrape_cutoff(db)

        sql = text(f"""
            WITH by_source AS (
                SELECT make, model, country, provider,
                       COUNT(*) AS cnt,
                       ROUND(AVG(price_eur)::numeric, 0) AS avg_price,
                       ROUND(MIN(price_eur)::numeric, 0) AS min_price,
                       ROUND(MAX(price_eur)::numeric, 0) AS max_price
                FROM carhero.car_listings
                WHERE status = 'active' AND price_eur > 0
                  AND scraped_at > ({cutoff})
                GROUP BY make, model, country, provider
                HAVING COUNT(*) >= 1
            ),
            spreads AS (
                SELECT make, model,
                       SUM(cnt) AS listing_count,
                       MIN(min_price) AS min_price,
                       MAX(max_price) AS max_price,
                       ROUND(AVG(avg_price)::numeric, 0) AS avg_price,
                       (MAX(max_price) - MIN(min_price)) AS savings_eur,
                       ROUND(((MAX(max_price) - MIN(min_price))
                              / NULLIF(AVG(avg_price), 0) * 100)::numeric, 1) AS savings_pct
                FROM by_source
                GROUP BY make, model
                HAVING COUNT(DISTINCT country || '/' || provider) >= 2
            )
            SELECT * FROM spreads
            WHERE savings_eur > 0
            ORDER BY savings_pct DESC
            LIMIT :lim
        """)
        rows = [dict(r._mapping) for r in db.execute(sql, {"lim": limit})]

        for row in rows:
            cheapest = db.execute(text("""
                SELECT id, country, provider
                FROM carhero.car_listings
                WHERE make = :make AND model = :model
                  AND status = 'active' AND price_eur > 0
                ORDER BY price_eur ASC LIMIT 1
            """), {"make": row["make"], "model": row["model"]})
            c = cheapest.first()
            if c:
                row["cheapest_country"] = c.country
                row["cheapest_provider"] = c.provider
                row["cheapest_listing_id"] = c.id

            priciest = db.execute(text("""
                SELECT id, country, provider
                FROM carhero.car_listings
                WHERE make = :make AND model = :model
                  AND status = 'active' AND price_eur > 0
                ORDER BY price_eur DESC LIMIT 1
            """), {"make": row["make"], "model": row["model"]})
            p = priciest.first()
            if p:
                row["priciest_country"] = p.country
                row["priciest_provider"] = p.provider
                row["priciest_listing_id"] = p.id

            deal_row = db.execute(text("""
                INSERT INTO carhero.deals
                    (make, model, cheapest_listing_id, priciest_listing_id,
                     cheapest_price_eur, priciest_price_eur, savings_eur, savings_pct,
                     cheapest_country, cheapest_provider, priciest_country, priciest_provider,
                     listing_count, status, updated_at)
                VALUES
                    (:make, :model, :cl, :pl,
                     :min_price, :max_price, :savings_eur, :savings_pct,
                     :cc, :cp, :pc, :pp,
                     :cnt, 'active', NOW())
                ON CONFLICT (make, model) DO UPDATE SET
                    cheapest_listing_id  = EXCLUDED.cheapest_listing_id,
                    priciest_listing_id  = EXCLUDED.priciest_listing_id,
                    cheapest_price_eur   = EXCLUDED.cheapest_price_eur,
                    priciest_price_eur   = EXCLUDED.priciest_price_eur,
                    savings_eur          = EXCLUDED.savings_eur,
                    savings_pct          = EXCLUDED.savings_pct,
                    cheapest_country     = EXCLUDED.cheapest_country,
                    cheapest_provider    = EXCLUDED.cheapest_provider,
                    priciest_country     = EXCLUDED.priciest_country,
                    priciest_provider    = EXCLUDED.priciest_provider,
                    listing_count        = EXCLUDED.listing_count,
                    status               = 'active',
                    updated_at           = NOW()
                RETURNING id
            """), {
                "make": row["make"], "model": row["model"],
                "cl": row.get("cheapest_listing_id"),
                "pl": row.get("priciest_listing_id"),
                "min_price": row["min_price"], "max_price": row["max_price"],
                "savings_eur": row["savings_eur"], "savings_pct": row["savings_pct"],
                "cc": row.get("cheapest_country"), "cp": row.get("cheapest_provider"),
                "pc": row.get("priciest_country"), "pp": row.get("priciest_provider"),
                "cnt": row.get("listing_count", 0),
            })
            deal = deal_row.first()
            row["deal_id"] = str(deal.id) if deal else None

        db.commit()
        return rows
    finally:
        db.close()


def scan_lowest_prices(limit: int = 10) -> list[dict]:
    """Cheapest active listings from the latest scrape run."""
    from db import SessionLocal
    from sqlalchemy import text

    db = SessionLocal()
    try:
        cutoff = _scrape_cutoff(db)
        sql = text(f"""
            SELECT make, model, variant, year, mileage_km, price_eur,
                   country, provider, fuel_type, transmission, source_url
            FROM carhero.car_listings
            WHERE status = 'active' AND price_eur > 0
              AND scraped_at > ({cutoff})
            ORDER BY price_eur ASC
            LIMIT :lim
        """)
        return [dict(r._mapping) for r in db.execute(sql, {"lim": limit})]
    finally:
        db.close()


def scan_freshness_stats() -> dict:
    """Summary stats for the digest header, based on latest scrape run."""
    from db import SessionLocal
    from sqlalchemy import text

    db = SessionLocal()
    try:
        cutoff = _scrape_cutoff(db)
        row = db.execute(text(f"""
            SELECT
                COUNT(*) AS total_active,
                COUNT(*) FILTER (
                    WHERE scraped_at > ({cutoff})
                ) AS fresh_count,
                COUNT(*) FILTER (
                    WHERE created_at > ({cutoff})
                ) AS new_count,
                COUNT(DISTINCT provider) FILTER (
                    WHERE scraped_at > ({cutoff})
                ) AS providers_scraped,
                COUNT(DISTINCT country) FILTER (
                    WHERE scraped_at > ({cutoff})
                ) AS countries_covered,
                MAX(scraped_at) AS last_scrape
            FROM carhero.car_listings
            WHERE status = 'active'
        """)).first()
        return dict(row._mapping) if row else {}
    finally:
        db.close()


# ── Formatting helpers ────────────────────────────────────────────────


def _fmt_eur(n) -> str:
    if not n:
        return "--"
    try:
        return f"€{float(n):,.0f}"
    except (TypeError, ValueError):
        return str(n)


def _source_label(country: str | None, provider: str | None) -> str:
    c = COUNTRY_LABELS.get(country or "", country or "")
    p = PROVIDER_LABELS.get(provider or "", provider or "")
    return f"{c} / {p}"


# ── HTML builder ──────────────────────────────────────────────────────


def build_digest_html(
    deals: list[dict],
    cheapest: list[dict],
    new_listings: list[dict] | None = None,
    price_drops: list[dict] | None = None,
    stats: dict | None = None,
) -> str:
    now = datetime.now()
    today = now.strftime("%A, %B %d, %Y")

    stats = stats or {}
    fresh = stats.get("fresh_count", 0)
    new = stats.get("new_count", 0)
    providers = stats.get("providers_scraped", 0)
    countries = stats.get("countries_covered", 0)

    link_style = "color:inherit; text-decoration:none;"

    # --- Stats banner ---
    stats_html = ""
    if fresh > 0:
        stats_html = f"""
    <div style="background:#F0FDF4; border:1px solid #BBF7D0; border-radius:8px; padding:12px 16px; margin-bottom:20px; text-align:center;">
        <span style="font-size:13px; color:#15803D;">
            <strong>{fresh:,}</strong> listings refreshed &middot;
            <strong>{new:,}</strong> new today &middot;
            <strong>{providers}</strong> providers &middot;
            <strong>{countries}</strong> countries
        </span>
    </div>"""

    # --- New listings section ---
    new_html = ""
    if new_listings:
        rows_html = ""
        for c in new_listings:
            km = f"{int(c['mileage_km']):,} km" if c.get("mileage_km") else "--"
            src = _source_label(c.get("country"), c.get("provider"))
            deal_url = f"{BASE_URL}/app?deal={quote(c['make'] + ' ' + c['model'])}"
            rows_html += f"""
            <tr>
                <td style="padding:6px 12px; border-bottom:1px solid #E5E7EB;">
                    <a href="{deal_url}" style="{link_style}">
                        <strong>{c['make']} {c['model']}</strong>
                        <span style="color:#6B7280; font-size:12px;">
                            {c.get('variant') or ''} &middot; {c.get('year') or ''} &middot; {km}
                        </span>
                    </a>
                </td>
                <td style="padding:6px 12px; border-bottom:1px solid #E5E7EB; text-align:right;">
                    <a href="{deal_url}" style="{link_style} font-family:'Courier New',monospace; font-size:13px; font-weight:600; color:#1A1A1A;">
                        {_fmt_eur(c.get('price_eur'))}
                    </a>
                </td>
                <td style="padding:6px 12px; border-bottom:1px solid #E5E7EB; text-align:right;">
                    <a href="{deal_url}" style="{link_style} font-size:11px; color:#6B7280;">{src}</a>
                </td>
            </tr>"""

        new_html = f"""
    <div style="background:#FFFFFF; border:1px solid #E5E7EB; border-radius:8px; padding:16px; margin-bottom:20px;">
        <h2 style="color:#1A1A1A; font-size:16px; font-weight:600; margin:0 0 12px; border-bottom:2px solid #16A34A; padding-bottom:6px;">
            &#x1F195; New Listings Today
        </h2>
        <p style="color:#6B7280; font-size:12px; margin:0 0 12px;">
            Just appeared across European markets.
        </p>
        <table width="100%" cellpadding="0" cellspacing="0" style="font-size:13px; color:#1A1A1A;">
            <tbody>{rows_html}</tbody>
        </table>
    </div>"""

    # --- Price drops section ---
    drops_html = ""
    if price_drops:
        rows_html = ""
        for d in price_drops:
            km = f"{int(d['mileage_km']):,} km" if d.get("mileage_km") else "--"
            src = _source_label(d.get("country"), d.get("provider"))
            deal_url = f"{BASE_URL}/app?deal={quote(d['make'] + ' ' + d['model'])}"
            drop_pct = float(d.get("drop_pct") or 0)
            rows_html += f"""
            <tr>
                <td style="padding:6px 12px; border-bottom:1px solid #E5E7EB;">
                    <a href="{deal_url}" style="{link_style}">
                        <strong>{d['make']} {d['model']}</strong>
                        <span style="color:#6B7280; font-size:12px;">
                            {d.get('variant') or ''} &middot; {d.get('year') or ''} &middot; {km}
                        </span>
                    </a>
                </td>
                <td style="padding:6px 12px; border-bottom:1px solid #E5E7EB; text-align:right;">
                    <span style="text-decoration:line-through; color:#9CA3AF; font-size:11px;">{_fmt_eur(d.get('old_price'))}</span><br>
                    <a href="{deal_url}" style="{link_style} font-family:'Courier New',monospace; font-size:13px; font-weight:600; color:#16A34A;">
                        {_fmt_eur(d.get('price_eur'))}
                    </a>
                </td>
                <td style="padding:6px 12px; border-bottom:1px solid #E5E7EB; text-align:center;">
                    <span style="background:#16A34A; color:white; padding:2px 8px; border-radius:12px; font-size:12px; font-weight:600;">
                        &darr;{drop_pct:.0f}%
                    </span><br>
                    <span style="font-size:11px; color:#6B7280;">{src}</span>
                </td>
            </tr>"""

        drops_html = f"""
    <div style="background:#FFFFFF; border:1px solid #E5E7EB; border-radius:8px; padding:16px; margin-bottom:20px;">
        <h2 style="color:#1A1A1A; font-size:16px; font-weight:600; margin:0 0 12px; border-bottom:2px solid #F59E0B; padding-bottom:6px;">
            &#x1F4C9; Price Drops
        </h2>
        <p style="color:#6B7280; font-size:12px; margin:0 0 12px;">
            Prices reduced since last scrape &mdash; sellers are getting motivated.
        </p>
        <table width="100%" cellpadding="0" cellspacing="0" style="font-size:13px; color:#1A1A1A;">
            <tbody>{rows_html}</tbody>
        </table>
    </div>"""

    # --- Top deals section ---
    deal_rows = ""
    for d in deals:
        savings_pct = float(d.get("savings_pct") or 0)
        badge_color = "#16A34A" if savings_pct >= 15 else "#F59E0B" if savings_pct >= 8 else "#6B7280"
        cheapest_src = _source_label(d.get("cheapest_country"), d.get("cheapest_provider"))
        priciest_src = _source_label(d.get("priciest_country"), d.get("priciest_provider"))
        deal_id = d.get("deal_id") or ""
        deal_url = f"{BASE_URL}/app?deal_id={deal_id}" if deal_id else f"{BASE_URL}/app?deal={quote(d['make'] + ' ' + d['model'])}"

        deal_rows += f"""
        <tr>
            <td style="padding:10px 12px; border-bottom:1px solid #E5E7EB;">
                <a href="{deal_url}" style="{link_style}">
                    <strong style="color:#1A1A1A; font-size:14px;">{d['make']} {d['model']}</strong><br>
                    <span style="font-size:11px; color:#6B7280;">{int(d.get('listing_count') or 0)} listings</span>
                </a>
            </td>
            <td style="padding:10px 12px; border-bottom:1px solid #E5E7EB; text-align:right;">
                <a href="{deal_url}" style="{link_style} font-family:'Courier New',monospace; font-size:13px;">
                    {_fmt_eur(d.get('min_price'))}<br>
                    <span style="font-size:10px; color:#6B7280;">{cheapest_src}</span>
                </a>
            </td>
            <td style="padding:10px 12px; border-bottom:1px solid #E5E7EB; text-align:right;">
                <a href="{deal_url}" style="{link_style} font-family:'Courier New',monospace; font-size:13px;">
                    {_fmt_eur(d.get('max_price'))}<br>
                    <span style="font-size:10px; color:#6B7280;">{priciest_src}</span>
                </a>
            </td>
            <td style="padding:10px 12px; border-bottom:1px solid #E5E7EB; text-align:center;">
                <a href="{deal_url}" style="{link_style}">
                    <span style="background:{badge_color}; color:white; padding:2px 8px; border-radius:12px; font-size:12px; font-weight:600;">
                        {savings_pct:.0f}%
                    </span><br>
                    <span style="font-size:11px; color:#16A34A; font-weight:600;">Save {_fmt_eur(d.get('savings_eur'))}</span><br>
                    <span style="font-size:10px; color:#000; font-weight:500;">Ask CarHero &rarr;</span>
                </a>
            </td>
        </tr>"""

    # --- Cheapest listings section ---
    cheapest_rows = ""
    for c in cheapest:
        km = f"{int(c['mileage_km']):,} km" if c.get("mileage_km") else "--"
        src = _source_label(c.get("country"), c.get("provider"))
        deal_url = f"{BASE_URL}/app?deal={quote(c['make'] + ' ' + c['model'])}"
        cheapest_rows += f"""
        <tr>
            <td style="padding:6px 12px; border-bottom:1px solid #E5E7EB;">
                <a href="{deal_url}" style="{link_style}">
                    <strong>{c['make']} {c['model']}</strong>
                    <span style="color:#6B7280; font-size:12px;">
                        {c.get('variant') or ''} &middot; {c.get('year') or ''} &middot; {km}
                    </span>
                </a>
            </td>
            <td style="padding:6px 12px; border-bottom:1px solid #E5E7EB; text-align:right;">
                <a href="{deal_url}" style="{link_style} font-family:'Courier New',monospace; font-size:13px; font-weight:600; color:#1A1A1A;">
                    {_fmt_eur(c.get('price_eur'))}
                </a>
            </td>
            <td style="padding:6px 12px; border-bottom:1px solid #E5E7EB; text-align:right;">
                <a href="{deal_url}" style="{link_style} font-size:11px; color:#6B7280;">
                    {src}
                </a>
            </td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="margin:0; padding:0; background:#F5F5F5; font-family:'Inter','Helvetica Neue',Arial,sans-serif;">
<div style="max-width:680px; margin:0 auto; padding:24px 16px;">

    <!-- Header -->
    <div style="text-align:center; padding:20px 0 24px;">
        <h1 style="color:#1A1A1A; font-size:22px; font-weight:700; margin:0; letter-spacing:-0.02em;">
            Car<span style="color:#6B7280;">Hero</span>
        </h1>
        <p style="color:#6B7280; font-size:14px; margin:6px 0 0;">Daily Deals &middot; {today}</p>
        <p style="color:#9CA3AF; font-size:12px; margin:4px 0 0;">Fresh picks from overnight European market scan</p>
    </div>

    {stats_html}
    {new_html}
    {drops_html}

    <!-- Top Deals -->
    <div style="background:#FFFFFF; border:1px solid #E5E7EB; border-radius:8px; padding:16px; margin-bottom:20px;">
        <h2 style="color:#1A1A1A; font-size:16px; font-weight:600; margin:0 0 12px; border-bottom:2px solid #000000; padding-bottom:6px;">
            &#x1F4B0; Best Price Arbitrage
        </h2>
        <p style="color:#6B7280; font-size:12px; margin:0 0 12px;">
            Same make &amp; model, different prices across countries and providers.
        </p>
        <table width="100%" cellpadding="0" cellspacing="0" style="font-size:13px; color:#1A1A1A;">
            <thead>
                <tr style="color:#6B7280; font-size:11px; text-transform:uppercase; letter-spacing:0.05em;">
                    <th style="padding:6px 12px; text-align:left;">Car</th>
                    <th style="padding:6px 12px; text-align:right;">Cheapest</th>
                    <th style="padding:6px 12px; text-align:right;">Priciest</th>
                    <th style="padding:6px 12px; text-align:center;">Savings</th>
                </tr>
            </thead>
            <tbody>
                {deal_rows if deal_rows else '<tr><td colspan="4" style="padding:16px; text-align:center; color:#6B7280;">No price differences found yet.</td></tr>'}
            </tbody>
        </table>
    </div>

    <!-- Cheapest Listings -->
    <div style="background:#FFFFFF; border:1px solid #E5E7EB; border-radius:8px; padding:16px; margin-bottom:20px;">
        <h2 style="color:#1A1A1A; font-size:16px; font-weight:600; margin:0 0 12px; border-bottom:2px solid #000000; padding-bottom:6px;">
            &#x1F3F7; Lowest Prices Right Now
        </h2>
        <table width="100%" cellpadding="0" cellspacing="0" style="font-size:13px; color:#1A1A1A;">
            <tbody>
                {cheapest_rows if cheapest_rows else '<tr><td style="padding:16px; text-align:center; color:#6B7280;">No listings yet.</td></tr>'}
            </tbody>
        </table>
    </div>

    <!-- Footer -->
    <div style="text-align:center; padding:20px 0; border-top:1px solid #E5E7EB; margin-top:12px;">
        <p style="color:#6B7280; font-size:12px; margin:0 0 4px;">
            <a href="{BASE_URL}/app" style="color:#000000; text-decoration:none; font-weight:600;">Open CarHero</a>
            &nbsp;&middot;&nbsp;
            <a href="{BASE_URL}/app/market-map" style="color:#000000; text-decoration:none;">Market Map</a>
        </p>
        <p style="color:#9CA3AF; font-size:11px; margin:0;">
            Predictive Labs Ltd &middot; You're receiving this because you signed up for CarHero alerts.
        </p>
    </div>

</div>
</body>
</html>"""


def build_digest_text(
    deals: list[dict],
    cheapest: list[dict],
    new_listings: list[dict] | None = None,
    price_drops: list[dict] | None = None,
    stats: dict | None = None,
) -> str:
    now = datetime.now()
    today = now.strftime("%A, %B %d, %Y")

    stats = stats or {}
    fresh = stats.get("fresh_count", 0)
    new_count = stats.get("new_count", 0)

    lines = [f"CarHero Daily Deals -- {today}", "=" * 44, ""]

    if fresh > 0:
        lines.append(f"  {fresh:,} listings refreshed | {new_count:,} new today")
        lines.append("")

    if new_listings:
        lines.append("NEW LISTINGS TODAY")
        lines.append("-" * 44)
        for c in new_listings:
            km = f"{int(c['mileage_km']):,} km" if c.get("mileage_km") else ""
            src = _source_label(c.get("country"), c.get("provider"))
            lines.append(f"  {c['make']} {c['model']} {c.get('year') or ''} {km} -- {_fmt_eur(c.get('price_eur'))} ({src})")
        lines.append("")

    if price_drops:
        lines.append("PRICE DROPS")
        lines.append("-" * 44)
        for d in price_drops:
            drop_pct = float(d.get("drop_pct") or 0)
            lines.append(f"  {d['make']} {d['model']} {d.get('year') or ''}")
            lines.append(f"    Was {_fmt_eur(d.get('old_price'))} -> Now {_fmt_eur(d.get('price_eur'))} (down {drop_pct:.0f}%)")
        lines.append("")

    lines.append("BEST PRICE ARBITRAGE")
    lines.append("-" * 44)
    for d in deals:
        cheapest_src = _source_label(d.get("cheapest_country"), d.get("cheapest_provider"))
        priciest_src = _source_label(d.get("priciest_country"), d.get("priciest_provider"))
        lines.append(f"  {d['make']} {d['model']}  ({int(d.get('listing_count') or 0)} listings)")
        lines.append(f"    Cheapest: {_fmt_eur(d.get('min_price'))} ({cheapest_src})")
        lines.append(f"    Priciest: {_fmt_eur(d.get('max_price'))} ({priciest_src})")
        lines.append(f"    Save {_fmt_eur(d.get('savings_eur'))} ({float(d.get('savings_pct') or 0):.0f}%)")
        lines.append("")

    lines.append("LOWEST PRICES RIGHT NOW")
    lines.append("-" * 44)
    for c in cheapest:
        km = f"{int(c['mileage_km']):,} km" if c.get("mileage_km") else ""
        lines.append(f"  {c['make']} {c['model']} {c.get('year') or ''} {km} -- {_fmt_eur(c.get('price_eur'))}")
    lines.append("")

    lines.append("---")
    lines.append(f"{BASE_URL}/app")
    return "\n".join(lines)
