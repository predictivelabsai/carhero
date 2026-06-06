"""mobile.de scraper — Germany's largest car marketplace.

Uses German formatting (period = thousands separator) and brand codes in URLs.
Listings are in article elements with structured specs strings.

URL pattern:
    https://suchen.mobile.de/fahrzeuge/search.html?dam=false&isSearchRequest=true
        &ms={brand_code}%3B%3B%3B&sb=p&sd=d&s=Car&vc=Car&pageNumber=1

Specs string format: "EZ 10/2022 . 134.287 km . 250 kW (340 PS) . Diesel"
Cookie consent: button "Einverstanden"
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
BRAND_CODES = get_brand_slugs("mobile_de")

BASE_URL = "https://suchen.mobile.de"
MAX_PAGES = 50


def _build_search_url(brand_code: str, page: int = 1) -> str:
    return (
        f"{BASE_URL}/fahrzeuge/search.html?"
        f"dam=false&isSearchRequest=true"
        f"&ms={brand_code}%3B%3B%3B"
        f"&sb=p&sd=d&s=Car&vc=Car"
        f"&pageNumber={page}"
    )


def _extract_listings(page) -> list[dict]:
    """Extract listing data from mobile.de search results via JS."""
    return page.evaluate("""() => {
        const articles = document.querySelectorAll('article, [class*="listing"], [data-testid="result-listing"]');
        const results = [];

        for (const el of articles) {
            // Title/heading
            const headingEl = el.querySelector('h2, h3, [class*="headline"], [data-testid="result-listing-title"]');
            if (!headingEl) continue;
            const title = headingEl.textContent.trim();
            if (!title) continue;

            // Price — German format: "35.890 €¹"
            const priceEl = el.querySelector('[class*="price"], [data-testid="price-label"]');
            const priceText = priceEl ? priceEl.textContent.trim() : '';

            // Specs string: "EZ 10/2022 · 134.287 km · 250 kW (340 PS) · Diesel"
            const specEl = el.querySelector('[class*="vehicle-data"], [class*="spec"], [class*="rms-"]');
            const specText = specEl ? specEl.textContent.trim() : '';

            // Also try to get individual spec items
            const specItems = el.querySelectorAll('[class*="vehicle-data"] span, [class*="spec"] span');
            const specList = [...specItems].map(s => s.textContent.trim()).filter(s => s.length > 0);

            // Tags: "Unfallfrei", "Nicht fahrtauglich", etc.
            const tagEls = el.querySelectorAll('[class*="tag"], [class*="badge"], [class*="label"]');
            const tags = [...tagEls].map(t => t.textContent.trim()).filter(t => t.length > 0);

            // Seller info
            const sellerEl = el.querySelector('[class*="seller"], [class*="dealer"]');
            const sellerText = sellerEl ? sellerEl.textContent.trim() : '';

            // Location
            const locationEl = el.querySelector('[class*="location"], [class*="address"]');
            const locationText = locationEl ? locationEl.textContent.trim() : '';

            // Detail URL
            const linkEl = el.querySelector('a[href*="/fahrzeuge/details"], a[href*="details.html"]');
            let detailUrl = '';
            if (linkEl) {
                detailUrl = linkEl.href;
                if (detailUrl.startsWith('/')) {
                    detailUrl = window.location.origin + detailUrl;
                }
            }

            // Images
            const imgEls = el.querySelectorAll('img[src*="mobile.de"], img[src*="img.classistatic"]');
            const imageUrls = [...imgEls].map(img => img.src).filter(s => s && !s.includes('placeholder'));

            if (title && priceText) {
                results.push({
                    title,
                    price_text: priceText,
                    spec_text: specText,
                    spec_list: specList,
                    tags,
                    seller_text: sellerText,
                    location_text: locationText,
                    source_url: detailUrl,
                    image_urls: imageUrls,
                });
            }
        }
        return results;
    }""")


def _parse_specs_string(spec_text: str) -> dict:
    """Parse the combined specs string.

    Format: "EZ 10/2022 · 134.287 km · 250 kW (340 PS) · Diesel"
    Separator can be · or • or |
    """
    result = {
        "registration_str": None,
        "mileage_str": None,
        "power_str": None,
        "fuel_type": None,
    }
    if not spec_text:
        return result

    # Split on common separators
    parts = re.split(r"[·•|]", spec_text)
    parts = [p.strip() for p in parts if p.strip()]

    for part in parts:
        part_lower = part.lower()
        if "ez" in part_lower or re.search(r"\d{1,2}/\d{4}", part):
            result["registration_str"] = part
        elif "km" in part_lower and any(c.isdigit() for c in part):
            result["mileage_str"] = part
        elif "kw" in part_lower or "ps" in part_lower:
            result["power_str"] = part
        elif part_lower in ("diesel", "benzin", "elektro", "hybrid",
                            "plug-in-hybrid", "erdgas/cng", "autogas/lpg",
                            "wasserstoff", "ethanol"):
            result["fuel_type"] = part

    return result


def _parse_listing(raw: dict, brand: str) -> dict:
    """Convert raw JS-extracted data into a normalized listing dict."""
    title = raw.get("title", "")

    # Parse model from title: "BMW 540 d Touring xDrive Luxury Line..."
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
    # Truncate long variant
    if len(variant) > 200:
        variant = variant[:200]

    # Price (German format)
    price_text = raw.get("price_text", "")
    price = parse_price(price_text, "EUR")

    # Parse specs from combined string or individual items
    spec_text = raw.get("spec_text", "")
    spec_list = raw.get("spec_list", [])
    specs = _parse_specs_string(spec_text)

    # If spec_text parsing didn't work, try individual items
    if not specs["mileage_str"] and spec_list:
        for item in spec_list:
            item_lower = item.lower()
            if "km" in item_lower and any(c.isdigit() for c in item):
                specs["mileage_str"] = item
            elif "kw" in item_lower or "ps" in item_lower:
                specs["power_str"] = item
            elif "ez" in item_lower or re.search(r"\d{1,2}/\d{4}", item):
                specs["registration_str"] = item

    mileage_km = parse_mileage(specs["mileage_str"]) if specs["mileage_str"] else None
    power_hp, power_kw = parse_power(specs["power_str"]) if specs["power_str"] else (None, None)
    reg_month, reg_year = parse_registration(specs["registration_str"]) if specs["registration_str"] else (None, None)
    fuel_type = specs.get("fuel_type")

    # Map German fuel types to English
    fuel_map = {
        "benzin": "Petrol",
        "diesel": "Diesel",
        "elektro": "Electric",
        "hybrid": "Hybrid",
        "plug-in-hybrid": "Plug-in Hybrid",
        "erdgas/cng": "CNG",
        "autogas/lpg": "LPG",
        "wasserstoff": "Hydrogen",
        "ethanol": "Ethanol",
    }
    if fuel_type:
        fuel_type = fuel_map.get(fuel_type.lower(), fuel_type)

    # Tags
    tags = raw.get("tags", [])
    accident_free = any("unfallfrei" in t.lower() for t in tags)

    # Seller
    seller_text = raw.get("seller_text", "")
    location_text = raw.get("location_text", "")
    seller_type = "private" if "privatanbieter" in (seller_text + location_text).lower() else "dealer"
    seller_name = seller_text if seller_type == "dealer" and seller_text else None

    # Location — extract city and postal code
    city = None
    if location_text:
        # Pattern: "51545 Waldbröl" or "81247 München, Privatanbieter"
        loc_match = re.match(r"\d{5}\s+(.+?)(?:,|$)", location_text)
        if loc_match:
            city = loc_match.group(1).strip()
        else:
            city = location_text.split(",")[0].strip()

    return {
        "provider": "mobile_de",
        "make": brand,
        "model": model,
        "variant": variant or None,
        "price": price,
        "price_eur": price,
        "price_original": price,
        "currency": "EUR",
        "year": reg_year,
        "registration_str": specs.get("registration_str"),
        "mileage_km": mileage_km,
        "fuel_type": fuel_type,
        "power_hp": power_hp,
        "power_kw": power_kw,
        "power_str": specs.get("power_str"),
        "country": "DE",
        "city": city,
        "seller_type": seller_type,
        "seller_name": seller_name,
        "accident_free": accident_free if accident_free else None,
        "steering_side": "LHD",
        "source_url": raw.get("source_url"),
        "image_urls": raw.get("image_urls") or [],
        "condition": "used",
    }


def scrape(headless: bool = True, limit: int = 0, brand: str | None = None):
    """Scrape mobile.de listings for premium brands.

    Args:
        headless: Run browser in headless mode.
        limit: Max listings per brand (0 = unlimited).
        brand: Specific brand to scrape, or None for all.
    """
    listings = load_checkpoint("mobile_de")
    seen_urls = {l.get("source_url") for l in listings if l.get("source_url")}

    brands = [brand] if brand else PREMIUM_BRANDS
    pw, browser, ctx, page = setup_browser(headless=headless)

    try:
        cookies_dismissed = False

        for brand_name in brands:
            brand_code = BRAND_CODES.get(brand_name)
            if not brand_code:
                log.warning("No brand code for %s, skipping", brand_name)
                continue

            log.info("Scraping mobile.de for %s...", brand_name)
            brand_count = 0

            for page_num in range(1, MAX_PAGES + 1):
                url = _build_search_url(brand_code, page_num)
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

                log.info("[mobile_de] %s page %d/%d: %d items (%d new), total: %d",
                         brand_name, page_num, MAX_PAGES, len(raw_items), new_count, len(listings))

                if limit and brand_count >= limit:
                    log.info("Reached limit of %d for %s", limit, brand_name)
                    break

                if page_num % 25 == 0:
                    save_checkpoint(listings, "mobile_de")

                time.sleep(2)

        listings = deduplicate(listings)
        save_checkpoint(listings, "mobile_de")
        log.info("mobile.de scrape complete: %d listings", len(listings))

    finally:
        browser.close()
        pw.stop()

    return listings
