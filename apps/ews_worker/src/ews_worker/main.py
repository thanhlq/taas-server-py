"""
🚀 Main entry point for the EWS worker.

Run with::

    uv run python -m ews_worker
"""

from __future__ import annotations

import asyncio

# Importing bootstrap first configures the environment and logging.
from .bootstrap import settings  # noqa: F401


def main() -> None:
    """Build and run the worker until interrupted."""
    from .worker import EwsWorker

    async def _run() -> None:
        worker = EwsWorker()
        await worker.initialize_worker_tasks()
        await worker.main()

    asyncio.run(_run())


if __name__ == '__main__':
    main()
