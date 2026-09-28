"""Workflow template catalog (read-only, shipped with the API).

The standard lives in ``taas-specs/ppm/project/project-workflow/`` (templates,
categories, stage types); ``data/`` is a copy of it plus the catalog
translations (``data/i18n/<locale>.json``, English = source).

- **Stage types** are canonical keys grouped in five lifecycle bands
  (initial · active · review · done · special). A stage's ``stage_type`` drives
  analytics: tasks in a *done*-band stage are done; *excluded* types
  (cancelled, rejected) do not count towards progress.
- **Templates** define the work item types, the allowed stage types and the
  default board (stages) of a workflow for one business domain.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

_DATA = Path(__file__).parent / 'data'
DEFAULT_LOCALE = 'en'


@dataclass(frozen=True)
class StageTypeInfo:
    key: str
    band: str
    order: int
    tone: str
    excluded_from_progress: bool = False


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


@lru_cache(maxsize=1)
def _stage_types() -> dict[str, StageTypeInfo]:
    raw = _read(_DATA / 'stage-types.json')
    return {
        s['key']: StageTypeInfo(
            key=s['key'],
            band=s['band'],
            order=s['order'],
            tone=s['tone'],
            excluded_from_progress=bool(s.get('excluded_from_progress')),
        )
        for s in raw['stage_types']
    }


def stage_types() -> list[StageTypeInfo]:
    """Every canonical stage type, in lifecycle order."""
    return sorted(_stage_types().values(), key=lambda s: s.order)


def stage_type_info(key: Optional[str]) -> Optional[StageTypeInfo]:
    return _stage_types().get(key or '')


def is_stage_type(key: Optional[str]) -> bool:
    return (key or '') in _stage_types()


def done_stage_types() -> frozenset[str]:
    """Stage types whose tasks count as done (the *done* band)."""
    return frozenset(k for k, s in _stage_types().items() if s.band == 'done')


def excluded_stage_types() -> frozenset[str]:
    """Stage types left out of progress (e.g. cancelled, rejected)."""
    return frozenset(k for k, s in _stage_types().items() if s.excluded_from_progress)


def stage_type_tone(key: Optional[str]) -> str:
    info = stage_type_info(key)
    return info.tone if info else 'gray'


# ── Templates ─────────────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _templates() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for path in sorted((_DATA / 'templates').glob('*.json')):
        t = _read(path)
        out[t['id']] = t
    return out


@lru_cache(maxsize=1)
def _categories() -> list[dict[str, Any]]:
    return sorted(_read(_DATA / 'categories.json'), key=lambda c: c['order'])


@lru_cache(maxsize=32)
def _translations(locale: str) -> dict[str, Any]:
    path = _DATA / 'i18n' / f'{locale}.json'
    return _read(path) if path.exists() else {}


def available_locales() -> list[str]:
    return sorted(p.stem for p in (_DATA / 'i18n').glob('*.json'))


def resolve_locale(locale: Optional[str]) -> str:
    """Best catalog locale for a BCP 47 tag (``pt-PT`` → ``pt-BR``, ``zh-HK`` → ``zh-TW``)."""
    if not locale:
        return DEFAULT_LOCALE
    tag = locale.strip().replace('_', '-')
    available = available_locales()
    by_lower = {a.lower(): a for a in available}
    if tag.lower() in by_lower:
        return by_lower[tag.lower()]
    base = tag.split('-')[0].lower()
    if base == 'zh':
        traditional = any(p in tag.lower() for p in ('-tw', '-hk', '-mo', 'hant'))
        wanted = 'zh-tw' if traditional else 'zh-cn'
        return by_lower.get(wanted, DEFAULT_LOCALE)
    for a in available:
        if a.split('-')[0].lower() == base:
            return a
    return DEFAULT_LOCALE


class CatalogText:
    """Localized catalog strings with English fallback."""

    def __init__(self, locale: Optional[str]) -> None:
        self.locale = resolve_locale(locale)
        self._t = _translations(self.locale)
        self._en = _translations(DEFAULT_LOCALE)

    def _get(self, section: str, key: str, fallback: str) -> str:
        for source in (self._t, self._en):
            value = source.get(section, {}).get(key)
            if isinstance(value, str) and value:
                return value
        return fallback

    def category(self, cid: str, field: str, fallback: str) -> str:
        for source in (self._t, self._en):
            value = source.get('categories', {}).get(cid, {}).get(field)
            if value:
                return value
        return fallback

    def template(self, tid: str, field: str, fallback: str) -> str:
        for source in (self._t, self._en):
            value = source.get('templates', {}).get(tid, {}).get(field)
            if value:
                return value
        return fallback

    def work_item_type(self, key: str, fallback: str) -> str:
        return self._get('work_item_types', key, fallback)

    def work_item_description(self, key: str, fallback: Optional[str]) -> Optional[str]:
        return self._get('work_item_descriptions', key, fallback or '') or None

    def stage(self, name: str) -> str:
        return self._get('stages', name, name)

    def label(self, key: str, fallback: str) -> str:
        return self._get('labels', key, fallback)


def _localized_work_item_types(
    items: list[dict[str, Any]], text: CatalogText
) -> list[dict[str, Any]]:
    out = []
    for w in items:
        item = {**w, 'term': text.work_item_type(w['key'], w['term'])}
        desc = text.work_item_description(w['key'], w.get('description'))
        if desc:
            item['description'] = desc
        out.append(item)
    return out


def template_ids() -> list[str]:
    return list(_templates())


def get_template(
    template_id: Optional[str], locale: Optional[str] = None
) -> Optional[dict[str, Any]]:
    """A full template (localized), or None for an unknown id."""
    raw = _templates().get(template_id or '')
    if raw is None:
        return None
    text = CatalogText(locale)
    return {
        **raw,
        'name': text.template(raw['id'], 'name', raw['name']),
        'description': text.template(raw['id'], 'description', raw['description']),
        'work_item_types': _localized_work_item_types(raw['work_item_types'], text),
        'stages': [{**s, 'name': text.stage(s['name'])} for s in raw['stages']],
        'stage_suggestions': [
            {
                **s,
                'name': text.stage(s['name']),
                'color': s.get('color') or stage_type_tone(s['stage_type']),
            }
            for s in raw['stage_suggestions']
        ],
    }


def template_summary(template: dict[str, Any]) -> dict[str, Any]:
    return {
        'id': template['id'],
        'category': template['category'],
        'name': template['name'],
        'description': template['description'],
        'icon': template.get('icon'),
        'color': template.get('color'),
        'workflow_type': template.get('workflow_type'),
        'stage_names': [s['name'] for s in template['stages']],
        'work_item_type_count': len(template['work_item_types']),
    }


def list_categories(locale: Optional[str] = None) -> list[dict[str, Any]]:
    """Categories (UI order) with their template summaries, localized."""
    text = CatalogText(locale)
    out = []
    for c in _categories():
        templates = [get_template(tid, locale) for tid in c['templates']]
        out.append(
            {
                'id': c['id'],
                'name': text.category(c['id'], 'name', c['name']),
                'description': text.category(c['id'], 'description', c['description']),
                'icon': c.get('icon'),
                'color': c.get('color'),
                'order': c['order'],
                'templates': [template_summary(t) for t in templates if t],
            }
        )
    return out


def localized_stage_name(name: str, locale: Optional[str]) -> str:
    return CatalogText(locale).stage(name)


def localized_work_item_types(
    items: list[dict[str, Any]], locale: Optional[str]
) -> list[dict[str, Any]]:
    return _localized_work_item_types(items, CatalogText(locale))


def label(key: str, fallback: str, locale: Optional[str] = None) -> str:
    return CatalogText(locale).label(key, fallback)
