"""Autohero scraper — certified used cars from Auto1 Group.

All listings are certified pre-owned, sold by Autohero (dealer).
EUR pricing, km for mileage.

URL pattern:
    https://www.autohero.com/de/search/?make=bmw&sort=price_desc&page=1
"""

from __future__ import annotations

import logging
import re
import time

from scripts.scrapers.base import (
    PREMIUM_BRANDS,
    parse_price, parse_mileage, parse_power, parse_registration,
    setup_browser, dismiss_cookies, save_checkpoint, load_checkpoint,
    deduplicate, safe_navigate,
)

log = logging.getLogger(__name__)

from utils.config import get_brand_slugs
BRAND_SLUGS = get_brand_slugs("autohero")

BASE_URL = "https://www.autohero.com"
MAX_PAGES = 50


def _build_search_url(brand_slug: str, page: int = 1) -> str:
    return f"{BASE_URL}/de/search/?make={brand_slug}&sort=price_desc&page={page}"


def _extract_listings(page) -> list[dict]:
    """Extract listing data from Autohero search results via JS."""
    return page.evaluate("""() => {
        const cards = document.querySelectorAll('article, [class*="listing"], [class*="CarCard"], [data-testid*="listing"]');
        const results = [];

        for (const el of cards) {
            // Title
            const headingEl = el.querySelector('h2, h3, [class*="title"], [class*="headline"]');
            if (!headingEl) continue;
            const title = headingEl.textContent.trim();
            if (!title) continue;

            // Price
            const priceEl = el.querySelector('[class*="price"], [class*="Price"]');
            const priceText = priceEl ? priceEl.textContent.trim() : '';

            // Specs — mileage, year, fuel, transmission, etc.
            const specEls = el.querySelectorAll('[class*="spec"] span, [class*="detail"] span, [class*="Attribute"], li');
            const specs = [...specEls].map(s => s.textContent.trim()).filter(s => s.length > 0 && s.length < 100);

            // Detail URL
            const linkEl = el.querySelector('a[href*="/de/"], a[href*="/search/"]');
            let detailUrl = '';
            if (linkEl) {
                detailUrl = linkEl.href;
                if (detailUrl.startsWith('/')) {
                    detailUrl = window.location.origin + detailUrl;
                }
            }

            // Images
            const imgEls = el.querySelectorAll('img');
            const imageUrls = [...imgEls]
                .map(img => img.src || img.dataset.src || '')
                .filter(s => s && !s.includes('placeholder') && !s.includes('logo'));

            if (title && priceText) {
                results.push({
                    title,
                    price_text: priceText,
                    specs,
                    source_url: detailUrl,
                    image_urls: imageUrls,
                });
            }
        }
        return results;
    }""")


def _parse_listing(raw: dict, brand: str) -> dict:
    """Convert raw JS-extracted data into a normalized listing dict."""
    title = raw.get("title", "")

    # Parse model from title
    model = ""
    variant = ""
    brand_lower = brand.lower().replace("-", " ")
    title_clean = title
    if title.lower().startswith(brand_lower):
        title_clean = title[len(brand):].strip()
    elif title.lower().startswith(brand_lower.split()[0]):
        title_clean = title[len(brand):].strip()

    parts = title_clean.split(" ", 1)
    model = parts[0] if parts else title_clean
    variant = parts[1] if len(parts) > 1 else ""
    if len(variant) > 200:
        variant = variant[:200]

    # Price
    price_text = raw.get("price_text", "")
    price = parse_price(price_text, "EUR")

    # Parse specs
    specs = raw.get("specs", [])
    mileage_str = ""
    registration_str = ""
    fuel_type = ""
    transmission = ""
    power_str = ""

    for spec in specs:
        spec_lower = spec.lower()
        if "km" in spec_lower and any(c.isdigit() for c in spec):
            mileage_str = spec
        elif re.search(r"\d{1,2}/\d{4}", spec):
            registration_str = spec
        elif re.search(r"^\d{4}$", spec.strip()):
            registration_str = spec
        elif "kw" in spec_lower or "ps" in spec_lower or "hp" in spec_lower:
            power_str = spec
        elif spec_lower in ("benzin", "diesel", "elektro", "hybrid",
                            "plug-in-hybrid", "petrol", "electric",
                            "gasoline"):
            fuel_type = spec
        elif spec_lower in ("automatik", "schaltgetriebe", "automatic",
                            "manual"):
            transmission = spec

    mileage_km = parse_mileage(mileage_str) if mileage_str else None
    power_hp, power_kw = parse_power(power_str) if power_str else (None, None)
    reg_month, reg_year = parse_registration(registration_str) if registration_str else (None, None)

    # Map German terms
    fuel_map = {
        "benzin": "Petrol",
        "diesel": "Diesel",
        "elektro": "Electric",
        "hybrid": "Hybrid",
        "plug-in-hybrid": "Plug-in Hybrid",
    }
    if fuel_type:
        fuel_type = fuel_map.get(fuel_type.lower(), fuel_type)

    transmission_map = {
        "automatik": "Automatic",
        "schaltgetriebe": "Manual",
    }
    if transmission:
        transmission = transmission_map.get(transmission.lower(), transmission)

    return {
        "provider": "autohero",
        "make": brand,
        "model": model,
        "variant": variant or None,
        "price": price,
        "price_eur": price,
        "price_original": price,
        "currency": "EUR",
        "year": reg_year,
        "registration_str": registration_str or None,
        "mileage_km": mileage_km,
        "fuel_type": fuel_type or None,
        "transmission": transmission or None,
        "power_hp": power_hp,
        "power_kw": power_kw,
        "power_str": power_str or None,
        "country": "DE",
        "city": None,
        "seller_type": "dealer",
        "seller_name": "Autohero",
        "accident_free": None,
        "steering_side": "LHD",
        "source_url": raw.get("source_url"),
        "image_urls": raw.get("image_urls") or [],
        "condition": "certified",
    }


def scrape(headless: bool = True, limit: int = 0, brand: str | None = None):
    """Scrape Autohero listings for premium brands.

    Args:
        headless: Run browser in headless mode.
        limit: Max listings per brand (0 = unlimited).
        brand: Specific brand to scrape, or None for all.
    """
    listings = load_checkpoint("autohero")
    seen_urls = {l.get("source_url") for l in listings if l.get("source_url")}

    brands = [brand] if brand else PREMIUM_BRANDS
    pw, browser, ctx, page = setup_browser(headless=headless)

    try:
        cookies_dismissed = False

        for brand_name in brands:
            slug = BRAND_SLUGS.get(brand_name)
            if not slug:
                log.warning("No slug for brand %s, skipping", brand_name)
                continue

            log.info("Scraping Autohero for %s...", brand_name)
            brand_count = 0

            for page_num in range(1, MAX_PAGES + 1):
                url = _build_search_url(slug, page_num)
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

                log.info("[autohero] %s page %d/%d: %d items (%d new), total: %d",
                         brand_name, page_num, MAX_PAGES, len(raw_items), new_count, len(listings))

                if limit and brand_count >= limit:
                    log.info("Reached limit of %d for %s", limit, brand_name)
                    break

                if page_num % 25 == 0:
                    save_checkpoint(listings, "autohero")

                time.sleep(2)

        listings = deduplicate(listings)
        save_checkpoint(listings, "autohero")
        log.info("Autohero scrape complete: %d listings", len(listings))

    finally:
        browser.close()
        pw.stop()

    return listings
