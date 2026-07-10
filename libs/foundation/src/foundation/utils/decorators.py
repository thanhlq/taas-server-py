

def empty_decorator(func_or_class):
    """
    An empty decorator that does nothing, used when tracing/auth/authz/... is disabled.

    Accepts both functions and classes with any number of arguments, and returns them unchanged.

    Example usage:

        - @empty_decorator
        - @empty_decorator()
        - @empty_decorator(arg1=value1, arg2=value2)
    """
    return func_or_class
