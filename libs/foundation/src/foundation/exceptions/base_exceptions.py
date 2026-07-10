from __future__ import annotations

from typing import Any

__all__ = ("BaseException", "TaasWarning", "MissingDependencyException", "SerializationException")


class BaseException(Exception):
    """Base exception class from which all Litestar exceptions inherit."""

    detail: str

    def __init__(self, *args: Any, detail: str = "") -> None:
        """Initialize ``BaseException``.

        Args:
            *args: args are converted to :class:`str` before passing to :class:`Exception`
            detail: detail of the exception.
        """
        str_args = [str(arg) for arg in args if arg]
        if not detail:
            if str_args:
                detail, *str_args = str_args
            elif hasattr(self, "detail"):
                detail = self.detail
        self.detail = detail
        super().__init__(*str_args)

    def __repr__(self) -> str:
        if self.detail:
            return f"{self.__class__.__name__} - {self.detail}"
        return self.__class__.__name__

    def __str__(self) -> str:
        return " ".join((*self.args, self.detail)).strip()


class MissingDependencyException(BaseException, ImportError):
    """Missing optional dependency.

    This exception is raised only when a module depends on a dependency that has not been installed.
    """

    def __init__(self, package: str, install_package: str | None = None, extra: str | None = None) -> None:
        super().__init__(
            f"Package {package!r} is not installed but required. You can install it by running "
            f"`pip install 'litestar[{extra or install_package or package}]'` to install litestar with the required extra "
            f"or 'pip install {install_package or package}' to install the package separately"
        )


class SerializationException(BaseException):
    """Encoding or decoding of an object failed."""


class TaasWarning(UserWarning):
    """Base class for Taas warnings"""
