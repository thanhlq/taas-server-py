# https://medium.com/@rspatel031/a-comprehensive-guide-to-the-thread-safe-singleton-pattern-in-python-e47682e300da

import threading
from functools import wraps


def singleton(cls):
    """
    Decorator to make a class a singleton while preserving inheritance.
    This is preferred over metaclass approach to avoid metaclass conflicts.
    Thread-safe implementation using Double-Checked Locking.
    """
    instances = {}
    _lock = threading.Lock()
    original_new = cls.__new__
    original_init = cls.__init__

    @wraps(cls.__new__)
    def singleton_new(cls_inner, *args, **kwargs):
        if cls_inner not in instances:
            with _lock:
                if cls_inner not in instances:
                    # Use the original __new__ method
                    if original_new is object.__new__:
                        instance = original_new(cls_inner)
                    else:
                        instance = original_new(cls_inner, *args, **kwargs)
                    instances[cls_inner] = instance
        return instances[cls_inner]

    @wraps(cls.__init__)
    def singleton_init(self, *args, **kwargs):
        with _lock:
            if not getattr(self, '_singleton_initialized', False):
                original_init(self, *args, **kwargs)
                self._singleton_initialized = True

    cls.__new__ = singleton_new
    cls.__init__ = singleton_init
    return cls
