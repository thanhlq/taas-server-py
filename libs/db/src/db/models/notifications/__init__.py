"""Platform notification tables ``taas_notification*`` (one inbox for every app; ``ews.notifications``)."""

from ._notifications import (
    Notification,
    NotificationDelivery,
    NotificationPreference,
    NotificationUserSettings,
)

__all__ = [
    'Notification',
    'NotificationDelivery',
    'NotificationPreference',
    'NotificationUserSettings',
]
