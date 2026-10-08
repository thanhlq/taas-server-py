"""Wire types of the members routes every object app exposes (``/{id}/members``, ``/{id}/member-candidates``,
``/roles``): msgspec, snake_case JSON."""

from __future__ import annotations

from foundation.serialization import ApiRequest, ApiResponse


class MemberOut(ApiResponse, kw_only=True):
    user_id: str
    email: str | None = None
    name: str | None = None
    role: str
    inherited: bool = False
    """Organization / tenant admins: they hold every right through the organization (read-only here)."""


class MemberUpsert(ApiRequest, kw_only=True):
    user_id: str
    role: str


class CandidateOut(ApiResponse, kw_only=True):
    user_id: str
    email: str
    name: str | None = None


class RoleOut(ApiResponse, kw_only=True):
    key: str
    name: str
    description: str
    rank: int
    """Higher = more rights (catalog order of the kind's roles)."""
    default: bool = False
