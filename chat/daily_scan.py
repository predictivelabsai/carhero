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
                    P("Price comparisons across European markets. Biggest savings first.",
                      cls="text-sm text-gray-500 mb-4"),
                    Div(id="scan-loading", cls="text-center text-gray-400 py-12"),
                    Div(id="scan-stats", style="display:none",
                        cls="mb-4 p-3 bg-green-50 border border-green-200 rounded-lg text-center text-sm text-green-700"),
                    Div(id="scan-filters", style="display:none",
                        cls="mb-4 p-3 border border-gray-200 rounded-lg"),
                    Div(
                        Div(id="filter-count", cls="text-xs text-gray-400 mb-2"),
                        H3("Best Price Arbitrage", cls="text-base font-semibold mb-3"),
                        Div(id="comparisons-list", cls="space-y-2 mb-6"),
                        id="comparisons-section", style="display:none",
                    ),
                    Div(
                        H3("Price Drops", cls="text-base font-semibold mb-3"),
                        Div(id="price-drops", cls="space-y-2 mb-6"),
                        id="drops-section", style="display:none",
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
            scan_price_comparisons, scan_price_drops, scan_freshness_stats,
        )

        stats = scan_freshness_stats()
        comparisons = scan_price_comparisons(limit=100)
        price_drops = scan_price_drops(limit=15)

        def _default(o):
            if isinstance(o, Decimal):
                return float(o)
            if hasattr(o, 'isoformat'):
                return o.isoformat()
            raise TypeError

        raw = _json.loads(_json.dumps({
            "stats": stats,
            "comparisons": comparisons,
            "price_drops": price_drops,
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
            let scrapeDate = '';
            if (s.last_scrape) {
                const d = new Date(s.last_scrape);
                scrapeDate = ' \\u00B7 Last scan: ' + d.toLocaleDateString(undefined, {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'});
            }
            el('scan-stats').innerHTML =
                '<strong>' + fresh + '</strong> listings \\u00B7 ' +
                '<strong>' + nw + '</strong> new \\u00B7 ' +
                '<strong>' + prov + '</strong> providers \\u00B7 ' +
                '<strong>' + ctry + '</strong> countries' + scrapeDate;
            el('scan-stats').style.display = 'block';
        }

        function fmtEur(n) {
            return n ? '\\u20AC' + Number(n).toLocaleString(undefined, {maximumFractionDigits:0}) : '--';
        }
        function srcLabel(country, provider) {
            return (country||'') + ' / ' + (provider||'');
        }
        function viewLink(url) {
            if (!url) return '';
            return '<a href="' + url + '" target="_blank" rel="noopener" style="font-size:11px;color:#000;text-decoration:underline;">View listing</a>';
        }
        function kmLabel(km) {
            return km ? Number(km).toLocaleString() + ' km' : '';
        }

        const allComparisons = (data.comparisons || []).sort((a,b) => (b.savings_eur||0) - (a.savings_eur||0));

        // Build filter bar
        if (allComparisons.length) {
            const makes = [...new Set(allComparisons.map(d => d.make))].sort();
            const years = [...new Set(allComparisons.map(d => d.year).filter(Boolean))].sort((a,b) => b-a);

            const iStyle = 'padding:6px 10px;border:1px solid #D1D5DB;border-radius:6px;font-size:13px;flex:1;min-width:0;';
            el('scan-filters').innerHTML =
                '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">' +
                    '<input id="f-search" type="text" placeholder="Search make or model..." style="' + iStyle + 'flex:2;">' +
                    '<select id="f-make" style="' + iStyle + '"><option value="">All makes</option>' +
                        makes.map(m => '<option value="' + m + '">' + m + '</option>').join('') + '</select>' +
                    '<select id="f-year" style="' + iStyle + '"><option value="">All years</option>' +
                        years.map(y => '<option value="' + y + '">' + y + '</option>').join('') + '</select>' +
                    '<select id="f-gap" style="' + iStyle + '">' +
                        '<option value="0">Any price gap</option>' +
                        '<option value="1000">\\u2265 \\u20AC1,000</option>' +
                        '<option value="5000">\\u2265 \\u20AC5,000</option>' +
                        '<option value="10000">\\u2265 \\u20AC10,000</option>' +
                        '<option value="25000">\\u2265 \\u20AC25,000</option>' +
                        '<option value="50000">\\u2265 \\u20AC50,000</option>' +
                    '</select>' +
                    '<button id="f-clear" style="padding:6px 12px;border:1px solid #D1D5DB;border-radius:6px;font-size:12px;cursor:pointer;background:#F9FAFB;white-space:nowrap;">Clear</button>' +
                '</div>';
            el('scan-filters').style.display = 'block';

            function applyFilters() {
                const q = (el('f-search').value || '').toLowerCase().trim();
                const make = el('f-make').value;
                const year = el('f-year').value;
                const gap = Number(el('f-gap').value) || 0;

                const filtered = allComparisons.filter(d => {
                    if (make && d.make !== make) return false;
                    if (year && String(d.year) !== year) return false;
                    if (gap && (d.savings_eur || 0) < gap) return false;
                    if (q) {
                        const hay = (d.make + ' ' + d.model + ' ' + (d.year||'')).toLowerCase();
                        if (!hay.includes(q)) return false;
                    }
                    return true;
                });

                renderComparisons(filtered);
                el('filter-count').textContent = filtered.length + ' of ' + allComparisons.length + ' results';
            }

            el('f-search').addEventListener('input', applyFilters);
            el('f-make').addEventListener('change', applyFilters);
            el('f-year').addEventListener('change', applyFilters);
            el('f-gap').addEventListener('change', applyFilters);
            el('f-clear').addEventListener('click', () => {
                el('f-search').value = '';
                el('f-make').value = '';
                el('f-year').value = '';
                el('f-gap').value = '0';
                applyFilters();
            });
        }

        function renderComparisons(items) {
            if (!items.length) {
                el('comparisons-list').innerHTML = '<div style="text-align:center;color:#9CA3AF;padding:24px;">No matches found.</div>';
                el('comparisons-section').style.display = 'block';
                return;
            }
            el('comparisons-section').style.display = 'block';
            el('comparisons-list').innerHTML = items.map(d => {
                const pct = d.savings_pct || 0;
                const color = pct >= 15 ? '#16A34A' : pct >= 8 ? '#F59E0B' : '#6B7280';
                const cheapKm = kmLabel(d.cheap_km);
                const expKm = kmLabel(d.expensive_km);
                return '<div style="border:1px solid #E5E7EB;border-radius:8px;padding:12px 14px;margin-bottom:2px;">' +
                    '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">' +
                        '<div><strong style="font-size:14px;">' + d.make + ' ' + d.model + '</strong> <span style="color:#6B7280;font-size:13px;">' + (d.year||'') + '</span>' +
                        '<br><span style="font-size:11px;color:#9CA3AF;">' + (d.listing_count||0) + ' listings \\u00B7 ' + (d.source_count||0) + ' sources</span></div>' +
                        '<div><span style="background:' + color + ';color:white;padding:2px 8px;border-radius:10px;font-size:12px;font-weight:600;">Save ' + fmtEur(d.savings_eur) + ' (' + Number(pct).toFixed(0) + '%)</span></div>' +
                    '</div>' +
                    '<div style="display:flex;gap:8px;">' +
                        '<div style="flex:1;background:#F0FDF4;border-radius:6px;padding:8px 10px;">' +
                            '<div style="font-size:10px;color:#16A34A;font-weight:600;text-transform:uppercase;margin-bottom:2px;">Cheapest</div>' +
                            '<div style="font-size:15px;font-weight:700;color:#15803D;">' + fmtEur(d.cheap_price) + '</div>' +
                            '<div style="font-size:11px;color:#6B7280;">' + srcLabel(d.cheap_country, d.cheap_provider) + (cheapKm ? ' \\u00B7 ' + cheapKm : '') + '</div>' +
                            '<div style="margin-top:4px;">' + viewLink(d.cheap_url) + '</div>' +
                        '</div>' +
                        '<div style="flex:1;background:#FEF2F2;border-radius:6px;padding:8px 10px;">' +
                            '<div style="font-size:10px;color:#DC2626;font-weight:600;text-transform:uppercase;margin-bottom:2px;">Most Expensive</div>' +
                            '<div style="font-size:15px;font-weight:700;color:#991B1B;">' + fmtEur(d.expensive_price) + '</div>' +
                            '<div style="font-size:11px;color:#6B7280;">' + srcLabel(d.expensive_country, d.expensive_provider) + (expKm ? ' \\u00B7 ' + expKm : '') + '</div>' +
                            '<div style="margin-top:4px;">' + viewLink(d.expensive_url) + '</div>' +
                        '</div>' +
                    '</div>' +
                '</div>';
            }).join('');
        }

        // Initial render
        if (allComparisons.length) {
            renderComparisons(allComparisons);
            el('filter-count').textContent = allComparisons.length + ' results';
        }

        // Price drops
        if (data.price_drops && data.price_drops.length) {
            el('drops-section').style.display = 'block';
            el('price-drops').innerHTML = data.price_drops.map(d => {
                const km = kmLabel(d.mileage_km);
                const yr = d.year || '';
                const src = srcLabel(d.country, d.provider);
                const url = viewLink(d.source_url);
                return '<div style="border:1px solid #E5E7EB;border-radius:8px;padding:10px 14px;display:flex;justify-content:space-between;align-items:center;">' +
                    '<div><strong>' + d.make + ' ' + d.model + '</strong> ' + (d.variant||'') +
                    '<br><span style="font-size:12px;color:#6B7280;">' + yr + (yr && km ? ' \\u00B7 ' : '') + km + ' \\u00B7 ' + src + '</span></div>' +
                    '<div style="text-align:right;">' + fmtEur(d.price_eur) +
                    '<br><span style="text-decoration:line-through;color:#9CA3AF;font-size:11px;">' + fmtEur(d.old_price) + '</span>' +
                    ' <span style="color:#16A34A;font-size:12px;font-weight:600;">\\u2193' + (d.drop_pct||0).toFixed(0) + '%</span>' +
                    '<br>' + url + '</div></div>';
            }).join('');
        }

        // If nothing at all
        if (!allComparisons.length && !data.price_drops?.length) {
            el('scan-loading').style.display = 'block';
            el('scan-loading').textContent = 'No scan data available yet. Deals appear after the nightly scrape runs.';
        }

    } catch(e) {
        el('scan-loading').textContent = 'Failed to load scan data.';
        console.error(e);
    }
})();
"""
