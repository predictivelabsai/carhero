"""Market Map — interactive treemap + price trends + geographic comparison with filters.

GET /app/market-map              → full-page Market Map with filters
GET /api/market-map/treemap      → Plotly JSON (supports ?country=&make=&fuel_type=)
GET /api/market-map/trends       → Plotly JSON (supports ?country=&make=&fuel_type=)
GET /api/market-map/geo          → Plotly JSON (supports ?make=&model=)
GET /api/market-map/filters      → available filter values
"""

from __future__ import annotations

import json
import logging

import pandas as pd
import plotly.express as px
from fasthtml.common import (
    Html, Head, Body, Script, NotStr,
    Div, Span, H2, H3, P, A, Button, Select, Option, Label, Input,
)
from starlette.requests import Request
from starlette.responses import JSONResponse

from chat.layout import _head
from chat.components import left_pane, signin_overlay
from chat.routes import _ensure_user, _list_sessions

log = logging.getLogger(__name__)

CHART_LAYOUT = dict(
    paper_bgcolor="#FFFFFF", plot_bgcolor="#F5F5F5",
    font=dict(family="Inter, system-ui", color="#1A1A1A"),
    margin=dict(l=40, r=20, t=50, b=40),
    title=dict(font=dict(size=15)),
)

PREMIUM_BRANDS = ["BMW", "Mercedes-Benz", "Audi", "Porsche", "Jaguar",
                  "Land Rover", "Volvo", "Tesla", "Lexus"]


def _build_where(params: dict) -> tuple[str, dict]:
    conditions = ["status = 'active'", "price_eur > 0"]
    bind = {}
    country = params.get("country", "").strip()
    if country and country != "ALL":
        conditions.append("country = :country")
        bind["country"] = country
    make = params.get("make", "").strip()
    if make and make != "ALL":
        conditions.append("make = :make")
        bind["make"] = make
    fuel_type = params.get("fuel_type", "").strip()
    if fuel_type and fuel_type != "ALL":
        conditions.append("fuel_type ILIKE :fuel_type")
        bind["fuel_type"] = f"%{fuel_type}%"
    min_year = params.get("min_year", "").strip()
    if min_year and min_year.isdigit():
        conditions.append("year >= :min_year")
        bind["min_year"] = int(min_year)
    max_year = params.get("max_year", "").strip()
    if max_year and max_year.isdigit():
        conditions.append("year <= :max_year")
        bind["max_year"] = int(max_year)
    return "WHERE " + " AND ".join(conditions), bind


def _fetch_treemap_data(params: dict):
    """Fetch treemap data with geographic price spread as color.

    For each make/model, computes:
    - listing_count: total listings
    - avg_price: overall average
    - price_spread_pct: (max_country_avg - min_country_avg) / overall_avg * 100
      A high spread means big arbitrage opportunity across countries.
    """
    from db import SessionLocal
    from sqlalchemy import text
    db = SessionLocal()
    try:
        where, bind = _build_where(params)
        sql = text(f"""
            WITH by_country AS (
                SELECT make, model, country,
                       COUNT(*) AS cnt,
                       AVG(price_eur) AS country_avg
                FROM carhero.car_listings
                {where}
                GROUP BY make, model, country
                HAVING COUNT(*) >= 1
            ),
            aggregated AS (
                SELECT make, model,
                       SUM(cnt) AS listing_count,
                       ROUND(AVG(country_avg)::numeric, 0) AS avg_price,
                       CASE WHEN COUNT(DISTINCT country) >= 2
                            THEN ROUND(((MAX(country_avg) - MIN(country_avg))
                                  / NULLIF(AVG(country_avg), 0) * 100)::numeric, 1)
                            ELSE 0 END AS price_spread_pct
                FROM by_country
                GROUP BY make, model
            )
            SELECT * FROM aggregated
            ORDER BY listing_count DESC
            LIMIT 100
        """)
        return [dict(r._mapping) for r in db.execute(sql, bind)]
    finally:
        db.close()


def _fetch_trend_data(params: dict):
    from db import SessionLocal
    from sqlalchemy import text
    db = SessionLocal()
    try:
        where, bind = _build_where(params)
        where += " AND year IS NOT NULL AND year >= 2005"
        sql = text(f"""
            SELECT year, make,
                   ROUND(AVG(price_eur)::numeric, 0) AS avg_price,
                   COUNT(*) AS listings
            FROM carhero.car_listings
            {where}
            GROUP BY year, make
            HAVING COUNT(*) >= 1
            ORDER BY year
        """)
        return [dict(r._mapping) for r in db.execute(sql, bind)]
    finally:
        db.close()


def _fetch_geo_data(params: dict):
    from db import SessionLocal
    from sqlalchemy import text
    db = SessionLocal()
    try:
        conditions = ["status = 'active'", "price_eur > 0"]
        bind = {}
        make = params.get("make", "").strip()
        if make and make != "ALL":
            conditions.append("make = :make")
            bind["make"] = make
        model = params.get("model", "").strip()
        if model:
            conditions.append("model ILIKE :model")
            bind["model"] = f"%{model}%"
        where = "WHERE " + " AND ".join(conditions)
        sql = text(f"""
            SELECT country, provider,
                   COUNT(*) AS listings,
                   ROUND(AVG(price_eur)::numeric, 0) AS avg_price,
                   ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_eur)::numeric, 0) AS median_price
            FROM carhero.car_listings
            {where}
            GROUP BY country, provider
            HAVING COUNT(*) >= 1
            ORDER BY avg_price
        """)
        return [dict(r._mapping) for r in db.execute(sql, bind)]
    finally:
        db.close()


def _fetch_filter_options():
    from db import SessionLocal
    from sqlalchemy import text
    db = SessionLocal()
    try:
        countries = [r[0] for r in db.execute(text(
            "SELECT DISTINCT country FROM carhero.car_listings WHERE status='active' AND country IS NOT NULL ORDER BY 1"
        ))]
        makes = [r[0] for r in db.execute(text(
            "SELECT DISTINCT make FROM carhero.car_listings WHERE status='active' ORDER BY 1"
        ))]
        fuel_types = [r[0] for r in db.execute(text(
            "SELECT DISTINCT fuel_type FROM carhero.car_listings WHERE status='active' AND fuel_type IS NOT NULL ORDER BY 1"
        ))]
        return {"countries": countries, "makes": makes, "fuel_types": fuel_types}
    finally:
        db.close()


def _build_treemap_fig(rows):
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["listing_count"] = df["listing_count"].astype(int)
    df["avg_price"] = pd.to_numeric(df["avg_price"], errors="coerce").fillna(0)
    df["price_spread_pct"] = pd.to_numeric(df["price_spread_pct"], errors="coerce").fillna(0)

    has_spread = (df["price_spread_pct"] > 0).sum() > len(df) * 0.2
    if has_spread:
        color_col = "price_spread_pct"
        color_scale = "RdYlGn_r"
        title = "Listings by Brand/Model (color = price spread % across countries)"
    else:
        color_col = "avg_price"
        color_scale = "Viridis"
        title = "Listings by Brand/Model (color = avg price EUR)"

    fig = px.treemap(
        df, path=["make", "model"],
        values="listing_count", color=color_col,
        color_continuous_scale=color_scale,
        title=title,
        hover_data={"avg_price": ":,.0f", "price_spread_pct": ":.1f"},
    )
    fig.update_layout(**CHART_LAYOUT)
    fig.update_layout(margin=dict(t=30, l=0, r=0, b=0))
    return fig


def _build_trend_fig(rows):
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["avg_price"] = pd.to_numeric(df["avg_price"], errors="coerce")
    fig = px.area(
        df, x="year", y="avg_price", color="make",
        title="Average Price by Model Year & Brand", markers=True,
    )
    fig.update_layout(**CHART_LAYOUT)
    return fig


def _build_geo_fig(rows):
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["label"] = df["country"] + " / " + df["provider"]
    fig = px.bar(
        df, x="label", y="avg_price", color="country",
        text="avg_price", title="Average Price by Country & Provider",
    )
    fig.update_traces(texttemplate="EUR %{text:,.0f}", textposition="outside")
    fig.update_layout(**CHART_LAYOUT)
    fig.update_layout(xaxis_title="", yaxis_title="Price (EUR)")
    return fig


COUNTRY_NAMES = {"GB": "United Kingdom", "DE": "Germany", "EU": "Other EU"}


def register_market_map_routes(rt):

    @rt("/api/market-map/treemap")
    def treemap_json(request: Request):
        params = dict(request.query_params)
        rows = _fetch_treemap_data(params)
        fig = _build_treemap_fig(rows)
        if not fig:
            return JSONResponse({"error": "No data"})
        return JSONResponse(json.loads(fig.to_json()))

    @rt("/api/market-map/trends")
    def trends_json(request: Request):
        params = dict(request.query_params)
        rows = _fetch_trend_data(params)
        fig = _build_trend_fig(rows)
        if not fig:
            return JSONResponse({"error": "No data"})
        return JSONResponse(json.loads(fig.to_json()))

    @rt("/api/market-map/geo")
    def geo_json(request: Request):
        params = dict(request.query_params)
        rows = _fetch_geo_data(params)
        fig = _build_geo_fig(rows)
        if not fig:
            return JSONResponse({"error": "No data"})
        return JSONResponse(json.loads(fig.to_json()))

    @rt("/api/market-map/filters")
    def filter_options():
        return JSONResponse(_fetch_filter_options())

    @rt("/app/market-map")
    def market_map_page(sess):
        uid, email = _ensure_user(sess)
        sessions = _list_sessions(uid) if uid else []

        country_options = [
            Option("All Countries", value="ALL", selected=True),
            Option("United Kingdom", value="GB"),
            Option("Germany", value="DE"),
            Option("Other EU", value="EU"),
        ]
        make_options = [Option("All Brands", value="ALL", selected=True)] + [
            Option(b, value=b) for b in PREMIUM_BRANDS
        ]
        fuel_options = [
            Option("All Fuels", value="ALL", selected=True),
            Option("Petrol", value="Petrol"),
            Option("Diesel", value="Diesel"),
            Option("Electric", value="Electric"),
            Option("Hybrid", value="Hybrid"),
            Option("Plugin Hybrid", value="Plugin Hybrid"),
        ]

        body = Body(
            signin_overlay(),
            Div(id="left-overlay", cls="left-overlay", onclick="toggleLeftPane()"),
            left_pane(user_email=email, sessions=sessions, current_sid=""),
            Div(
                Div(
                    Div(
                        Button("=", cls="mobile-menu-btn", onclick="toggleLeftPane()"),
                        Span("Market Map", cls="chat-header-title"),
                        cls="chat-header-left",
                    ),
                    Div(
                        A("Back to chat", href="/app", cls="header-action-btn"),
                        A("Analytics", href="/app/analytics", cls="header-action-btn"),
                        cls="chat-header-actions",
                    ),
                    cls="chat-header",
                ),
                Div(
                    Div(
                        H2("Market Map", cls="text-xl font-display font-bold mb-1"),
                        P("Interactive market overview. Larger blocks = more listings. Color = price spread across countries (red = big arbitrage opportunity).",
                          cls="text-sm text-gray-500 mb-4"),
                        cls="mb-2",
                    ),
                    # Filters
                    Div(
                        Div(
                            Label("Country", cls="text-xs text-gray-400 block mb-1"),
                            Select(*country_options, id="filter-country",
                                   cls="text-sm border border-gray-200 rounded px-2 py-1.5 bg-white",
                                   onchange="applyFilters()"),
                            cls="flex flex-col",
                        ),
                        Div(
                            Label("Brand", cls="text-xs text-gray-400 block mb-1"),
                            Select(*make_options, id="filter-make",
                                   cls="text-sm border border-gray-200 rounded px-2 py-1.5 bg-white",
                                   onchange="applyFilters()"),
                            cls="flex flex-col",
                        ),
                        Div(
                            Label("Fuel Type", cls="text-xs text-gray-400 block mb-1"),
                            Select(*fuel_options, id="filter-fuel",
                                   cls="text-sm border border-gray-200 rounded px-2 py-1.5 bg-white",
                                   onchange="applyFilters()"),
                            cls="flex flex-col",
                        ),
                        Div(
                            Label("Model (geo)", cls="text-xs text-gray-400 block mb-1"),
                            Input(type="text", id="filter-model", placeholder="e.g. X5, 3 Series...",
                                  cls="text-sm border border-gray-200 rounded px-2 py-1.5 w-36",
                                  onkeydown="if(event.key==='Enter')applyFilters()"),
                            cls="flex flex-col",
                        ),
                        Button("Apply", onclick="applyFilters()",
                               cls="self-end px-4 py-1.5 text-sm bg-black text-white rounded cursor-pointer border-none hover:bg-gray-800"),
                        cls="flex flex-wrap items-end gap-4 mb-6 p-3 bg-gray-50 rounded-lg border border-gray-100",
                    ),
                    # Treemap
                    Div(id="treemap-chart", style="width:100%;min-height:500px;"),
                    # Price Trends
                    Div(
                        H3("Price by Model Year", cls="text-lg font-display font-bold mt-8 mb-1"),
                        P("Average asking price by model year and brand. Shows depreciation curves.",
                          cls="text-sm text-gray-500 mb-4"),
                    ),
                    Div(id="trend-chart", style="width:100%;min-height:400px;"),
                    # Geographic Comparison
                    Div(
                        H3("Geographic Price Comparison", cls="text-lg font-display font-bold mt-8 mb-1"),
                        P("Average price for the same brand/model across countries and providers.",
                          cls="text-sm text-gray-500 mb-4"),
                    ),
                    Div(id="geo-chart", style="width:100%;min-height:400px;"),
                    cls="px-6 py-4 overflow-y-auto flex-1",
                ),
                cls="center-pane",
            ),
            Script(NotStr("""
                function getFilterParams() {
                    const country = document.getElementById('filter-country').value;
                    const make = document.getElementById('filter-make').value;
                    const fuel = document.getElementById('filter-fuel').value;
                    const model = document.getElementById('filter-model').value.trim();
                    const params = new URLSearchParams();
                    if (country && country !== 'ALL') params.set('country', country);
                    if (make && make !== 'ALL') params.set('make', make);
                    if (fuel && fuel !== 'ALL') params.set('fuel_type', fuel);
                    if (model) params.set('model', model);
                    return params.toString();
                }

                async function applyFilters() {
                    const qs = getFilterParams();
                    const noData = '<p style="color:#888;padding:2rem;text-align:center">No data for these filters. Try scraping some listings first.</p>';

                    const t = await fetch('/api/market-map/treemap?' + qs);
                    const tData = await t.json();
                    if (tData.data) Plotly.newPlot('treemap-chart', tData.data, tData.layout, {responsive: true});
                    else document.getElementById('treemap-chart').innerHTML = noData;

                    const r = await fetch('/api/market-map/trends?' + qs);
                    const rData = await r.json();
                    if (rData.data) Plotly.newPlot('trend-chart', rData.data, rData.layout, {responsive: true});
                    else document.getElementById('trend-chart').innerHTML = noData;

                    const g = await fetch('/api/market-map/geo?' + qs);
                    const gData = await g.json();
                    if (gData.data) Plotly.newPlot('geo-chart', gData.data, gData.layout, {responsive: true});
                    else document.getElementById('geo-chart').innerHTML = noData;
                }

                applyFilters();
            """)),
            Script(src="/static/chat.js"),
            cls="bg-white text-ink font-sans antialiased app pane-closed",
        )
        return Html(_head("Market Map"), body)
