from typing import TYPE_CHECKING

from foundation.state import register_service

if TYPE_CHECKING:
    from foundation.resiliant.types import ResiliantServiceFactoryT

# def register_service(svc: type, service: Any, singleton: bool = True,):
#     """
#     A convenience method to register a service in the service registry.
#     """
#     from foundation.state.service_registry import (
#         register_service as _register_service,
#     )

#     _register_service(svc, service, singleton=singleton)


def register_resiliant_factory(factory: 'ResiliantServiceFactoryT'):
    """
    Register a resiliant service factory.
    """
    from foundation.messaging.types import IMessageRoutingService
    from foundation.resiliant.dlq import IDLQService
    from foundation.resiliant.idempotency import IIdempotencyService
    from foundation.resiliant.outbox import IOutboxService
    from foundation.resiliant.types import ResiliantServiceFactoryT

    register_service(IOutboxService, factory.get_outbox_service())
    register_service(IDLQService, factory.get_dlq_service())
    register_service(IIdempotencyService, factory.get_idempotency_service())
    register_service(IMessageRoutingService, factory.get_message_routing_service())
    register_service(ResiliantServiceFactoryT, factory)
