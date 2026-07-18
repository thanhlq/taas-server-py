"""
🗺️  IAM business-flow definitions (single source of registration truth).

Purpose
-------
Each ``EventStep`` below describes one hop of an IAM business flow: the
triggering event, the handlers that react, and (critically) the
downstream events those handlers emit. A reader of this file alone can
trace a business process (e.g. user onboarding) top-to-bottom without
grepping ``.publish_*`` calls across the codebase.

These definitions are also **load-bearing**: handler registration,
event (de)serializers, and schema-registry schemas are all derived from
``IAM_ALL_FLOWS`` by :mod:`core.events.flow_registration` (wired up in
:mod:`core.iam.events.handlers`). Adding an ``EventStep`` here is the
only change required to register a new IAM handler / event / schema —
delete this file and nothing gets registered.

See: ``docs/architecture/event-flow-tracing.md`` for the rationale.
``tests/unit/test_iam_event_flows.py`` checks each flow is a closed
graph — no dangling ``emits``, exactly one entry event.

Discipline
----------
* All ``event=`` and ``handlers=`` entries are **real Python class
  references**, never strings. Rename or delete a symbol → this module
  fails to import. That is intentional: it prevents silent rot.
* ``emits`` must list every event the step's handlers publish, and each
  emitted event needs its own ``EventStep`` in the same flow (enforced
  by the sanity test) — otherwise the flow map lies about the story.
"""

from __future__ import annotations

from typing import Final

from foundation.messaging.events.event_handler import EventStep

from iam.auth.auth_events import (
    TenantCreatedEvent,
    UserDirectoryCreatedEvent,
    UserRegisteredEvent,
)
from iam.auth.handlers.init_handlers import (
    IamWelcomeAccountNotificationHandler,
    InternalUserSetupHandler,
    TenantSetupEventHandler,
)

# ---------------------------------------------------------------------------
# Flow: User Onboarding
# ---------------------------------------------------------------------------
# Starts when an external identity provider (e.g. Keycloak) signals that
# a user directory entry has been created, fans out into a per-tenant
# bootstrap and a welcome notification.
#
#   UserDirectoryCreatedEvent
#        │
#        ▼
#   InternalUserSetupHandler
#        │ emits ──────────────┐
#        │                     │
#        ▼                     ▼
#   UserRegisteredEvent   TenantCreatedEvent
#        │                     │
#        ▼                     ▼
#   IamWelcome...Handler   TenantSetupEventHandler
#   (terminal)             (terminal)
# ---------------------------------------------------------------------------

USER_ONBOARDING: Final[tuple[EventStep, ...]] = (
    EventStep(
        event=UserDirectoryCreatedEvent,
        handlers=(InternalUserSetupHandler,),
        emits=(UserRegisteredEvent, TenantCreatedEvent),
        note=(
            'Directory entry created → provision the internal user row '
            'and its owning tenant row, then publish both '
            'UserRegisteredEvent (drives welcome email) and '
            'TenantCreatedEvent (drives tenant bootstrap).'
        ),
    ),
    EventStep(
        event=UserRegisteredEvent,
        handlers=(IamWelcomeAccountNotificationHandler,),
        emits=(),
        note='Send welcome email to the newly registered user. Terminal step.',
    ),
    EventStep(
        event=TenantCreatedEvent,
        handlers=(TenantSetupEventHandler,),
        emits=(),
        note=(
            'Bootstrap per-tenant resources (default roles, billing '
            'placeholder, etc.) once the tenant row exists. Terminal step.'
        ),
    ),
)


# ---------------------------------------------------------------------------
# Registry of all IAM flows
# ---------------------------------------------------------------------------

IAM_ALL_FLOWS: Final[dict[str, tuple[EventStep, ...]]] = {
    'user_onboarding': USER_ONBOARDING,
}
