"""Starter templates (Site-0401): theme + menus + pages with sample content, built from the same blocks.

Links inside content are site-relative (``/contact``): the renderer prefixes the site's base path.
Menus reference pages by template key. The same shape is used by site import (Site-0007).
"""

from __future__ import annotations

import copy
import itertools
from typing import Any

from ._document import SCHEMA_VERSION
from ._rules import DEFAULT_THEME

_ids = itertools.count(1)


def _id(prefix: str = 'b') -> str:
    return f'{prefix}{next(_ids)}'


def b(type_: str, children: list[dict[str, Any]] | None = None, **props: Any) -> dict[str, Any]:
    block: dict[str, Any] = {'id': _id(), 'type': type_, 'props': {k: v for k, v in props.items() if v is not None}}
    if children is not None:
        block['children'] = children
    return block


def p(*parts: str | tuple[str, str]) -> dict[str, Any]:
    """Paragraph; a ``(text, mark)`` tuple is bold / italic / a link (``('label', 'href:/x')``)."""
    content: list[dict[str, Any]] = []
    for part in parts:
        if isinstance(part, tuple):
            text, mark = part
            if mark.startswith('href:'):
                content.append({'type': 'text', 'text': text, 'marks': [{'type': 'link', 'attrs': {'href': mark[5:]}}]})
            else:
                content.append({'type': 'text', 'text': text, 'marks': [{'type': mark}]})
        else:
            content.append({'type': 'text', 'text': part})
    return {'type': 'paragraph', 'content': content}


def h(level: int, text: str) -> dict[str, Any]:
    return {'type': 'heading', 'attrs': {'level': level}, 'content': [{'type': 'text', 'text': text}]}


def ul(*items: str) -> dict[str, Any]:
    return {
        'type': 'bulletList',
        'content': [{'type': 'listItem', 'content': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': i}]}]} for i in items],
    }


def rich(*nodes: dict[str, Any], align: str | None = None) -> dict[str, Any]:
    block = b('richText', align=align)
    block['content'] = {'type': 'doc', 'content': list(nodes)}
    return block


def doc(*sections: dict[str, Any]) -> dict[str, Any]:
    return {'schemaVersion': SCHEMA_VERSION, 'sections': list(sections)}


def section(*children: dict[str, Any], **props: Any) -> dict[str, Any]:
    return b('section', list(children), **props)


def columns(*cols: list[dict[str, Any]], **props: Any) -> dict[str, Any]:
    return b('columns', [b('column', list(c)) for c in cols], **props)


def theme(**overrides: Any) -> dict[str, Any]:
    t = copy.deepcopy(DEFAULT_THEME)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(t.get(key), dict):
            t[key].update(value)
        else:
            t[key] = value
    return t


def _not_found() -> dict[str, Any]:
    return {
        'key': 'not-found',
        'slug': 'not-found',
        'title': 'Page not found',
        'in_menu': False,
        'noindex': True,
        'not_found': True,
        'doc': doc(
            section(
                b('heading', text='Page not found', level=1, align='center'),
                rich(p('The page you are looking for does not exist or has moved.'), align='center'),
                b('button', label='Back to the home page', href='/', align='center'),
                spacing='xl',
            )
        ),
    }


def _contact_form(title: str = 'Send us a message') -> dict[str, Any]:
    return b(
        'form',
        title=title,
        submitLabel='Send message',
        successMessage='Thank you! We will get back to you within one business day.',
        items=[
            {'name': 'name', 'label': 'Your name', 'type': 'text', 'required': True},
            {'name': 'email', 'label': 'E-mail', 'type': 'email', 'required': True},
            {'name': 'message', 'label': 'Message', 'type': 'textarea', 'required': True},
        ],
    )


def _blank() -> dict[str, Any]:
    return {
        'key': 'blank',
        'name': 'Blank',
        'description': 'A home page and a 404 page, ready for your blocks.',
        'theme': theme(),
        'menus': {'header': [{'label': 'Home', 'page': 'home'}], 'footer': []},
        'pages': [
            {
                'key': 'home',
                'slug': 'home',
                'title': 'Home',
                'home': True,
                'doc': doc(
                    b('hero', title='Welcome to our new website', subtitle='Start editing this page to tell your story.', layout='centered'),
                ),
            },
            _not_found(),
        ],
    }


def _business() -> dict[str, Any]:
    return {
        'key': 'business',
        'name': 'Business',
        'description': 'Services company: hero, services, numbers, testimonials, pricing, FAQ and contact.',
        'theme': theme(colors={'primary': '#2563eb', 'accent': '#0ea5e9'}, fonts={'heading': 'Plus Jakarta Sans', 'body': 'Inter'},
                       header={'ctaLabel': 'Get in touch', 'ctaHref': '/contact'}),
        'menus': {
            'header': [{'label': 'Home', 'page': 'home'}, {'label': 'Services', 'page': 'services'}, {'label': 'About', 'page': 'about'}, {'label': 'Contact', 'page': 'contact'}],
            'footer': [{'label': 'About', 'page': 'about'}, {'label': 'Contact', 'page': 'contact'}],
        },
        'pages': [
            {
                'key': 'home', 'slug': 'home', 'title': 'Home', 'home': True,
                'seo': {'description': 'We help growing companies run better operations.'},
                'doc': doc(
                    b('hero', eyebrow='Consulting · Software · Support', title='Run your business with confidence',
                      subtitle='We design, build and operate the tools your team relies on every day — so you can focus on your customers.',
                      layout='centered', height='medium', primaryLabel='Book a call', primaryHref='/contact',
                      secondaryLabel='Our services', secondaryHref='/services'),
                    section(
                        b('features', title='What we do', subtitle='Three ways we help you grow.', columns=3, items=[
                            {'icon': 'compass', 'title': 'Strategy', 'text': 'Workshops and roadmaps that turn goals into a clear plan.'},
                            {'icon': 'code', 'title': 'Software', 'text': 'Web apps and integrations built for your processes.'},
                            {'icon': 'life-buoy', 'title': 'Support', 'text': 'Monitoring and a team that answers within hours.'},
                        ]),
                    ),
                    section(b('stats', items=[
                        {'value': '120+', 'label': 'Projects delivered'}, {'value': '98%', 'label': 'Client satisfaction'},
                        {'value': '24h', 'label': 'Response time'}, {'value': '12', 'label': 'Countries'},
                    ]), background='muted'),
                    section(b('testimonials', title='What clients say', items=[
                        {'quote': 'They understood our business in days and shipped in weeks.', 'name': 'Linh Nguyen', 'role': 'COO, Lotus Foods'},
                        {'quote': 'A reliable partner: clear communication and great results.', 'name': 'Marc Dubois', 'role': 'CEO, Alpine Tools'},
                    ])),
                    b('cta', title='Ready to start?', text='Tell us about your project — we reply within one business day.',
                      buttonLabel='Contact us', buttonHref='/contact', style='primary'),
                ),
            },
            {
                'key': 'services', 'slug': 'services', 'title': 'Services',
                'doc': doc(
                    section(b('heading', text='Services', level=1), rich(p('Pick a plan or ask for a tailored offer.'))),
                    section(b('pricing', items=[
                        {'name': 'Starter', 'price': '$900', 'period': '/ month', 'description': 'For small teams.',
                         'features': 'Monthly review\nE-mail support\n1 integration', 'ctaLabel': 'Choose Starter', 'ctaHref': '/contact'},
                        {'name': 'Growth', 'price': '$2,400', 'period': '/ month', 'description': 'Most popular.', 'highlighted': True,
                         'features': 'Weekly review\nPhone support\n5 integrations\nDedicated manager', 'ctaLabel': 'Choose Growth', 'ctaHref': '/contact'},
                        {'name': 'Enterprise', 'price': 'Custom', 'description': 'Large organizations.',
                         'features': 'SLA 99.9%\n24/7 support\nUnlimited integrations', 'ctaLabel': 'Talk to us', 'ctaHref': '/contact'},
                    ])),
                    section(b('faq', title='Questions', items=[
                        {'question': 'How fast can we start?', 'answer': 'Usually within two weeks after the first call.'},
                        {'question': 'Can we change plans later?', 'answer': 'Yes, plans change at the next billing period.'},
                    ]), width='narrow'),
                ),
            },
            {
                'key': 'about', 'slug': 'about', 'title': 'About us',
                'doc': doc(section(
                    b('heading', text='About us', level=1),
                    rich(
                        p('We are a small team of engineers and consultants who care about ', ('useful', 'bold'), ' software.'),
                        h(2, 'Our values'),
                        ul('Clarity over complexity', 'Long-term partnerships', 'Security by default'),
                    ),
                    width='narrow',
                )),
            },
            {
                'key': 'contact', 'slug': 'contact', 'title': 'Contact',
                'doc': doc(section(
                    columns(
                        [b('heading', text='Contact us', level=1), rich(p('We reply within one business day.')),
                         b('contact', email='hello@example.com', phone='+1 555 0100', address='1 Main Street\nSpringfield', hours='Mon–Fri 9:00–18:00')],
                        [_contact_form()],
                        gap='lg',
                    ),
                )),
            },
            _not_found(),
        ],
    }


def _cafe() -> dict[str, Any]:
    return {
        'key': 'cafe',
        'name': 'Café & restaurant',
        'description': 'Warm local business: menu highlights, opening hours, gallery, map and reservations.',
        'theme': theme(colors={'primary': '#b45309', 'secondary': '#1c1917', 'accent': '#65a30d', 'background': '#fffbf5', 'surface': '#f5ede1', 'text': '#1c1917', 'muted': '#57534e'},
                       fonts={'heading': 'Playfair Display', 'body': 'Lora'}, radius='lg', buttonStyle='pill'),
        'menus': {
            'header': [{'label': 'Home', 'page': 'home'}, {'label': 'Menu', 'page': 'menu'}, {'label': 'Visit us', 'page': 'visit'}],
            'footer': [{'label': 'Visit us', 'page': 'visit'}],
        },
        'pages': [
            {
                'key': 'home', 'slug': 'home', 'title': 'Home', 'home': True,
                'seo': {'description': 'Fresh coffee, roasted every morning.'},
                'doc': doc(
                    b('hero', eyebrow='Since 2012', title='Fresh coffee, daily', subtitle='Single-origin beans roasted every morning, pastries baked on site.',
                      layout='centered', height='tall', primaryLabel='See the menu', primaryHref='/menu', secondaryLabel='Find us', secondaryHref='/visit'),
                    section(b('features', title='Why people come back', columns=3, items=[
                        {'icon': 'leaf', 'title': 'Organic', 'text': 'Grown without pesticides by partner farms.'},
                        {'icon': 'coffee', 'title': 'Roasted here', 'text': 'Small batches, every morning.'},
                        {'icon': 'heart', 'title': 'Made with care', 'text': 'Pastries baked fresh on site.'},
                    ]), background='muted'),
                    section(b('iconList', items=[
                        {'icon': 'clock', 'text': 'Mon–Fri 7:00–19:00'}, {'icon': 'clock', 'text': 'Sat–Sun 8:00–20:00'},
                        {'icon': 'wifi', 'text': 'Free Wi-Fi'}, {'icon': 'dog', 'text': 'Dogs welcome'},
                    ]), width='narrow'),
                    b('cta', title='Book a table', text='Groups of six or more: reserve a day ahead.', buttonLabel='Reserve', buttonHref='/visit', style='dark'),
                ),
            },
            {
                'key': 'menu', 'slug': 'menu', 'title': 'Menu',
                'doc': doc(section(
                    b('heading', text='Menu', level=1, align='center'),
                    b('pricing', items=[
                        {'name': 'Espresso', 'price': '$3', 'description': 'Double shot, house blend.'},
                        {'name': 'Flat white', 'price': '$4.5', 'description': 'Velvety milk, single origin.', 'highlighted': True},
                        {'name': 'Croissant', 'price': '$3.5', 'description': 'Butter, baked this morning.'},
                    ]),
                )),
            },
            {
                'key': 'visit', 'slug': 'visit', 'title': 'Visit us',
                'doc': doc(section(
                    columns(
                        [b('heading', text='Visit us', level=1), b('contact', phone='+1 555 0142', address='12 Market Street\nPortland', hours='Every day 7:00–19:00'), _contact_form('Reserve a table')],
                        [b('map', address='Pioneer Courthouse Square, Portland', zoom=15, height='large')],
                        gap='lg',
                    ),
                )),
            },
            _not_found(),
        ],
    }


def _portfolio() -> dict[str, Any]:
    return {
        'key': 'portfolio',
        'name': 'Portfolio',
        'description': 'Personal or studio portfolio: bold intro, selected work, clients and contact.',
        'theme': theme(colors={'primary': '#7c3aed', 'secondary': '#111827', 'accent': '#ec4899', 'background': '#0b0b10', 'surface': '#16161f', 'text': '#f5f5f7', 'muted': '#a1a1aa'},
                       fonts={'heading': 'Manrope', 'body': 'DM Sans'}, radius='sm', buttonStyle='outline', header={'layout': 'center'}),
        'menus': {
            'header': [{'label': 'Work', 'page': 'home'}, {'label': 'About', 'page': 'about'}, {'label': 'Contact', 'page': 'contact'}],
            'footer': [],
        },
        'pages': [
            {
                'key': 'home', 'slug': 'home', 'title': 'Work', 'home': True,
                'doc': doc(
                    b('hero', eyebrow='Design studio', title='We craft brands people remember', subtitle='Identity, web and motion for ambitious teams.',
                      layout='centered', align='start', height='medium', primaryLabel='Start a project', primaryHref='/contact'),
                    section(b('features', title='Selected work', columns=2, items=[
                        {'icon': 'palette', 'title': 'Nordlicht — rebrand', 'text': 'Identity system and website for a Berlin energy start-up.'},
                        {'icon': 'film', 'title': 'Kite — launch film', 'text': '60-second motion piece for a product launch.'},
                        {'icon': 'layout', 'title': 'Atlas — design system', 'text': 'Components and guidelines for 40 product teams.'},
                        {'icon': 'type', 'title': 'Mono — typeface', 'text': 'Custom display face for a fashion label.'},
                    ])),
                    section(b('stats', items=[{'value': '14', 'label': 'Awards'}, {'value': '60+', 'label': 'Brands'}, {'value': '9', 'label': 'Years'}]), background='muted'),
                ),
            },
            {
                'key': 'about', 'slug': 'about', 'title': 'About',
                'doc': doc(section(b('heading', text='About the studio', level=1),
                                   rich(p('A team of six designers and developers working remotely from Lisbon and Hanoi.')), width='narrow')),
            },
            {
                'key': 'contact', 'slug': 'contact', 'title': 'Contact',
                'doc': doc(section(b('heading', text="Let's talk", level=1), _contact_form('Tell us about your project'), width='narrow')),
            },
            _not_found(),
        ],
    }


def templates() -> list[dict[str, Any]]:
    """Fresh copies (block ids are unique per call)."""
    return [_blank(), _business(), _cafe(), _portfolio()]


def get_template(key: str) -> dict[str, Any] | None:
    return next((t for t in templates() if t['key'] == key), None)
