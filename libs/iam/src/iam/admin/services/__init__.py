from ._admin import AdminService


def get_admin_service() -> AdminService:
    """Return a new instance of :class:`AdminService`."""
    return AdminService()


__all__ = ['get_admin_service', 'AdminService']
