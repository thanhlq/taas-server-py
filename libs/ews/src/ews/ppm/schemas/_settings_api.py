"""Wire types of ``/api/v1/ppm/settings`` (capability levels, Ppm-0009)."""

from __future__ import annotations

from typing import Any

import msgspec
from foundation.serialization import ApiRequest, ApiResponse


class PpmCapabilityOut(ApiResponse, kw_only=True):
    key: str
    level: int
    """1 Simple · 2 Professional · 3 Enterprise · 4 AI-native."""
    core: bool = False
    enabled: bool


class PpmSettingsOut(ApiResponse, kw_only=True):
    level: int
    capabilities: list[PpmCapabilityOut]
    overrides: dict[str, bool] = msgspec.field(default_factory=dict)
    """Single capabilities switched against the level's default."""
    settings: dict[str, Any] = msgspec.field(default_factory=dict)
    """Organization preferences: ``editors`` ``{default, enabled}`` (description editor modes), …"""
    version: int
    can_manage: bool
    """``ppm.settings:manage`` (organization admins)."""
    can_create_project: bool


class PpmSettingsUpdate(ApiRequest, kw_only=True):
    version: int | None = None
    """The version read (409 ``stale_settings`` when it changed meanwhile)."""
    level: int | None = None
    capabilities: dict[str, bool | None] | None = None
    """``{key: true | false}`` overrides; ``null`` drops an override (back to the level's default)."""
    settings: dict[str, Any] | None = None
