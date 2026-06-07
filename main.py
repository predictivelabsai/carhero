import os
from fasthtml.common import *
from starlette.responses import RedirectResponse
from starlette.staticfiles import StaticFiles

from components.layout import app_styles, Page
from pages.home import home_page
from pages.about import about_page
from pages.contact import contact_page

from starlette.responses import JSONResponse as _JSONResponse

from db import init_db

app, rt = fast_app(
    hdrs=(app_styles(),),
    secret_key=os.environ.get('APP_SECRET', 'carhero-app-2026'),
)

app.mount("/static", StaticFiles(directory="static"), name="static")


@rt("/health")
def health():
    return _JSONResponse({"status": "ok"})


# --- Language switching ---

@rt('/set-lang/{code}')
def set_language(code: str, sess):
    from utils.i18n import set_lang, LANGUAGES
    if code in LANGUAGES:
        set_lang(sess, code)
    return RedirectResponse('/', status_code=303)


# --- Public pages ---

@rt
def index(sess):
    return Page(home_page(sess=sess), active='home', sess=sess)

@rt
def about(sess):
    return Page(about_page(), active='about', title='About', sess=sess)

@rt
def contact(sess):
    return Page(contact_page(), active='contact', title='Contact', sess=sess)


# --- Chat routes (Phase 5) ---

from chat.routes import register_chat_routes
register_chat_routes(rt)

# --- Market Map + Analytics (Phase 6) ---

from chat.market_map import register_market_map_routes
register_market_map_routes(rt)

from chat.analytics import register_analytics_routes
register_analytics_routes(rt)

# --- Auth routes ---

from auth.routes import register_auth_routes
register_auth_routes(rt)

# --- Favorites + Saved Searches + Garage ---

from chat.favorites import register_favorites_routes
register_favorites_routes(rt)

from chat.garage import register_garage_routes
register_garage_routes(rt)


# --- Scraper + Daily digest scheduler ---

SCRAPE_PROVIDERS = [
    "autoscout24", "autotrader", "autohero",
    "auto24_ee", "auto24_lt", "auto24_lv", "blocket",
    "otomoto", "coches", "marktplaats", "nettiauto", "bilbasen",
    "donedeal", "finn", "standvirtual", "autovit",
]


def _start_scrape_and_digest():
    """Background daemon: scrape all providers, load to DB, then send digest.

    Timeline each day:
        DIGEST_HOUR - 1  →  run all scrapers (sequential, ~45-60 min)
        after scrape      →  load checkpoint JSONs into DB
        DIGEST_HOUR       →  send deals digest email to all users
    """
    import threading
    import time as _time
    from datetime import datetime, timedelta

    DIGEST_HOUR = int(os.environ.get("DIGEST_HOUR", "7"))
    SCRAPE_HOUR = (DIGEST_HOUR - 1) % 24

    def _run_scrapers():
        from scripts.scrape_cars import get_scraper
        for provider in SCRAPE_PROVIDERS:
            try:
                print(f"INFO:     [scheduler] Scraping {provider}...", flush=True)
                scraper = get_scraper(provider)
                scraper(headless=True, limit=0, brand=None)
            except Exception as e:
                print(f"ERROR:    [scheduler] Scraper {provider} failed: {e}", flush=True)

    def _load_to_db():
        from scripts.scrape_cars import load_to_db
        total = 0
        for provider in SCRAPE_PROVIDERS:
            try:
                total += load_to_db(provider)
            except Exception as e:
                print(f"ERROR:    [scheduler] DB load {provider} failed: {e}", flush=True)
        print(f"INFO:     [scheduler] Loaded {total} new listings to DB", flush=True)

    def _run_digest():
        try:
            from scripts.daily_deals import main as digest_main
            import sys
            sys.argv = ["daily_deals", "--all"]
            digest_main()
        except Exception as e:
            print(f"ERROR:    [scheduler] Digest error: {e}", flush=True)

    def _loop():
        while True:
            now = datetime.now()
            scrape_target = now.replace(hour=SCRAPE_HOUR, minute=0, second=0, microsecond=0)
            if scrape_target <= now:
                scrape_target += timedelta(days=1)
            wait = (scrape_target - now).total_seconds()
            digest_time = scrape_target + timedelta(hours=1)
            print(f"INFO:     [scheduler] Next scrape: {scrape_target.strftime('%Y-%m-%d %H:%M')} ({wait/3600:.1f}h), digest: {digest_time.strftime('%H:%M')}", flush=True)
            _time.sleep(wait)

            print(f"INFO:     [scheduler] Starting scrape run...", flush=True)
            _run_scrapers()

            print(f"INFO:     [scheduler] Loading data to DB...", flush=True)
            _load_to_db()

            print(f"INFO:     [scheduler] Sending digest...", flush=True)
            _run_digest()

    t = threading.Thread(target=_loop, daemon=True)
    t.start()


# --- Mount FastAPI mobile API at /api/v1 (optional) ---

try:
    from api.app import api_router
    app.mount("/api/v1", api_router)
    print("INFO:     Mobile API mounted at /api/v1 (docs: /api/v1/docs)")
except ImportError:
    print("INFO:     FastAPI not installed — mobile API disabled (monolith mode)")


# --- Initialize DB on startup ---

@app.on_event("startup")
async def startup():
    try:
        init_db()
    except Exception as e:
        print(f"DB init warning: {e}")

    if os.environ.get("DIGEST_ENABLED", "1") == "1":
        _start_scrape_and_digest()


serve(port=int(os.environ.get('PORT', 5011)), reload=False)
