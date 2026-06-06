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


# --- Initialize DB on startup ---

@app.on_event("startup")
async def startup():
    try:
        init_db()
    except Exception as e:
        print(f"DB init warning: {e}")


serve(port=int(os.environ.get('PORT', 5011)), reload=False)
