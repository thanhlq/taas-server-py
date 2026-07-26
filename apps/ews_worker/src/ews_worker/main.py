"""
🚀 Main entry point for the EWS worker.

Run with::

    uv run python -m ews_worker
"""

from __future__ import annotations

import asyncio

from foundation.observability.types import InstrumentSettings

# Importing bootstrap first configures the environment and logging.
from .bootstrap import settings  # noqa: F401


def main() -> None:
    """Build and run the worker until interrupted."""
    from .worker import EwsWorker

    async def _run() -> None:
        worker = EwsWorker()

        from foundation.observability.tracing_factory import TracingFactory
        ins_settings: InstrumentSettings = worker.config.get_instrumentation_settings()
        TracingFactory().init_instrumentation(ins_settings)

        await worker.initialize_worker_tasks()
        await worker.main()

    asyncio.run(_run())


if __name__ == '__main__':
    main()
