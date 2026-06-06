"""AutoScout24 scraper — pan-European car marketplace.

AutoScout24 covers DE, AT, NL, ES, IT, BE, FR and more. Listings are in
article elements with structured headings, price, and a specs grid.

URL pattern:
    https://www.autoscout24.com/lst/{brand}?atype=C&desc=1&sort=price&page=1

Pagination via ?page=N, up to 20 pages per search.
"""

from __future__ import annotations

import logging
import re
import time

from scripts.scrapers.base import (
    PREMIUM_BRANDS,
    parse_price, convert_to_eur, parse_mileage, parse_power, parse_registration,
    setup_browser, dismiss_cookies, save_checkpoint, load_checkpoint,
    deduplicate, safe_navigate,
)

log = logging.getLogger(__name__)

from utils.config import get_brand_slugs
BRAND_SLUGS = get_brand_slugs("autoscout24")

BASE_URL = "https://www.autoscout24.com"
MAX_PAGES = 20  # AutoScout24 limits to 20 pages per search


def _extract_listings(page) -> list[dict]:
    """Extract all article listing items from the current page via JS."""
    return page.evaluate("""() => {
        const articles = document.querySelectorAll('article');
        return [...articles].map(el => {
            // Title: make ref + variant ref in heading
            const heading = el.querySelector('h2, [data-testid="result-listing-title"]');
            const title = heading ? heading.textContent.trim() : '';

            // Price
            const priceEl = el.querySelector('[data-testid="price-label"], .price');
            const priceText = priceEl ? priceEl.textContent.trim() : '';

            // Specs grid: registration, km, fuel, power (4 items)
            const specEls = el.querySelectorAll('[data-testid="spec"] span, .spec-item, [class*="VehicleDetailTable"] span');
            const specs = [...specEls].map(s => s.textContent.trim()).filter(s => s.length > 0);

            // Fallback: try to get specs from any list within the article
            let specTexts = specs;
            if (specTexts.length === 0) {
                const allSpans = el.querySelectorAll('span');
                const filtered = [...allSpans].map(s => s.textContent.trim()).filter(s => {
                    return s.match(/\\d/) && (s.includes('km') || s.includes('kW') || s.includes('/') || s.includes('hp'));
                });
                specTexts = filtered;
            }

            // Seller info
            const sellerEl = el.querySelector('[data-testid="seller-info"], .seller-info, [class*="SellerInfo"]');
            const sellerText = sellerEl ? sellerEl.textContent.trim() : '';

            // Location
            const locationEl = el.querySelector('[data-testid="location"], .location');
            const locationText = locationEl ? locationEl.textContent.trim() : '';

            // Detail URL
            const linkEl = el.querySelector('a[href*="/offers/"], a[href*="/lst/"]');
            let detailUrl = '';
            if (linkEl) {
                detailUrl = linkEl.href;
                // Ensure absolute URL
                if (detailUrl.startsWith('/')) {
                    detailUrl = window.location.origin + detailUrl;
                }
            }

            // Images
            const imgEls = el.querySelectorAll('img[src*="autoscout24"], img[src*="as24"]');
            const imageUrls = [...imgEls].map(img => img.src).filter(s => s && !s.includes('placeholder'));

            return {
                title,
                price_text: priceText,
                specs: specTexts,
                seller_text: sellerText,
                location_text: locationText,
                source_url: detailUrl,
                image_urls: imageUrls,
            };
        }).filter(item => item.title && item.price_text);
    }""")


def _parse_listing(raw: dict, brand: str) -> dict:
    """Convert raw JS-extracted data into a normalized listing dict."""
    title = raw.get("title", "")

    # Split title into model and variant
    # Title usually starts with brand name, e.g. "BMW 320i Touring M Sport"
    model = ""
    variant = ""
    title_lower = title.lower()
    brand_lower = brand.lower()
    if title_lower.startswith(brand_lower):
        remainder = title[len(brand):].strip()
    else:
        remainder = title
    parts = remainder.split(" ", 1)
    model = parts[0] if parts else remainder
    variant = parts[1] if len(parts) > 1 else ""

    # Price
    price_text = raw.get("price_text", "")
    price = parse_price(price_text, "EUR")

    # Specs: typically [registration, mileage, fuel_type, power]
    specs = raw.get("specs", [])
    registration_str = ""
    mileage_str = ""
    fuel_type = ""
    power_str = ""

    for spec in specs:
        spec_lower = spec.lower()
        if "km" in spec_lower and any(c.isdigit() for c in spec):
            mileage_str = spec
        elif "kw" in spec_lower or "hp" in spec_lower or "ps" in spec_lower:
            power_str = spec
        elif re.search(r"\d{2}/\d{4}", spec):
            registration_str = spec
        elif spec_lower in ("gasoline", "diesel", "electric", "hybrid",
                            "petrol", "benzin", "elektro", "plug-in hybrid",
                            "lpg", "cng", "ethanol", "hydrogen",
                            "petrol/electric", "diesel/electric"):
            fuel_type = spec

    mileage_km = parse_mileage(mileage_str) if mileage_str else None
    power_hp, power_kw = parse_power(power_str) if power_str else (None, None)
    reg_month, reg_year = parse_registration(registration_str) if registration_str else (None, None)

    # Location / country
    location_text = raw.get("location_text", "")
    country = None
    city = None
    # Pattern: "DE-63868 Großwallstadt" or "ES-38207 38207"
    loc_match = re.match(r"([A-Z]{2})-\d+\s*(.*)", location_text)
    if loc_match:
        country = loc_match.group(1)
        city = loc_match.group(2).strip() or None
    elif location_text:
        city = location_text

    # Seller
    seller_text = raw.get("seller_text", "")
    seller_type = "private" if "private" in seller_text.lower() else "dealer"
    seller_name = seller_text if seller_type == "dealer" else None

    return {
        "provider": "autoscout24",
        "make": brand,
        "model": model,
        "variant": variant or None,
        "price": price,
        "price_eur": price,
        "price_original": price,
        "currency": "EUR",
        "year": reg_year,
        "registration_str": registration_str,
        "mileage_km": mileage_km,
        "fuel_type": fuel_type or None,
        "power_hp": power_hp,
        "power_kw": power_kw,
        "power_str": power_str or None,
        "country": country,
        "city": city,
        "seller_type": seller_type,
        "seller_name": seller_name,
        "steering_side": "LHD" if country != "GB" else "RHD",
        "source_url": raw.get("source_url"),
        "image_urls": raw.get("image_urls") or [],
        "condition": "used",
    }


def scrape(headless: bool = True, limit: int = 0, brand: str | None = None):
    """Scrape AutoScout24 listings for premium brands.

    Args:
        headless: Run browser in headless mode.
        limit: Max listings per brand (0 = unlimited).
        brand: Specific brand to scrape, or None for all.
    """
    listings = load_checkpoint("autoscout24")
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

            log.info("Scraping AutoScout24 for %s...", brand_name)
            brand_count = 0

            for page_num in range(1, MAX_PAGES + 1):
                url = f"{BASE_URL}/lst/{slug}?atype=C&desc=1&sort=price&page={page_num}"
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

                log.info("[autoscout24] %s page %d/%d: %d items (%d new), total: %d",
                         brand_name, page_num, MAX_PAGES, len(raw_items), new_count, len(listings))

                if limit and brand_count >= limit:
                    log.info("Reached limit of %d for %s", limit, brand_name)
                    break

                # Checkpoint every 25 pages
                if page_num % 25 == 0:
                    save_checkpoint(listings, "autoscout24")

                time.sleep(2)

        listings = deduplicate(listings)
        save_checkpoint(listings, "autoscout24")
        log.info("AutoScout24 scrape complete: %d listings", len(listings))

    finally:
        browser.close()
        pw.stop()

    return listings
