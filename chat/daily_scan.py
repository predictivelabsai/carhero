"""Daily Scan workspace page — shows the latest digest content inline."""

from __future__ import annotations

from fasthtml.common import (
    Html, Body, Div, Span, H2, H3, P, A, Button, Script, NotStr,
)

from chat.layout import _head
from chat.components import left_pane, signin_overlay


def _ensure_user(sess):
    from chat.routes import _ensure_user as eu
    return eu(sess)


def _list_sessions(uid):
    from chat.routes import _list_sessions as ls
    return ls(uid)


def register_daily_scan_routes(rt):

    @rt("/app/daily-scan")
    def daily_scan_page(sess):
        uid, email = _ensure_user(sess)
        sessions = _list_sessions(uid) if uid else []

        body = Body(
            signin_overlay(),
            Div(id="left-overlay", cls="left-overlay", onclick="toggleLeftPane()"),
            left_pane(user_email=email, sessions=sessions, current_sid=""),
            Div(
                Div(
                    Div(
                        Button("=", cls="mobile-menu-btn", onclick="toggleLeftPane()"),
                        Span("Daily Scan", cls="chat-header-title"),
                        cls="chat-header-left",
                    ),
                    Div(
                        A("Back to chat", href="/app", cls="header-action-btn"),
                        A("Market Map", href="/app/market-map", cls="header-action-btn"),
                        cls="chat-header-actions",
                    ),
                    cls="chat-header",
                ),
                Div(
                    H2("Daily Scan", cls="text-xl font-display font-bold mb-1"),
                    P("Fresh deals from overnight European market scan. Updated daily.",
                      cls="text-sm text-gray-500 mb-6"),
                    Div(id="scan-loading", cls="text-center text-gray-400 py-12"),
                    Div(id="scan-stats", style="display:none",
                        cls="mb-6 p-3 bg-green-50 border border-green-200 rounded-lg text-center text-sm text-green-700"),
                    Div(
                        H3("New Listings", cls="text-base font-semibold mb-3"),
                        Div(id="new-listings", cls="space-y-2 mb-6"),
                        id="new-section", style="display:none",
                    ),
                    Div(
                        H3("Price Drops", cls="text-base font-semibold mb-3"),
                        Div(id="price-drops", cls="space-y-2 mb-6"),
                        id="drops-section", style="display:none",
                    ),
                    Div(
                        H3("Best Price Arbitrage", cls="text-base font-semibold mb-3"),
                        Div(id="deals-list", cls="space-y-2 mb-6"),
                        id="deals-section", style="display:none",
                    ),
                    Div(
                        H3("Lowest Prices", cls="text-base font-semibold mb-3"),
                        Div(id="cheapest-list", cls="space-y-2 mb-6"),
                        id="cheapest-section", style="display:none",
                    ),
                    cls="px-6 py-4 overflow-y-auto flex-1",
                ),
                cls="center-pane",
            ),
            Script(NotStr(_PAGE_JS)),
            Script(src="/static/chat.js"),
            cls="bg-white text-ink font-sans antialiased app pane-closed",
        )
        return Html(_head("Daily Scan"), body)

    @rt("/api/daily-scan")
    def daily_scan_api(sess):
        import json as _json
        from decimal import Decimal
        from starlette.responses import JSONResponse
        from utils.deals_scanner import (
            scan_new_listings, scan_price_drops, scan_deals,
            scan_lowest_prices, scan_freshness_stats,
        )

        stats = scan_freshness_stats()
        new_listings = scan_new_listings(limit=15)
        price_drops = scan_price_drops(limit=15)
        deals = scan_deals(limit=15)
        cheapest = scan_lowest_prices(limit=15)

        def _default(o):
            if isinstance(o, Decimal):
                return float(o)
            raise TypeError

        raw = _json.loads(_json.dumps({
            "stats": stats,
            "new_listings": new_listings,
            "price_drops": price_drops,
            "deals": deals,
            "cheapest": cheapest,
        }, default=_default))

        return JSONResponse(raw)


_PAGE_JS = """
(async function() {
    const el = id => document.getElementById(id);
    el('scan-loading').textContent = 'Loading daily scan...';

    try {
        const resp = await fetch('/api/daily-scan');
        const data = await resp.json();
        el('scan-loading').style.display = 'none';

        // Stats banner
        const s = data.stats || {};
        if (s.fresh_count > 0 || s.total_active > 0) {
            const fresh = (s.fresh_count || 0).toLocaleString();
            const nw = (s.new_count || 0).toLocaleString();
            const prov = s.providers_scraped || 0;
            const ctry = s.countries_covered || 0;
            const total = (s.total_active || 0).toLocaleString();
            el('scan-stats').innerHTML =
                '<strong>' + fresh + '</strong> listings refreshed &middot; ' +
                '<strong>' + nw + '</strong> new &middot; ' +
                '<strong>' + prov + '</strong> providers &middot; ' +
                '<strong>' + ctry + '</strong> countries &middot; ' +
                '<strong>' + total + '</strong> total active';
            el('scan-stats').style.display = 'block';
        }

        function fmtEur(n) {
            return n ? '\\u20AC' + Number(n).toLocaleString(undefined, {maximumFractionDigits:0}) : '--';
        }
        function srcLabel(country, provider) {
            return (country||'') + ' / ' + (provider||'');
        }

        function listingCard(c, extra) {
            const km = c.mileage_km ? c.mileage_km.toLocaleString() + ' km' : '';
            const yr = c.year || '';
            const v = c.variant || '';
            const src = srcLabel(c.country, c.provider);
            const url = c.source_url ? '<a href="' + c.source_url + '" target="_blank" style="font-size:11px;color:#000;text-decoration:underline;">View listing</a>' : '';
            return '<div style="border:1px solid #E5E7EB;border-radius:8px;padding:10px 14px;display:flex;justify-content:space-between;align-items:center;">' +
                '<div><strong>' + c.make + ' ' + c.model + '</strong> ' + v +
                '<br><span style="font-size:12px;color:#6B7280;">' + yr + (yr && km ? ' \\u00B7 ' : '') + km + ' \\u00B7 ' + src + '</span></div>' +
                '<div style="text-align:right;">' + fmtEur(c.price_eur) + (extra||'') + '<br>' + url + '</div></div>';
        }

        // New listings
        if (data.new_listings && data.new_listings.length) {
            el('new-section').style.display = 'block';
            el('new-listings').innerHTML = data.new_listings.map(c => listingCard(c)).join('');
        }

        // Price drops
        if (data.price_drops && data.price_drops.length) {
            el('drops-section').style.display = 'block';
            el('price-drops').innerHTML = data.price_drops.map(d => {
                const extra = '<br><span style="text-decoration:line-through;color:#9CA3AF;font-size:11px;">' + fmtEur(d.old_price) + '</span>' +
                    ' <span style="color:#16A34A;font-size:12px;font-weight:600;">\\u2193' + (d.drop_pct||0).toFixed(0) + '%</span>';
                return listingCard(d, extra);
            }).join('');
        }

        // Deals
        if (data.deals && data.deals.length) {
            el('deals-section').style.display = 'block';
            el('deals-list').innerHTML = data.deals.map(d => {
                const pct = d.savings_pct || 0;
                const color = pct >= 15 ? '#16A34A' : pct >= 8 ? '#F59E0B' : '#6B7280';
                return '<div style="border:1px solid #E5E7EB;border-radius:8px;padding:10px 14px;display:flex;justify-content:space-between;align-items:center;">' +
                    '<div><strong>' + d.make + ' ' + d.model + '</strong>' +
                    '<br><span style="font-size:12px;color:#6B7280;">' + (d.listing_count||0) + ' listings across sources</span></div>' +
                    '<div style="text-align:right;">' +
                    '<span style="font-size:12px;">From ' + fmtEur(d.min_price) + '</span><br>' +
                    '<span style="background:' + color + ';color:white;padding:1px 8px;border-radius:10px;font-size:11px;font-weight:600;">Save ' + Number(pct).toFixed(0) + '%</span>' +
                    '</div></div>';
            }).join('');
        }

        // Cheapest
        if (data.cheapest && data.cheapest.length) {
            el('cheapest-section').style.display = 'block';
            el('cheapest-list').innerHTML = data.cheapest.map(c => listingCard(c)).join('');
        }

        // If nothing at all
        if (!data.new_listings?.length && !data.price_drops?.length && !data.deals?.length && !data.cheapest?.length) {
            el('scan-loading').style.display = 'block';
            el('scan-loading').textContent = 'No scan data available yet. Deals appear after the nightly scrape runs.';
        }

    } catch(e) {
        el('scan-loading').textContent = 'Failed to load scan data.';
        console.error(e);
    }
})();
"""
