""" """

import os
from typing import Any

from foundation import BaseService
from foundation.storage.providers.fs.fs_paths import FSPaths
from foundation.storage.types import TemplateStorageServiceT
from foundation.template.render import render_template
from foundation.utils.io import join_paths


class FSTemplateStorage(BaseService, TemplateStorageServiceT):
    """File system-based template storage service implementation."""

    def __init__(self, template_directory: str | None = None):
        super().__init__()
        if template_directory is None:
            template_directory = FSPaths.get_templates_dir()
            if not os.path.exists(template_directory):
                self.logger.warning(
                    f'Creating template directory at {template_directory}'
                )
                os.makedirs(template_directory)
            else:
                self.logger.info(
                    f'📂 Using existing template directory at {template_directory}'
                )
        self.template_directory = template_directory

    async def get_template(self, template_name: str) -> str:
        """Retrieve template content by name."""
        template_path = join_paths(self.template_directory, template_name)

        try:
            with open(template_path, encoding='utf-8') as file:
                content = file.read()
            return content
        except FileNotFoundError:
            m = f"Template '{template_name}' not found in '{template_path}'"
            self.logger.error(m)
            raise ValueError(m)

    async def save_template(self, template_name: str, content: str) -> None:
        """Save or update template content."""
        template_path = os.path.join(self.template_directory, template_name)

        # Ensure parent directory exists
        parent_dir = os.path.dirname(template_path)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)

        with open(template_path, 'w', encoding='utf-8') as file:
            file.write(content)

    async def delete_template(self, template_name: str) -> None:
        """Delete a template by name."""
        template_path = os.path.join(self.template_directory, template_name)
        try:
            os.remove(template_path)
        except FileNotFoundError:
            raise ValueError(
                f"Template '{template_name}' not found in '{self.template_directory}'"
            )

    async def list_templates(self) -> list[str]:
        """List all available template names."""
        templates = []

        for root, _dirs, files in os.walk(self.template_directory):
            for file in files:
                # Get relative path from template directory
                full_path = os.path.join(root, file)
                relative_path = os.path.relpath(full_path, self.template_directory)
                templates.append(relative_path)

        return sorted(templates)

    async def render_template(self, template_str: str, context: dict[str, Any]) -> str:
        return await render_template(template_str, context)
