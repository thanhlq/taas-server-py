from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal



__all__ = ("CompressionConfig",)


@dataclass
class CompressionConfig:
    """Configuration for response compression.

    To enable response compression, pass an instance of this class to the :class:`Litestar <.app.Litestar>` constructor
    using the ``compression_config`` key.
    """

    backend: Literal["gzip", "brotli"] | str
    """The backend to use.

    If the value given is `gzip` or `brotli`, then the builtin gzip and brotli compression is used.
    """
    minimum_size: int = field(default=500)
    """Minimum response size (bytes) to enable compression, affects all backends."""
    gzip_compress_level: int = field(default=9)
    """Range ``[0-9]``, see :doc:`python:library/gzip`."""
    brotli_quality: int = field(default=5)
    """Range ``[0-11]``, Controls the compression-speed vs compression-density tradeoff.

    The higher the quality, the slower the compression.
    """
    brotli_mode: Literal["generic", "text", "font"] = "text"
    """``MODE_GENERIC``, ``MODE_TEXT`` (for UTF-8 format text input, default) or ``MODE_FONT`` (for WOFF 2.0)."""
    brotli_lgwin: int = field(default=22)
    """Base 2 logarithm of size.

    Range is 10 to 24. Defaults to 22.
    """
    brotli_lgblock: Literal[0, 16, 17, 18, 19, 20, 21, 22, 23, 24] = 0
    """Base 2 logarithm of the maximum input block size.

    Range is ``16`` to ``24``. If set to ``0``, the value will be set based on the quality. Defaults to ``0``.
    """
    brotli_gzip_fallback: bool = True
