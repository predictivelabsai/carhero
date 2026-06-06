from fasthtml.common import *
from utils.i18n import t, agent_t, get_lang


def _stat(value, label):
    return Div(
        Span(value, cls='text-xl md:text-2xl font-semibold text-black'),
        Span(label, cls='text-[11px] tracking-[0.12em] uppercase text-gray-400 mt-1'),
        cls='flex flex-col items-center md:items-start',
    )


def home_page(sess=None):
    lang = get_lang(sess or {})

    agents = ["car_search", "market_analyst", "valuator", "car_compare", "advisor"]

    hero = Section(
        Div(
            H1(t('hero_h1', lang),
               cls='text-[36px] sm:text-5xl md:text-7xl font-medium tracking-tight text-black leading-[1.08] max-w-4xl'),
            P(t('hero_h2', lang),
              cls='mt-3 text-xl md:text-2xl text-gray-400 max-w-2xl'),
            P(t('hero_body', lang),
              cls='mt-5 text-base text-gray-500 max-w-xl leading-relaxed'),
            Div(
                A(t('hero_cta_start', lang), href='/app',
                  cls='inline-flex items-center gap-2 px-6 py-3 rounded-full text-sm font-medium no-underline bg-black text-white hover:bg-gray-800 transition-colors'),
                A(t('hero_cta_explore', lang), href='/app/market-map',
                  cls='inline-flex items-center gap-2 px-6 py-3 rounded-full text-sm font-medium no-underline bg-transparent text-black border border-gray-200 hover:border-black transition-colors'),
                cls='mt-8 flex items-center gap-3 flex-wrap',
            ),
            cls='max-w-7xl mx-auto px-5 md:px-6 py-20 md:py-28',
        ),
    )

    stats = Div(
        Div(
            _stat('50,000+', t('stat_listings', lang)),
            _stat('9', t('stat_brands', lang)),
            _stat('3+', t('stat_countries', lang)),
            _stat('4', t('stat_sources', lang)),
            cls='max-w-7xl mx-auto px-5 md:px-6 py-5 grid grid-cols-2 md:grid-cols-4 gap-6',
        ),
        cls='border-y border-gray-100 bg-gray-50/60',
    )

    features = Section(
        Div(
            Div(
                *[Article(
                    H3(title, cls='text-black text-lg font-medium mb-2'),
                    P(body, cls='text-gray-500 text-sm leading-relaxed'),
                    A(link, href=href, cls='inline-block mt-3 text-sm font-medium text-black no-underline hover:underline'),
                    cls='p-6 rounded-xl bg-white border border-gray-100',
                ) for title, body, link, href in [
                    (t('feat_advisory', lang), t('feat_advisory_body', lang), t('feat_advisory_link', lang), '/app'),
                    (t('feat_market', lang), t('feat_market_body', lang), t('feat_market_link', lang), '/app/market-map'),
                    (t('feat_valuation', lang), t('feat_valuation_body', lang), t('feat_valuation_link', lang), '/app'),
                ]],
                cls='grid md:grid-cols-3 gap-4',
            ),
            cls='max-w-7xl mx-auto px-5 md:px-6',
        ),
        cls='py-14 md:py-20 border-t border-gray-100',
    )

    how = Section(
        Div(
            Span('How it works', cls='text-[11px] tracking-[0.18em] uppercase text-gray-400'),
            H2(t('how_title', lang), cls='mt-3 text-2xl md:text-3xl font-medium text-black max-w-2xl mb-10'),
            Div(
                *[Article(
                    P(num, cls='text-[11px] tracking-widest uppercase text-gray-300 mb-3'),
                    H3(title, cls='text-black text-lg font-medium mb-2'),
                    P(body, cls='text-gray-500 text-sm leading-relaxed'),
                    cls='p-6 rounded-xl bg-white border border-gray-100',
                ) for num, title, body in [
                    ('01', t('how_01_title', lang), t('how_01_body', lang)),
                    ('02', t('how_02_title', lang), t('how_02_body', lang)),
                    ('03', t('how_03_title', lang), t('how_03_body', lang)),
                ]],
                cls='grid md:grid-cols-3 gap-4',
            ),
            cls='max-w-7xl mx-auto px-5 md:px-6',
        ),
        cls='py-14 md:py-20 border-t border-gray-100 bg-gray-50',
    )

    agent_cards = [
        Div(
            H4(agent_t(slug, 'name', lang), cls='text-sm font-medium text-black mb-1'),
            P(agent_t(slug, 'one_liner', lang), cls='text-xs text-gray-500 leading-relaxed'),
            cls='p-4 rounded-xl border border-gray-100',
        )
        for slug in agents
    ]

    agents_section = Section(
        Div(
            Span(t('agents_title', lang), cls='text-[11px] tracking-[0.18em] uppercase text-gray-400'),
            H2(t('agents_subtitle', lang), cls='mt-3 text-2xl md:text-3xl font-medium text-black max-w-2xl mb-10'),
            Div(*agent_cards, cls='grid grid-cols-2 md:grid-cols-5 gap-3'),
            cls='max-w-7xl mx-auto px-5 md:px-6',
        ),
        cls='py-14 md:py-20 border-t border-gray-100',
    )

    brands_section = Section(
        Div(
            Span('Brands we cover', cls='text-[11px] tracking-[0.18em] uppercase text-gray-400'),
            Div(
                *[Span(brand, cls='px-4 py-2 rounded-full border border-gray-100 text-sm text-gray-600')
                  for brand in ['BMW', 'Mercedes-Benz', 'Audi', 'Porsche', 'Jaguar', 'Land Rover', 'Volvo', 'Tesla', 'Lexus']],
                cls='mt-4 flex flex-wrap gap-2 justify-center',
            ),
            cls='max-w-7xl mx-auto px-5 md:px-6 text-center',
        ),
        cls='py-10 border-t border-gray-100',
    )

    cta = Section(
        Div(
            H2(t('cta_headline', lang), cls='text-2xl md:text-3xl font-medium text-black mb-4'),
            P(t('cta_body', lang), cls='text-gray-500 text-sm max-w-xl mx-auto mb-8 leading-relaxed'),
            A(t('hero_cta_start', lang), href='/app',
              cls='inline-flex items-center px-6 py-3 rounded-full text-sm font-medium no-underline bg-black text-white hover:bg-gray-800 transition-colors'),
            cls='max-w-7xl mx-auto px-5 md:px-6 text-center',
        ),
        cls='py-14 md:py-20 border-t border-gray-100 bg-gray-50',
    )

    sources = Div(
        Div(
            P('Data from', cls='text-[11px] tracking-[0.12em] uppercase text-gray-400 mb-2'),
            Div(
                *[Span(src, cls='text-sm text-gray-500 font-medium')
                  for src in ['AutoTrader UK', 'mobile.de', 'AutoScout24', 'Autohero']],
                cls='flex items-center gap-4 flex-wrap justify-center',
            ),
            cls='max-w-7xl mx-auto px-5 md:px-6 text-center',
        ),
        cls='py-6 border-t border-gray-100',
    )

    return Div(
        hero, stats, features, how, agents_section, brands_section, cta, sources,
        style='overflow-x:hidden',
    )
