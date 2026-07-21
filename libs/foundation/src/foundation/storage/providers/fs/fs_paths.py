import os
import sys
from pathlib import Path
from typing import Optional

from foundation.cli import cli

from .fs_constants import CONFIG_CONSTANTS


class FSPaths:
    _root_dir: str | None = None

    def __init__(self, root_dir: Optional[str] = None):
        if root_dir is None:
            self._root_dir = self.find_app_root()
        else:
            self._root_dir = root_dir

    @staticmethod
    def join_paths(path1: str, path2: str) -> str:
        return os.path.join(path1, path2)

    @staticmethod
    def find_app_root(path: Path | None = None) -> str:
        """Get the application root directory."""
        if FSPaths._root_dir is not None:
            return FSPaths._root_dir

        python_path = os.environ.get('PYTHONPATH')
        if (python_path is not None) and (python_path != ''):
            return python_path

        _p = (
            path
            or Path(
                __file__
            ).parent.parent.parent.parent.parent.parent.parent.parent.resolve()
        )
        file_path = str(_p)
        sys.path.append(str(file_path))
        FSPaths._root_dir = file_path
        cli.info_formal('Application Root Directory', file_path)
        return FSPaths._root_dir

    @staticmethod
    def get_app_dir(relative_path: Optional[str]) -> str:
        if relative_path:
            return FSPaths.join_paths(FSPaths.find_app_root(), relative_path)
        return FSPaths.find_app_root()

    @staticmethod
    def get_config_dir(relative_path: Optional[str] = None) -> str:
        if relative_path:
            return FSPaths.join_paths(
                f'{FSPaths.find_app_root()}/{CONFIG_CONSTANTS.CONFIG_DIR}',
                relative_path,
            )
        return FSPaths.join_paths(FSPaths.find_app_root(), CONFIG_CONSTANTS.CONFIG_DIR)

    @staticmethod
    def get_logs_dir(relative_path: Optional[str] = None) -> str:
        if relative_path:
            return FSPaths.join_paths(
                f'{FSPaths.find_app_root()}/{CONFIG_CONSTANTS.LOGS_DIR}',
                relative_path,
            )
        return FSPaths.join_paths(FSPaths.find_app_root(), CONFIG_CONSTANTS.LOGS_DIR)

    @staticmethod
    def get_data_dir(relative_path: Optional[str] = None) -> str:
        if relative_path:
            return FSPaths.join_paths(
                f'{FSPaths.find_app_root()}/{CONFIG_CONSTANTS.DATA_DIR}',
                relative_path,
            )
        return FSPaths.join_paths(FSPaths.find_app_root(), CONFIG_CONSTANTS.DATA_DIR)

    @staticmethod
    def get_temp_dir(relative_path: Optional[str] = None) -> str:
        if relative_path:
            return FSPaths.join_paths(
                f'{FSPaths.find_app_root()}/{CONFIG_CONSTANTS.TEMP_DIR}',
                relative_path,
            )
        return FSPaths.join_paths(FSPaths.find_app_root(), CONFIG_CONSTANTS.TEMP_DIR)

    @staticmethod
    def get_backup_dir(relative_path: Optional[str] = None) -> str:
        if relative_path:
            return FSPaths.join_paths(
                f'{FSPaths.find_app_root()}/{CONFIG_CONSTANTS.BACKUP_DIR}',
                relative_path,
            )
        return FSPaths.join_paths(FSPaths.find_app_root(), CONFIG_CONSTANTS.BACKUP_DIR)

    @staticmethod
    def get_exports_dir(relative_path: Optional[str] = None) -> str:
        if relative_path:
            return FSPaths.join_paths(
                f'{FSPaths.find_app_root()}/{CONFIG_CONSTANTS.EXPORTS_DIR}',
                relative_path,
            )
        return FSPaths.join_paths(FSPaths.find_app_root(), CONFIG_CONSTANTS.EXPORTS_DIR)

    @staticmethod
    def get_imports_dir(relative_path: Optional[str] = None) -> str:
        if relative_path:
            return FSPaths.join_paths(
                f'{FSPaths.find_app_root()}/{CONFIG_CONSTANTS.IMPORTS_DIR}',
                relative_path,
            )
        return FSPaths.join_paths(FSPaths.find_app_root(), CONFIG_CONSTANTS.IMPORTS_DIR)

    @staticmethod
    def get_plugins_dir(relative_path: Optional[str] = None) -> str:
        if relative_path:
            return FSPaths.join_paths(
                f'{FSPaths.find_app_root()}/{CONFIG_CONSTANTS.PLUGINS_DIR}',
                relative_path,
            )
        return FSPaths.join_paths(FSPaths.find_app_root(), CONFIG_CONSTANTS.PLUGINS_DIR)

    @staticmethod
    def get_themes_dir(relative_path: Optional[str] = None) -> str:
        if relative_path:
            return FSPaths.join_paths(
                f'{FSPaths.find_app_root()}/{CONFIG_CONSTANTS.THEMES_DIR}',
                relative_path,
            )
        return FSPaths.join_paths(FSPaths.find_app_root(), CONFIG_CONSTANTS.THEMES_DIR)

    @staticmethod
    def get_resource_dir(relative_path: Optional[str] = None) -> str:
        if relative_path:
            return FSPaths.join_paths(
                f'{FSPaths.find_app_root()}/{CONFIG_CONSTANTS.RESOURCE_DIR}',
                relative_path,
            )
        return FSPaths.join_paths(
            FSPaths.find_app_root(), CONFIG_CONSTANTS.RESOURCE_DIR
        )

    @staticmethod
    def get_templates_dir(relative_path: Optional[str] = None) -> str:
        if relative_path:
            return FSPaths.join_paths(
                f'{FSPaths.find_app_root()}/{CONFIG_CONSTANTS.TEMPLATES_DIR}',
                relative_path,
            )
        return FSPaths.join_paths(
            FSPaths.find_app_root(), CONFIG_CONSTANTS.TEMPLATES_DIR
        )

    @staticmethod
    def get_email_templates_dir(relative_path: Optional[str] = None) -> str:
        if relative_path:
            return FSPaths.join_paths(
                f'{FSPaths.find_app_root()}/{CONFIG_CONSTANTS.EMAIL_TEMPLATES_DIR}',
                relative_path,
            )
        return FSPaths.join_paths(
            FSPaths.find_app_root(), CONFIG_CONSTANTS.EMAIL_TEMPLATES_DIR
        )
