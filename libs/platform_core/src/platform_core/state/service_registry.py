import logging
from logging import Logger
from typing import Any, Callable, Dict, Optional, Type, cast

# ============================================================================
# SERVICE LOCATOR IMPLEMENTATION
# ============================================================================


class ServiceRegistry:
    """
    Simple service locator implementation.
    The purpose of this service locator is to provide a simple way to register and retrieve services in the application.
    It supports both singleton and transient services. For singleton services, the same instance will be returned on every request. For transient services, a new instance will be created on each request.
    Usage:
    ```python
    # Registering a service
    service_locator.register(IMyService, MyServiceImplementation, singleton=True)
    # Retrieving a service
    my_service = service_locator.get(IMyService)
    ```
    """

    _logger: Optional[Logger] = None

    @property
    def logger(self):
        if self._logger is None:
            self._logger = logging.getLogger(__name__)
        return self._logger

    def __init__(self):
        self._services: Dict[Type, Any] = {}
        self._singletons: Dict[Type, Any] = {}

    def register[T](
        self,
        interface_type: Type[T],
        implementation: T | Callable[[], T],
        singleton: bool = True,
    ) -> T:
        """Register service implementation."""
        if not singleton and not callable(implementation):
            raise ValueError(
                f'Transient service {interface_type.__name__} requires a callable factory, not an instance. '
                'Pass a class or factory function, or use singleton=True.'
            )
        self._services[interface_type] = (implementation, singleton)
        # Clear stale singleton so re-registration takes effect immediately
        self._singletons.pop(interface_type, None)
        # If singleton and already an instance, cache it immediately — no lazy init needed
        if singleton and not callable(implementation):
            self._singletons[interface_type] = implementation
        return cast(T, implementation)

    def get[T](self, interface_type: Type[T], raise_if_not_found: bool = True) -> T:
        """Get service instance."""
        if interface_type not in self._services:
            if raise_if_not_found:
                raise ValueError(f'Service {interface_type.__name__} not registered')
            else:
                return None  # type: ignore

        implementation, is_singleton = self._services[interface_type]

        if is_singleton:
            if interface_type not in self._singletons:
                # Only factories reach here; instances are cached eagerly at register()
                self._singletons[interface_type] = implementation()
            return cast(T, self._singletons[interface_type])
        else:
            return cast(T, implementation())

    def get_all_running(self) -> Dict[Type, Any]:
        """
        Get all currently running service instances.
        Ignored if the serivce is not instantiated yet (for singleton) or not callable (for transient).
        """
        running_services = {}
        for interface_type, (implementation, is_singleton) in self._services.items():
            if is_singleton:
                if interface_type in self._singletons:
                    running_services[interface_type] = self._singletons[interface_type]
            else:
                if not callable(implementation):
                    running_services[interface_type] = implementation
                else:
                    self.logger.debug(
                        f'Skipping transient service {interface_type.__name__} as it is callable and not instantiated yet.'
                    )
        return running_services

    def has[T](self, interface_type: Type[T]) -> bool:
        """Check if service is registered."""
        return interface_type in self._services

    async def shutdown_all(self) -> None:
        """
        Call stop()/close()/aclose() on all running singleton instances that support it.
        Safe to call even if a service has no shutdown method.
        """
        import inspect

        for interface_type, instance in self.get_all_running().items():
            for method_name in ('stop', 'close', 'aclose'):
                method = getattr(instance, method_name, None)
                if callable(method):
                    try:
                        result = method()
                        if inspect.isawaitable(result):
                            await result
                        self.logger.info(
                            f'⏹️ {interface_type.__name__}.{method_name}() completed'
                        )
                    except Exception as e:
                        self.logger.error(
                            f'Error shutting down {interface_type.__name__}: {e}'
                        )
                    break  # only call the first matching method


# ============================================================================
# GLOBAL SERVICE LOCATOR
# ============================================================================

_service_registry: Optional[ServiceRegistry] = None


def get_service_registry() -> ServiceRegistry:
    """Get global service locator instance."""
    global _service_registry
    if _service_registry is None:
        _service_registry = ServiceRegistry()
    return _service_registry


def register_service[T](
    interface_type: Type[T],
    implementation: T | type[T],
    singleton: bool = True,
) -> T:
    """Register service in global locator."""
    return get_service_registry().register(interface_type, implementation, singleton)


def get_service[T](interface_type: Type[T], raise_if_not_found: bool = True) -> T:
    """Get service from global locator."""
    return get_service_registry().get(interface_type, raise_if_not_found)
