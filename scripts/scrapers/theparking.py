"""TheParking.eu scraper — European car aggregator.

Aggregates listings from multiple EU marketplaces (gocar.be, autoscout24, etc).
Uses EUR pricing and km for mileage. Multi-country coverage.

URL pattern:
    https://www.theparking.eu/used-cars/{brand}/
    Pagination via JS: ctrl.set_pageReload(n)

Cookie consent: GDPR dialog with "AGREE" button.
Listings are <li> elements with structured title, price, specs, and source site.
"""

from __future__ import annotations

import logging
import re
import time

from scripts.scrapers.base import (
    PREMIUM_BRANDS,
    parse_price, parse_mileage,
    setup_browser, dismiss_cookies, save_checkpoint, load_checkpoint,
    deduplicate, safe_navigate,
)

log = logging.getLogger(__name__)

BRAND_SLUGS = {
    "BMW": "bmw",
    "Mercedes-Benz": "mercedes-benz",
    "Audi": "audi",
    "Porsche": "porsche",
    "Jaguar": "jaguar",
    "Land Rover": "land-rover",
    "Volvo": "volvo",
    "Tesla": "tesla",
    "Lexus": "lexus",
}

BASE_URL = "https://www.theparking.eu"
MAX_PAGES = 30

COUNTRY_MAP = {
    "BELGIUM": "EU", "FRANCE": "EU", "GERMANY": "DE", "SPAIN": "EU",
    "ITALY": "EU", "NETHERLANDS": "EU", "AUSTRIA": "EU", "PORTUGAL": "EU",
    "SWITZERLAND": "EU", "POLAND": "EU", "CZECH REPUBLIC": "EU",
    "UNITED KINGDOM": "GB", "UK": "GB",
}


def _build_search_url(brand: str, page: int = 1) -> str:
    slug = BRAND_SLUGS.get(brand, brand.lower().replace(" ", "-"))
    if page == 1:
        return f"{BASE_URL}/used-cars/{slug}/"
    return f"{BASE_URL}/used-cars/{slug}/pg-{page}/"


def _extract_listings(page) -> list[dict]:
    return page.evaluate("""() => {
        const items = document.querySelectorAll('li');
        const results = [];

        for (const el of items) {
            const h2 = el.querySelector('h2');
            if (!h2) continue;

            const link = h2.querySelector('a');
            if (!link) continue;

            const titleSpans = link.querySelectorAll('span');
            if (titleSpans.length < 2) continue;

            const make = titleSpans[0] ? titleSpans[0].textContent.trim() : '';
            const model = titleSpans[1] ? titleSpans[1].textContent.trim() : '';
            const variant = titleSpans[2] ? titleSpans[2].textContent.trim() : '';

            // Price — look for € in nearby text
            const priceEl = el.querySelector('p[class]') ||
                           h2.parentElement.querySelector('p');
            let priceText = '';
            // Try to find price from the container next to the title
            const allPs = el.querySelectorAll('p');
            for (const p of allPs) {
                const t = p.textContent.trim();
                if (t.includes('€') && /\\d/.test(t)) {
                    priceText = t;
                    break;
                }
            }
            if (!priceText) {
                // Check spans/divs for price
                const allEls = el.querySelectorAll('*');
                for (const e of allEls) {
                    if (e.children.length === 0) {
                        const t = e.textContent.trim();
                        if (t.includes('€') && /\\d/.test(t) && t.length < 30) {
                            priceText = t;
                            break;
                        }
                    }
                }
            }

            // Specs from <ul> <li> elements within the listing
            const specEls = el.querySelectorAll('ul li');
            const specs = [];
            for (const s of specEls) {
                const inner = s.querySelector('span, div');
                const text = inner ? inner.textContent.trim() : s.textContent.trim();
                if (text && text.length < 80 && text.length > 1) {
                    specs.push(text);
                }
            }

            // Country
            let country = '';
            const countryEls = el.querySelectorAll('*');
            for (const ce of countryEls) {
                if (ce.children.length === 0) {
                    const t = ce.textContent.trim().toUpperCase();
                    if (['BELGIUM','FRANCE','GERMANY','SPAIN','ITALY','NETHERLANDS',
                         'AUSTRIA','PORTUGAL','SWITZERLAND','UNITED KINGDOM','UK',
                         'POLAND','CZECH REPUBLIC'].includes(t)) {
                        country = t;
                        break;
                    }
                }
            }

            // Source site (e.g. "gocar.be", "autoscout24.be")
            let sourceSite = '';
            const sourceLink = el.querySelector('p a[href*="/tools/"]');
            if (sourceLink) {
                sourceSite = sourceLink.textContent.trim();
            }

            // Detail URL
            const detailUrl = link.href || '';

            // Images
            const imgEl = el.querySelector('img[src*="theparking"]');
            const imageUrl = imgEl ? imgEl.src : '';

            if (make && priceText) {
                results.push({
                    make, model, variant,
                    price_text: priceText,
                    specs,
                    country,
                    source_site: sourceSite,
                    source_url: detailUrl,
                    image_urls: imageUrl ? [imageUrl] : [],
                });
            }
        }
        return results;
    }""")


def _parse_listing(raw: dict, brand: str) -> dict:
    make = raw.get("make", brand)
    model = raw.get("model", "")
    variant = raw.get("variant") or None

    price_text = raw.get("price_text", "")
    price_eur = parse_price(price_text, "EUR")

    specs = raw.get("specs", [])
    fuel_type = None
    mileage_km = None
    year = None
    transmission = None

    for spec in specs:
        spec_lower = spec.lower().strip()
        if "km" in spec_lower and any(c.isdigit() for c in spec):
            mileage_km = parse_mileage(spec)
        elif re.match(r"^\d{4}$", spec.strip()):
            year = int(spec.strip())
        elif spec_lower in ("gasoline", "petrol", "benzin", "essence"):
            fuel_type = "Petrol"
        elif spec_lower in ("diesel", "gasoil"):
            fuel_type = "Diesel"
        elif spec_lower in ("electric", "electrique", "elektrisch"):
            fuel_type = "Electric"
        elif "hybrid" in spec_lower:
            if "plug" in spec_lower:
                fuel_type = "Plugin Hybrid"
            else:
                fuel_type = "Hybrid"
        elif spec_lower in ("manual", "manuelle"):
            transmission = "Manual"
        elif spec_lower in ("automatic", "automatique", "automatik"):
            transmission = "Automatic"

    country_raw = raw.get("country", "").upper()
    country = COUNTRY_MAP.get(country_raw, "EU") if country_raw else "EU"

    detail_url = raw.get("source_url", "")
    if detail_url and not detail_url.startswith("http"):
        detail_url = BASE_URL + detail_url

    return {
        "provider": "theparking",
        "make": brand if make.lower() == brand.lower() else make,
        "model": model,
        "variant": variant,
        "price": price_eur,
        "price_eur": price_eur,
        "price_original": price_eur,
        "currency": "EUR",
        "year": year,
        "mileage_km": mileage_km,
        "fuel_type": fuel_type,
        "transmission": transmission,
        "body_type": None,
        "power_hp": None,
        "power_kw": None,
        "country": country,
        "city": None,
        "seller_type": "dealer",
        "seller_name": None,
        "steering_side": "RHD" if country == "GB" else "LHD",
        "source_url": detail_url,
        "image_urls": raw.get("image_urls") or [],
        "condition": "used",
    }


def scrape(headless: bool = True, limit: int = 0, brand: str | None = None):
    listings = load_checkpoint("theparking")
    seen_urls = {l.get("source_url") for l in listings if l.get("source_url")}

    brands = [brand] if brand else PREMIUM_BRANDS
    pw, browser, ctx, page = setup_browser(headless=headless)

    try:
        cookies_dismissed = False

        for brand_name in brands:
            if brand_name not in BRAND_SLUGS:
                log.warning("No slug for brand %s, skipping", brand_name)
                continue

            log.info("Scraping TheParking.eu for %s...", brand_name)
            brand_count = 0

            for page_num in range(1, MAX_PAGES + 1):
                url = _build_search_url(brand_name, page_num)
                safe_navigate(page, url)
                time.sleep(2)

                if not cookies_dismissed:
                    dismiss_cookies(page)
                    cookies_dismissed = True
                    time.sleep(1)

                try:
                    raw_items = _extract_listings(page)
                except Exception as e:
                    log.error("Failed to extract listings on page %d: %s", page_num, e)
                    raw_items = []

                if not raw_items:
                    log.info("No items on page %d for %s, stopping", page_num, brand_name)
                    break

                new_count = 0
                for raw in raw_items:
                    listing = _parse_listing(raw, brand_name)
                    src = listing.get("source_url")
                    if src and src in seen_urls:
                        continue
                    listings.append(listing)
                    if src:
                        seen_urls.add(src)
                    new_count += 1
                    brand_count += 1

                log.info("[theparking] %s page %d/%d: %d items (%d new), total: %d",
                         brand_name, page_num, MAX_PAGES, len(raw_items), new_count, len(listings))

                if limit and brand_count >= limit:
                    log.info("Reached limit of %d for %s", limit, brand_name)
                    break

                if page_num % 10 == 0:
                    save_checkpoint(listings, "theparking")

                time.sleep(2)

        listings = deduplicate(listings)
        save_checkpoint(listings, "theparking")
        log.info("TheParking scrape complete: %d listings", len(listings))

    finally:
        browser.close()
        pw.stop()

    return listings
