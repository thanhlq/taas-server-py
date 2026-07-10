""" All logging should use this module to get a logger, so that it will be configured correctly. """
import logging

from ..observability.factory import LogFactory, logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance by name."""
    return LogFactory().get_logger(name)


__all__ = ['get_logger', 'logger']
