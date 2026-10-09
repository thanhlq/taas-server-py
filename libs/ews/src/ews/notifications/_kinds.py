"""Notification kinds registered by the apps (Ppm-1701): channels on by default, mandatory in-app."""

from __future__ import annotations

from dataclasses import dataclass, field

CHANNELS = ('in_app', 'email')
MODES = ('instant', 'digest', 'off')


@dataclass(frozen=True, slots=True)
class Kind:
    key: str
    """``<app>:<kind>``, e.g. ``ppm:task_assigned``."""
    app: str
    email: str = 'instant'
    """Default e-mail mode: ``instant`` · ``digest`` · ``off``."""
    mandatory: bool = False
    """In-app cannot be switched off (approvals, mentions — Ppm-1706)."""
    labels: dict[str, str] = field(default_factory=dict)
    """English label (other languages: the web's i18n ``notifications.kinds.<app>.<kind>``)."""


_KINDS: dict[str, Kind] = {}


def register_kinds(*kinds: Kind) -> None:
    for kind in kinds:
        _KINDS[kind.key] = kind


def kind_of(key: str) -> Kind | None:
    return _KINDS.get(key)


def all_kinds(app: str | None = None) -> list[Kind]:
    return [k for k in _KINDS.values() if app is None or k.app == app]
