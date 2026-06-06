"""AutoTrader UK scraper — UK's largest car marketplace.

Requires a postcode to show results. Uses GBP pricing and miles for mileage,
both converted to EUR/km in parsing.

URL pattern:
    https://www.autotrader.co.uk/car-search?make=BMW&postcode=SW1A%201AA
        &price-from=5000&sort=price-desc&page=1

Cookie consent: SP Consent iframe with "Accept All" button.
Listings are in list > listitem elements with structured content.
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
BRAND_PARAMS = get_brand_slugs("autotrader")

POSTCODE = "SW1A 1AA"  # Central London
BASE_URL = "https://www.autotrader.co.uk"
MAX_PAGES = 50


def _build_search_url(brand: str, page: int = 1) -> str:
    make_param = BRAND_PARAMS.get(brand, brand)
    postcode_encoded = POSTCODE.replace(" ", "%20")
    return (
        f"{BASE_URL}/car-search?"
        f"make={make_param.replace(' ', '%20')}"
        f"&postcode={postcode_encoded}"
        f"&price-from=5000"
        f"&sort=price-desc"
        f"&page={page}"
    )


def _extract_listings(page) -> list[dict]:
    """Extract listing data from AutoTrader search results via JS."""
    return page.evaluate("""() => {
        // AutoTrader uses list items for results
        const items = document.querySelectorAll('li[class*="search-page__result"], section[data-testid="trader-seller-listing"], article');
        const results = [];

        for (const el of items) {
            // Title/heading — usually contains make, model, variant
            const headingEl = el.querySelector('h3 a, h2 a, a[href*="/car-details/"]');
            if (!headingEl) continue;

            const title = headingEl.textContent.trim();
            const detailUrl = headingEl.href || '';

            // Skip sponsored/ad listings
            const sponsoredEl = el.querySelector('[class*="sponsored"], [class*="advert"]');
            if (sponsoredEl) continue;

            // Price
            const priceEl = el.querySelector('[class*="price"], [data-testid="search-listing-price"]');
            const priceText = priceEl ? priceEl.textContent.trim() : '';

            // Specs — mileage, year, etc.
            const specEls = el.querySelectorAll('li[class*="spec"], span[class*="spec"], [class*="key-specs"] li, ul li');
            const specs = [...specEls].map(s => s.textContent.trim()).filter(s => s.length > 0 && s.length < 100);

            // Seller/location
            const sellerEl = el.querySelector('[class*="dealer"], [class*="seller"], [data-testid="search-listing-seller"]');
            const sellerText = sellerEl ? sellerEl.textContent.trim() : '';

            // Images
            const imgEls = el.querySelectorAll('img[src*="autotrader"], img[src*="i.ebayimg"]');
            const imageUrls = [...imgEls].map(img => img.src).filter(s => s && !s.includes('placeholder'));

            if (title && priceText) {
                results.push({
                    title,
                    price_text: priceText,
                    specs,
                    seller_text: sellerText,
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

    # Parse model and variant from title
    # Title format: "BMW 4 Series Gran Coupe 3.0 M440i MHT Auto xDrive Euro 6 (s/s) 5dr"
    model = ""
    variant = ""
    title_lower = title.lower()
    brand_lower = brand.lower().replace("-", " ")
    if title_lower.startswith(brand_lower):
        remainder = title[len(brand):].strip()
    elif title_lower.startswith(brand_lower.split()[0]):
        # Handle "Land Rover" -> "Land" prefix matching
        remainder = title[len(brand):].strip()
    else:
        remainder = title

    # First word(s) are typically the model (e.g. "4 Series", "C Class", "A3")
    parts = remainder.split(",")[0].strip()  # Remove price from title if present
    model_parts = parts.split(" ")
    if model_parts:
        # Try to grab model name (could be "4 Series", "X5", "A3", etc.)
        model = model_parts[0]
        # Check if next word is part of model name (e.g. "4 Series", "C Class")
        if len(model_parts) > 1 and model_parts[1].lower() in ("series", "class"):
            model = f"{model_parts[0]} {model_parts[1]}"
            variant = " ".join(model_parts[2:]) or None
        else:
            variant = " ".join(model_parts[1:]) or None

    # Price (GBP)
    price_text = raw.get("price_text", "")
    price_gbp = parse_price(price_text, "GBP")
    price_eur = convert_to_eur(price_gbp, "GBP")

    # Parse specs
    specs = raw.get("specs", [])
    mileage_str = ""
    year_str = ""
    fuel_type = ""
    transmission = ""
    body_type = ""

    for spec in specs:
        spec_lower = spec.lower()
        if "mile" in spec_lower and any(c.isdigit() for c in spec):
            mileage_str = spec
        elif re.search(r"\d{4}\s*\(\d+\s*reg\)", spec):
            year_str = spec
        elif re.search(r"^\d{4}$", spec.strip()):
            year_str = spec
        elif spec_lower in ("petrol", "diesel", "electric", "hybrid",
                            "plug-in hybrid", "petrol/electric",
                            "diesel/electric"):
            fuel_type = spec
        elif spec_lower in ("manual", "automatic", "semi-automatic"):
            transmission = spec
        elif spec_lower in ("hatchback", "saloon", "estate", "suv", "coupe",
                            "convertible", "mpv", "pickup"):
            body_type = spec

    mileage_km = parse_mileage(mileage_str) if mileage_str else None
    _, reg_year = parse_registration(year_str) if year_str else (None, None)

    # Seller / location
    seller_text = raw.get("seller_text", "")
    city = None
    seller_name = None
    # Pattern: "Durham (235 miles)" or dealer name
    loc_match = re.match(r"(.+?)\s*\(\d+\s*miles?\)", seller_text)
    if loc_match:
        city = loc_match.group(1).strip()
    elif seller_text:
        seller_name = seller_text
        city = seller_text

    return {
        "provider": "autotrader",
        "make": brand,
        "model": model,
        "variant": variant,
        "price": price_gbp,
        "price_eur": price_eur,
        "price_original": price_gbp,
        "currency": "GBP",
        "year": reg_year,
        "registration_str": year_str or None,
        "mileage_km": mileage_km,
        "fuel_type": fuel_type or None,
        "transmission": transmission or None,
        "body_type": body_type or None,
        "power_hp": None,
        "power_kw": None,
        "country": "GB",
        "city": city,
        "seller_type": "dealer",
        "seller_name": seller_name,
        "steering_side": "RHD",
        "source_url": raw.get("source_url"),
        "image_urls": raw.get("image_urls") or [],
        "condition": "used",
    }


def scrape(headless: bool = True, limit: int = 0, brand: str | None = None):
    """Scrape AutoTrader UK listings for premium brands.

    Args:
        headless: Run browser in headless mode.
        limit: Max listings per brand (0 = unlimited).
        brand: Specific brand to scrape, or None for all.
    """
    listings = load_checkpoint("autotrader")
    seen_urls = {l.get("source_url") for l in listings if l.get("source_url")}

    brands = [brand] if brand else PREMIUM_BRANDS
    pw, browser, ctx, page = setup_browser(headless=headless)

    try:
        cookies_dismissed = False

        for brand_name in brands:
            if brand_name not in BRAND_PARAMS:
                log.warning("No params for brand %s, skipping", brand_name)
                continue

            log.info("Scraping AutoTrader UK for %s...", brand_name)
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

                log.info("[autotrader] %s page %d/%d: %d items (%d new), total: %d",
                         brand_name, page_num, MAX_PAGES, len(raw_items), new_count, len(listings))

                if limit and brand_count >= limit:
                    log.info("Reached limit of %d for %s", limit, brand_name)
                    break

                if page_num % 25 == 0:
                    save_checkpoint(listings, "autotrader")

                time.sleep(2)

        listings = deduplicate(listings)
        save_checkpoint(listings, "autotrader")
        log.info("AutoTrader scrape complete: %d listings", len(listings))

    finally:
        browser.close()
        pw.stop()

    return listings
