from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Sequence


@dataclass(frozen=True, slots=True, kw_only=True)
class StorageBucket:
    """Storage bucket configuration."""

    name: str
    """
    Name of the storage bucket.
        - if is 'fs', this is the local path to the directory.
        - if is 's3', this is the S3 bucket name.
    """
    provider: str
    """ Values: 'fs', 's3', 'gcs', 'azure' """

# ============================================================================
# TEMPLATE STORAGE SERVICE INTERFACE
# ============================================================================


class TemplateStorageServiceT(ABC):
    """
    Abstract template storage service interface.
    This interface defines methods for managing templates, including retrieval,
    saving, deletion, and listing of templates.
    """

    @abstractmethod
    async def get_template(self, template_name: str) -> str:
        """Retrieve template content by name."""
        pass

    @abstractmethod
    async def save_template(self, template_name: str, content: str) -> None:
        """Save or update template content."""
        pass

    @abstractmethod
    async def delete_template(self, template_name: str) -> None:
        """Delete a template by name."""
        pass

    @abstractmethod
    async def list_templates(self) -> Sequence[str]:
        """List all available template names."""
        pass

    @abstractmethod
    async def render_template(self, template_str: str, context: dict[str, Any]) -> str: ...
