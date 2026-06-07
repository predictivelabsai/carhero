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


# --- Daily digest scheduler ---

def _start_daily_digest():
    """Background daemon thread that sends the deals digest once per day."""
    import threading
    import time as _time
    from datetime import datetime, timedelta

    DIGEST_HOUR = int(os.environ.get("DIGEST_HOUR", "7"))

    def _run_digest():
        try:
            from scripts.daily_deals import main as digest_main
            import sys
            sys.argv = ["daily_deals", "--all"]
            digest_main()
        except Exception as e:
            print(f"ERROR:    Daily digest error: {e}", flush=True)

    def _loop():
        while True:
            now = datetime.now()
            target = now.replace(hour=DIGEST_HOUR, minute=0, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            wait = (target - now).total_seconds()
            print(f"INFO:     Daily digest scheduled for {target.strftime('%Y-%m-%d %H:%M')} ({wait/3600:.1f}h from now)", flush=True)
            _time.sleep(wait)
            _run_digest()

    t = threading.Thread(target=_loop, daemon=True)
    t.start()


# --- Initialize DB on startup ---

@app.on_event("startup")
async def startup():
    try:
        init_db()
    except Exception as e:
        print(f"DB init warning: {e}")

    if os.environ.get("DIGEST_ENABLED", "1") == "1":
        _start_daily_digest()


serve(port=int(os.environ.get('PORT', 5011)), reload=False)
