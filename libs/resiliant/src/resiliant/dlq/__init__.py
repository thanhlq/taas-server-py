"""Dead-letter queue on Postgres (twin of ``@taas/resiliant/dlq``).

Contracts (statuses, transitions, config) are in ``foundation.resiliant.dlq``;
tables in ``resiliant.models.dlq``.
"""

from .dlq_repository import DLQRepository
from .dlq_service import (
    DeadLetterHandler,
    DLQHandlerRegistry,
    DLQRetryProcessor,
    DLQRetryResult,
    DLQService,
)
from .dlq_settings import DlqSettings, get_dlq_config, parse_handler_limits

__all__ = [
    "DLQHandlerRegistry",
    "DLQRepository",
    "DLQRetryProcessor",
    "DLQRetryResult",
    "DLQService",
    "DeadLetterHandler",
    "DlqSettings",
    "get_dlq_config",
    "parse_handler_limits",
]
