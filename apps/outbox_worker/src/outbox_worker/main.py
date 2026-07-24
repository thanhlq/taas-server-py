"""
🚀 Main entry point for the outbox worker.

Run with::

    uv run --package outbox_worker python -m outbox_worker
"""

from __future__ import annotations

import asyncio

# Importing bootstrap first configures the environment and logging.
from .bootstrap import settings  # noqa: F401


def main() -> None:
    """Build and run the outbox worker until interrupted."""
    from .worker import OutboxWorker

    async def _run() -> None:
        worker = OutboxWorker()
        await worker.initialize_worker_tasks()
        await worker.main()

    asyncio.run(_run())


if __name__ == '__main__':
    main()
