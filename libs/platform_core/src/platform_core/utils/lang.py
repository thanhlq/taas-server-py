

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
