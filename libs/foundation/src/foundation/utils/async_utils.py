"""
The purpose of this module is to provide utilities for running async code from sync contexts, and vice versa,
without causing issues with event loops.
"""

import asyncio
import concurrent.futures
import os
import threading
from typing import Any, Coroutine, Optional, TypeVar

T = TypeVar('T')

WORKER_LOOP_THREAD_NAME = 'async-worker-loop'

_worker_loop: Optional[asyncio.AbstractEventLoop] = None
_worker_thread: Optional[threading.Thread] = None
_worker_pid: Optional[int] = None
_worker_lock = threading.Lock()


def get_worker_loop() -> asyncio.AbstractEventLoop:
    """
    Return the process-wide worker event loop, starting its thread on first use.

    The loop runs in a daemon thread and is never closed while the process lives, so
    resources created on it (aiokafka clients, SSL transports, futures) remain valid
    between calls. Use :func:`shutdown_worker_loop` to tear it down explicitly.
    """
    global _worker_loop, _worker_thread, _worker_pid

    pid = os.getpid()
    loop = _worker_loop
    if loop is not None and not loop.is_closed() and _worker_pid == pid:
        return loop

    with _worker_lock:
        # Re-check: another thread may have created the loop while we waited.
        # A pid mismatch means we are in a forked child, where the inherited
        # loop's thread no longer exists — abandon it and build a fresh one.
        if (
            _worker_loop is not None
            and not _worker_loop.is_closed()
            and _worker_pid == pid
        ):
            return _worker_loop

        loop = asyncio.new_event_loop()
        started = threading.Event()

        def _run() -> None:
            asyncio.set_event_loop(loop)
            loop.call_soon(started.set)
            loop.run_forever()

        thread = threading.Thread(target=_run, daemon=True, name=WORKER_LOOP_THREAD_NAME)
        thread.start()
        started.wait()

        _worker_loop, _worker_thread, _worker_pid = loop, thread, pid
        return loop


def is_worker_loop(loop: Optional[asyncio.AbstractEventLoop]) -> bool:
    """Return ``True`` when *loop* is the live worker loop."""
    return loop is not None and loop is _worker_loop and not loop.is_closed()


def run_async_sync(coro: Coroutine[Any, Any, T], timeout: float | None = None) -> T:
    """
    Run *coro* on the worker loop from synchronous code, blocking until it completes.
    """
    loop = get_worker_loop()

    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    if running_loop is loop:
        coro.close()
        raise RuntimeError(
            'run_async_sync() was called from the worker loop itself, which would '
            'deadlock. Await the coroutine directly instead.'
        )

    future = asyncio.run_coroutine_threadsafe(coro, loop)
    try:
        return future.result(timeout)
    except concurrent.futures.TimeoutError as exc:
        future.cancel()
        raise TimeoutError(f'run_async_sync timed out after {timeout}s') from exc


async def await_on_loop(
    coro: Coroutine[Any, Any, T],
    loop: asyncio.AbstractEventLoop,
    timeout: float | None = None,
) -> T:
    """
    Await *coro* on another (still-running) *loop* from async code.

    Used to drive a resource on the loop that owns it — e.g. closing an aiokafka admin
    client created on the worker loop from the application's main loop. The calling loop
    is not blocked: the cross-loop future is awaited, not waited on.

    Args:
        coro: Coroutine to run on *loop*.
        loop: A running event loop, different from the caller's.
        timeout: Seconds to wait, or ``None`` to wait indefinitely.

    Raises:
        RuntimeError: When *loop* is closed.
        asyncio.TimeoutError: When *timeout* elapses first.
    """
    if loop.is_closed():
        coro.close()
        raise RuntimeError('Target event loop is closed.')

    future = asyncio.wrap_future(asyncio.run_coroutine_threadsafe(coro, loop))
    if timeout is None:
        return await future
    return await asyncio.wait_for(future, timeout)


def shutdown_worker_loop(timeout: float | None = 5.0) -> None:
    """
    Stop the worker loop and join its thread.

    If the thread is still alive after ``timeout`` (a callback is wedged on the
    loop), the loop is intentionally leaked rather than closed underneath a
    live thread — ``loop.close()`` on a running loop raises. The module globals
    are cleared either way, so a later ``get_worker_loop()`` builds a fresh
    loop; the leaked one exits once its blocking callback returns (``stop()``
    is already queued) and merely stays un-closed until process exit.
    """
    global _worker_loop, _worker_thread, _worker_pid

    with _worker_lock:
        loop, thread = _worker_loop, _worker_thread
        _worker_loop, _worker_thread, _worker_pid = None, None, None

    if loop is None:
        return

    if not loop.is_closed():
        loop.call_soon_threadsafe(loop.stop)
    if thread is not None:
        thread.join(timeout)
        if thread.is_alive():
            # join() timed out — the loop is still running run_forever(), and
            # close() on a running loop raises RuntimeError. Leave it for the OS
            # to reclaim rather than crashing the shutdown path.
            return
    if not loop.is_closed():
        loop.close()
