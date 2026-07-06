"""
Commonn core python utils for the platform.
"""
def is_python_3_10_or_lower() -> bool:
    """Check if the current Python version is 3.10 or lower."""
    import sys

    return sys.version_info < (3, 11)


def iscoroutinefunction(func):
    """A more robust version of inspect.iscoroutinefunction that can handle
    decorated functions and classes.
    """
    import inspect

    if inspect.iscoroutinefunction(func):
        return True
    # Check for common attributes that indicate a coroutine function
    # if hasattr(func, '__wrapped__'):
    #     return iscoroutinefunction(func.__wrapped__)
    # if hasattr(func, '__func__'):
    #     return iscoroutinefunction(func.__func__)
    # if hasattr(func, '__call__'):
    #     return iscoroutinefunction(func.__call__)
    return False
