"""Site rules: slugs and reserved paths (Site-0602 / 0603), theme tokens + WCAG contrast (Site-0400),
menus (Site-0102), redirect loops (Site-0613), accessibility check before publish (Site-0206 / 0005).
Pure functions, unit-tested.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from ._document import iter_blocks

SITE_SLUG = re.compile(r'^[a-z0-9][a-z0-9-]{0,38}[a-z0-9]$')
PAGE_SLUG = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
RESERVED_PATHS = frozenset(
    {'_assets', '_preview', '_forms', '_api', '_site', 'robots.txt', 'sitemap.xml', 'favicon.ico', '.well-known'}
)
MAX_PAGE_DEPTH = 5
HEX = re.compile(r'^#[0-9a-fA-F]{6}$')

FONTS = (
    'Inter', 'Plus Jakarta Sans', 'Manrope', 'DM Sans', 'Poppins', 'Lora', 'Merriweather', 'Playfair Display',
    'Source Serif 4', 'JetBrains Mono', 'System',
)
COLOR_TOKENS = ('primary', 'secondary', 'accent', 'background', 'surface', 'text', 'muted')

DEFAULT_THEME: dict[str, Any] = {
    'colors': {
        'primary': '#2563eb',
        'secondary': '#0f172a',
        'accent': '#f59e0b',
        'background': '#ffffff',
        'surface': '#f1f5f9',
        'text': '#0f172a',
        'muted': '#475569',
    },
    'fonts': {'heading': 'Inter', 'body': 'Inter'},
    'radius': 'md',
    'spacing': 'normal',
    'buttonStyle': 'solid',
    'header': {'layout': 'left', 'sticky': True, 'showName': True, 'logo': None, 'ctaLabel': None, 'ctaHref': None},
    'footer': {'text': None, 'showMenu': True, 'social': []},
}

_ENUMS = {
    'radius': ('none', 'sm', 'md', 'lg', 'full'),
    'spacing': ('compact', 'normal', 'relaxed'),
    'buttonStyle': ('solid', 'outline', 'pill'),
}
_SOCIAL = ('facebook', 'instagram', 'linkedin', 'x', 'youtube', 'tiktok', 'github')


def slugify(text: str, max_len: int = 40) -> str:
    import unicodedata

    ascii_text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode()
    slug = re.sub(r'[^a-z0-9]+', '-', ascii_text.lower()).strip('-')
    return slug[:max_len].strip('-')


def site_slug_error(slug: str) -> str | None:
    if not SITE_SLUG.match(slug or ''):
        return 'slug must be 2-40 lowercase letters, digits or hyphens, starting and ending with a letter or digit'
    if slug in RESERVED_PATHS:
        return 'this slug is reserved'
    return None


def page_slug_error(slug: str) -> str | None:
    if not slug or len(slug) > 80 or not PAGE_SLUG.match(slug):
        return 'slug must be lowercase letters, digits and single hyphens (max 80)'
    if slug in RESERVED_PATHS:
        return 'this slug is reserved'
    return None


def page_path(parent_path: str | None, slug: str) -> str:
    base = (parent_path or '').rstrip('/')
    return f'{base}/{slug}'


# --- theme ----------------------------------------------------------------------------------------


def _luminance(hex_color: str) -> float:
    def channel(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return round((la + 0.05) / (lb + 0.05), 2)


def readable_on(color: str) -> str:
    """``#ffffff`` or ``#0f172a``, whichever contrasts more with ``color`` (button labels)."""
    return '#ffffff' if contrast_ratio(color, '#ffffff') >= contrast_ratio(color, '#0f172a') else '#0f172a'


@dataclass(frozen=True, slots=True)
class Issue:
    severity: Literal['error', 'warning']
    code: str
    message: str
    block_id: str | None = None
    page_id: str | None = None


def theme_contrast_issues(theme: dict[str, Any]) -> list[Issue]:
    """WCAG AA (4.5:1 text, 3:1 large text / UI) on the token pairs the blocks use."""
    c = theme.get('colors') or {}
    pairs = [
        ('text', 'background', 4.5, 'Body text on the page background'),
        ('text', 'surface', 4.5, 'Text on muted sections'),
        ('muted', 'background', 4.5, 'Secondary text on the page background'),
        ('primary', 'background', 3.0, 'Links and outline buttons on the page background'),
    ]
    issues: list[Issue] = []
    for fg, bg, minimum, label in pairs:
        if HEX.match(c.get(fg, '')) and HEX.match(c.get(bg, '')):
            ratio = contrast_ratio(c[fg], c[bg])
            if ratio < minimum:
                issues.append(Issue('warning', 'contrast', f'{label}: contrast {ratio}:1 is below {minimum}:1 (WCAG AA)'))
    return issues


def normalize_theme(raw: Any) -> tuple[dict[str, Any], list[str]]:
    """Merge ``raw`` over the defaults and validate; returns the theme and errors."""
    errors: list[str] = []
    theme = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_THEME.items()}
    if not isinstance(raw, dict):
        return theme, ['theme must be an object']
    colors = raw.get('colors') or {}
    for token in COLOR_TOKENS:
        value = colors.get(token)
        if value is None:
            continue
        if not isinstance(value, str) or not HEX.match(value):
            errors.append(f'colors.{token} must be a #rrggbb color')
        else:
            theme['colors'][token] = value.lower()
    fonts = raw.get('fonts') or {}
    for role in ('heading', 'body'):
        if role in fonts:
            if fonts[role] not in FONTS:
                errors.append(f'fonts.{role} must be one of {", ".join(FONTS)}')
            else:
                theme['fonts'][role] = fonts[role]
    for key, options in _ENUMS.items():
        if key in raw:
            if raw[key] not in options:
                errors.append(f'{key} must be one of {", ".join(options)}')
            else:
                theme[key] = raw[key]
    header = raw.get('header') or {}
    if isinstance(header, dict):
        if header.get('layout') in ('left', 'center'):
            theme['header']['layout'] = header['layout']
        for flag in ('sticky', 'showName'):
            if isinstance(header.get(flag), bool):
                theme['header'][flag] = header[flag]
        logo = header.get('logo')
        if logo is None or (isinstance(logo, str) and re.match(r'^asset:[0-9a-fA-F-]{36}$', logo)):
            theme['header']['logo'] = logo
        else:
            errors.append('header.logo must be asset:<id>')
        for key, limit in (('ctaLabel', 40), ('ctaHref', 2048)):
            value = header.get(key)
            if value is None or (isinstance(value, str) and len(value) <= limit):
                theme['header'][key] = value or None
            else:
                errors.append(f'header.{key} is invalid')
    footer = raw.get('footer') or {}
    if isinstance(footer, dict):
        text = footer.get('text')
        if text is None or (isinstance(text, str) and len(text) <= 500):
            theme['footer']['text'] = text or None
        else:
            errors.append('footer.text is longer than 500 characters')
        if isinstance(footer.get('showMenu'), bool):
            theme['footer']['showMenu'] = footer['showMenu']
        social = footer.get('social') or []
        clean_social = []
        if isinstance(social, list):
            for item in social[:8]:
                if (
                    isinstance(item, dict)
                    and item.get('network') in _SOCIAL
                    and isinstance(item.get('url'), str)
                    and item['url'].startswith('https://')
                ):
                    clean_social.append({'network': item['network'], 'url': item['url'][:500]})
                else:
                    errors.append('footer.social items need a known network and an https:// url')
        theme['footer']['social'] = clean_social
    return theme, errors


# --- menus ----------------------------------------------------------------------------------------

MENU_KEYS = ('header', 'footer')


def normalize_menu(items: Any, depth: int = 1) -> tuple[list[dict[str, Any]], list[str]]:
    """Items ``{label, page_id | url, children?}``, 2 levels, max 12 per level."""
    from ._document import is_safe_url

    errors: list[str] = []
    out: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return [], ['menu items must be a list']
    for i, item in enumerate(items[:12]):
        if not isinstance(item, dict):
            errors.append(f'item {i} must be an object')
            continue
        label = item.get('label')
        if not isinstance(label, str) or not label.strip() or len(label) > 60:
            errors.append(f'item {i}: label must be 1-60 characters')
            continue
        entry: dict[str, Any] = {'label': label.strip()}
        if item.get('page_id'):
            entry['page_id'] = str(item['page_id'])
        elif isinstance(item.get('url'), str) and is_safe_url(item['url']):
            entry['url'] = item['url']
        elif not item.get('children'):
            errors.append(f'item {i}: link to a page or a URL')
            continue
        children = item.get('children')
        if children:
            if depth >= 2:
                errors.append(f'item {i}: menus have 2 levels')
            else:
                entry['children'], child_errors = normalize_menu(children, depth + 1)
                errors += child_errors
        out.append(entry)
    return out, errors


# --- redirects ------------------------------------------------------------------------------------


def creates_loop(redirects: dict[str, str], source: str, target: str) -> bool:
    """``True`` when adding ``source → target`` makes a cycle in ``redirects`` (path → path)."""
    seen = {source}
    current = target
    for _ in range(len(redirects) + 2):
        if current in seen:
            return True
        seen.add(current)
        nxt = redirects.get(current)
        if nxt is None:
            return False
        current = nxt
    return True


# --- accessibility --------------------------------------------------------------------------------


def accessibility_issues(
    doc: dict[str, Any], *, asset_alts: dict[str, str | None], page_id: str | None = None
) -> list[Issue]:
    """Missing alt text (error: Site-0005), heading order, empty links / buttons (warnings)."""
    issues: list[Issue] = []
    last_level = 1
    h1 = 0
    for block in iter_blocks(doc):
        props = block.get('props') or {}
        bid = block.get('id')
        btype = block.get('type')
        if btype == 'image':
            ref = props.get('image')
            if not ref:
                issues.append(Issue('warning', 'empty_image', 'Image block without an image', bid, page_id))
            elif not (props.get('alt') or asset_alts.get(ref)):
                issues.append(Issue('error', 'missing_alt', 'Image without alt text', bid, page_id))
        if btype in ('gallery', 'logos'):
            for item in props.get('items') or []:
                ref = item.get('image')
                if ref and not (item.get('alt') or item.get('name') or asset_alts.get(ref)):
                    issues.append(Issue('error', 'missing_alt', 'Gallery image without alt text', bid, page_id))
        if btype == 'hero' and props.get('image') and props.get('layout') != 'background' and not asset_alts.get(props['image']):
            issues.append(Issue('warning', 'missing_alt', 'Hero image without alt text in the media library', bid, page_id))
        if btype == 'heading':
            level = props.get('level') or 2
            h1 += level == 1
            if level > last_level + 1:
                issues.append(Issue('warning', 'heading_order', f'Heading level {level} follows level {last_level}', bid, page_id))
            last_level = level
        if btype == 'hero':
            h1 += 1
            last_level = 1
        if btype == 'button' and not props.get('href'):
            issues.append(Issue('warning', 'empty_link', 'Button without a link', bid, page_id))
        if btype == 'video' and not (props.get('title')):
            issues.append(Issue('warning', 'missing_title', 'Video without a title', bid, page_id))
    if h1 > 1:
        issues.append(Issue('warning', 'multiple_h1', 'More than one main heading (hero / heading level 1)', None, page_id))
    return issues
