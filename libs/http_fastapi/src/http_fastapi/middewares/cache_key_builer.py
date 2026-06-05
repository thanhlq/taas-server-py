# For example, if you wanted to use the request method, URL and query string as a
# cache key instead of the function identifier you could use:

# def request_key_builder(
#     func,
#     namespace: str = "",
#     *,
#     request: Request = None,
#     response: Response = None,
#     *args,
#     **kwargs,
# ):
#     return ":".join([
#         namespace,
#         request.method.lower(),
#         request.url.path,
#         repr(sorted(request.query_params.items()))
#     ])
# from fastapi import Request, Response


# Based on request url, method, path
# Not working
from starlette.requests import Request
def request_key_builder(
    func,
    namespace: str = '',
    request: Request = None,
    response: Response = None,
    *args,
    **kwargs,
):
    return ':'.join(
        [
            namespace,
            request.method.lower(),
            request.url.path,
            repr(sorted(request.query_params.items())),
        ]
    )


# @see https://medium.com/@drv.muk/understanding-fastapi-caching-and-asynchronous-processing-77608b0dd474
def custom_cache_key_builder(
    func, namespace: str, request: Request, *args, **kwargs
):
    # key = f"{namespace}:{default_key_builder(func, *args, **kwargs)}"
    # print("Positional arguments (*args):", args)
    print('Keyword arguments (**kwargs):', kwargs)
    # {'request': None, 'response': None, 'args': (), 'kwargs': {'session': <sqlmodel.orm.session.Session object at 0x11a876d50>,
    # 'opts': {'q': None, 'offset': 0, 'limit': 100}}}

    key = f'{namespace}:'

    if request is not None:
        key += f'{request.url.path}:'

    opts = kwargs.get('kwargs').get('opts')

    if opts is not None:
        key += str(opts)

    # key = f"{namespace}:{default_key_builder(func, *args, query)}"
    print(f'cache-key: {key}')
    # return ":".join([
    #     namespace,
    #     kwargs["opts"]
    # ])
    return key


