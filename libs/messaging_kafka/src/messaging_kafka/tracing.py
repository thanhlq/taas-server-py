# region Tracing Init
async def async_produce_hook(span, args, kwargs):
    # logger = LogFactory().get_logger(__name__)
    # logger.debug(f'📨 🪝 Kafka produce hook called {args} {kwargs}')
    if span and span.is_recording():
        span.set_attribute(
            'custom_user_attribute_from_async_response_hook', 'some-value 1'
        )


async def async_consume_hook(span, record, args, kwargs):
    # logger = LogFactory().get_logger(__name__)
    # logger.debug(
    #     f'📨 🪝 Kafka consume hook called {record}, args {args}, kwargs {kwargs}'
    # )
    if span and span.is_recording():
        span.set_attribute(
            'custom_user_attribute_from_consume_hook', 'some-value consume 1'
        )
