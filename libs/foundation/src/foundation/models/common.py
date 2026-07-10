from foundation.serialization import BaseModel
from enum import IntEnum


class ObjectScope(IntEnum):
    """
    Defines the scope of an object in the system.
    I.e. a tag can be applied to a system-wide object, a tenant, an organization, a team, a project, or a specific object instance.
    """

    SYSTEM = 0
    TENANT = 1
    ORGANIZATION = 2
    TEAM = 3
    PROJECT = 4
    OBJECT = 5
    """ Specific object instance (e.g., a particular document, task, or resource). """


class ObjectStatus(IntEnum):
    """
    Defines the status of an object in the system.
    """

    DRAFT = 0
    ACTIVE = 1
    INACTIVE = 2
    DELETED = 3


class Tag(BaseModel):
    """
    Represents a tag that can be applied to various objects in the system.
    Tags can be used for categorization, filtering, and access control.

    Tag can be applied accross tenant objects, or can be scoped to a specific tenant, organization, team, project, or object instance.
    """

    id: str

    name: str
    """The name of the tag."""

    description: str | None = None
    """An optional description of the tag."""

    slug: str | None = None

    color: str | None = None

    icon: str | None = None

    status: ObjectStatus = ObjectStatus.ACTIVE

    scope: ObjectScope = ObjectScope.TENANT
    """The scope of the tag, indicating where it can be applied."""

    tenant_id: str | None = None

    project_id: str | None = None

    parent_id: str | None = None
    """The ID of the parent tag, if this tag is a child of another tag."""

    entity_type: str | None = None
    """The type of entity this tag is associated with (e.g., 'project', 'task')."""

    entity_id: str | None = None

    assigned_by: str | None = None
    """The ID of the user who assigned the tag."""

    created_at: str | None = None
    """The timestamp when the tag was created."""

    updated_at: str | None = None
    """The timestamp when the tag was last updated."""
