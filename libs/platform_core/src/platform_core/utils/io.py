import os
from pathlib import Path


def join_paths(path1: str, path2: str) -> str:
    """Join multiple paths into a single path, handling OS-specific separators."""
    return os.path.join(path1, path2)


def is_file_exists(file_path: str) -> bool:
    """Check if a file exists at the given path."""
    return os.path.isfile(file_path)


def is_relative_path(path: str) -> bool:
    """Check if the given path is a relative path."""
    return not os.path.isabs(path)


def get_runtime_directory() -> str:
    """Get the current runtime directory."""
    return os.getcwd()


def get_parent_directory(path: str) -> str:
    """Get the parent directory of the given path."""
    return str(Path(path).parent)


def user_home_directory() -> str:
    """Get the user's home directory."""
    return str(Path.home())
