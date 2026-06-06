"""Car Deals Scanner -- finds price arbitrage opportunities across providers/countries.

A "deal" = same make + model listed at significantly different prices across
different providers or countries. Buyers can save by purchasing from the
cheaper source.
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
}


def scan_deals(limit: int = 15) -> list[dict]:
    """Find make/model combos with the biggest price spread across providers or countries.

    Each deal is upserted into the deals table and gets a stable UUID.
    Returns rows with: deal_id, make, model, min_price, max_price, avg_price,
    savings_eur, savings_pct, cheapest_source, priciest_source, listing_count.
    """
    from db import SessionLocal
    from sqlalchemy import text

    db = SessionLocal()
    try:
        sql = text("""
            WITH by_source AS (
                SELECT make, model, country, provider,
                       COUNT(*) AS cnt,
                       ROUND(AVG(price_eur)::numeric, 0) AS avg_price,
                       ROUND(MIN(price_eur)::numeric, 0) AS min_price,
                       ROUND(MAX(price_eur)::numeric, 0) AS max_price
                FROM carhero.car_listings
                WHERE status = 'active' AND price_eur > 0
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
    """Pull the cheapest active listings overall."""
    from db import SessionLocal
    from sqlalchemy import text

    db = SessionLocal()
    try:
        sql = text("""
            SELECT make, model, variant, year, mileage_km, price_eur,
                   country, provider, fuel_type, transmission
            FROM carhero.car_listings
            WHERE status = 'active' AND price_eur > 0
            ORDER BY price_eur ASC
            LIMIT :lim
        """)
        return [dict(r._mapping) for r in db.execute(sql, {"lim": limit})]
    finally:
        db.close()


def _fmt_eur(n) -> str:
    if not n:
        return "--"
    try:
        return f"EUR {float(n):,.0f}"
    except (TypeError, ValueError):
        return str(n)


def _source_label(country: str | None, provider: str | None) -> str:
    c = COUNTRY_LABELS.get(country or "", country or "")
    p = PROVIDER_LABELS.get(provider or "", provider or "")
    return f"{c} / {p}"


def build_digest_html(deals: list[dict], cheapest: list[dict]) -> str:
    now = datetime.now()
    today = now.strftime("%A, %B %d, %Y")
    period = "Morning" if now.hour < 12 else ("Afternoon" if now.hour < 17 else "Evening")

    deal_rows = ""
    link_style = "color:inherit; text-decoration:none;"
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
                        {c.get('variant') or ''} · {c.get('year') or ''} · {km}
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
            Car<span style="color:#000000;">Hero</span>
        </h1>
        <p style="color:#6B7280; font-size:14px; margin:6px 0 0;">{period} Deals &middot; {today}</p>
        <p style="color:#9CA3AF; font-size:12px; margin:4px 0 0;">Price arbitrage across European car markets</p>
    </div>

    <!-- Top Deals -->
    <div style="background:#FFFFFF; border:1px solid #E5E7EB; border-radius:8px; padding:16px; margin-bottom:20px;">
        <h2 style="color:#1A1A1A; font-size:16px; font-weight:600; margin:0 0 12px; border-bottom:2px solid #000000; padding-bottom:6px;">
            Top Price Deals
        </h2>
        <p style="color:#6B7280; font-size:12px; margin:0 0 12px;">
            Same make &amp; model, different prices across countries and providers.
            Buy from the cheapest source and save.
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
            Lowest Prices Right Now
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


def build_digest_text(deals: list[dict], cheapest: list[dict]) -> str:
    now = datetime.now()
    today = now.strftime("%A, %B %d, %Y")
    period = "Morning" if now.hour < 12 else ("Afternoon" if now.hour < 17 else "Evening")

    lines = [f"CarHero {period} Deals -- {today}", "=" * 44, ""]

    lines.append("TOP PRICE DEALS")
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
