"""Access to business objects that carry their own RBAC domain (``<kind>:<id>``): drives, knowledge
spaces, blogs — the generic form of ``ews/sites/_access.py`` and ``ews/ppm/_access.py``.

- ``ObjectAccess``: domains (object → organization chain → tenant), checks with the 404 / 403 rule,
  implicit roles (space visibility, organization drive membership), permissions for UI hints, roles of a
  user, objects shared with a user, creator grant, cleanup.
- Members (``_members``): catalog roles of the kind, list (direct + inherited admins), candidates of the
  organization, grant / change / revoke — one implementation for every app's ``/{id}/members`` routes.

Spec: taas-specs/iam/specs/authorization-rbac-spec.md §5, app-roles-spec.md §5 (assignment rules).
"""

from ._members import (
    list_members,
    member_candidates,
    object_roles,
    remove_member,
    upsert_member,
)
from ._object import ObjectAccess, role_permissions
from .schemas import CandidateOut, MemberOut, MemberUpsert, RoleOut

__all__ = [
    'CandidateOut',
    'MemberOut',
    'MemberUpsert',
    'ObjectAccess',
    'RoleOut',
    'list_members',
    'member_candidates',
    'object_roles',
    'remove_member',
    'role_permissions',
    'upsert_member',
]
