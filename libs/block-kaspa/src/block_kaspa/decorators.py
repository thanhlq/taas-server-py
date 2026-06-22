""" Specific decorators for Kaspa client functions. """
import asyncio
import decimal

import functools
import time
from functools import wraps
from typing import Optional


def retry(max_retries=10):
    def decorator_retry(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            for retry_count in range(max_retries):
                try:
                    result = await func(*args, **kwargs)
                    return result  # If successful, return the result
                except Exception as e:
                    print(f'Retry {retry_count + 1}/{max_retries} - Error: {e}')
                    if retry_count < max_retries - 1:
                        # Sleep before the next retry (you can adjust this as needed)
                        await asyncio.sleep(retry_count + 1)
                    else:
                        raise  # If max retries reached, raise the exception

        return wrapper

    return decorator_retry


def retry_sync(max_retries=10, non_retryable: tuple = ()):
    def decorator_retry(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for retry_count in range(max_retries):
                try:
                    result = func(*args, **kwargs)
                    return result  # If successful, return the result
                except non_retryable:
                    raise
                except Exception as e:
                    print(f'Retry {retry_count + 1}/{max_retries} - Error: {e}')
                    if retry_count < max_retries - 1:
                        # Sleep before the next retry (you can adjust this as needed)
                        time.sleep(retry_count + 1)
                    else:
                        raise  # If max retries reached, raise the exception

        return wrapper

    return decorator_retry


def ensure_int_amount(func):
    """Decorator to ensure 'amount' parameter is converted to int"""

    @wraps(func)
    async def wrapper(self, amount, token: Optional[str] = None):
        # Convert amount to int, handling various types
        if not isinstance(amount, int):
            amount = int(decimal.Decimal(str(amount)))
        return await func(self, amount, token)

    return wrapper
