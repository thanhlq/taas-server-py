"""

See detailed documentation in libs/foundation/src/foundation/http/docs/REST_CLIENT.md

A convenient, framework-agnostic REST client.

This module provides :class:`CommonRestClient`, a small but complete REST client
built on top of :mod:`httpx`. It is designed to be:

* **Convenient** -- one method per verb (``get``/``post``/``put``/``patch``/
  ``delete``/``head``/``options``) plus a generic :meth:`CommonRestClient.request`.
* **Batteries-included for auth** -- pluggable :class:`Auth` strategies for the
  most common schemes: :class:`BearerAuth`, :class:`ApiKeyAuth`,
  :class:`BasicAuth` and :class:`HeaderAuth`.
* **Decoupled from the HTTP library** -- callers only ever see the neutral
  :class:`RestResponse` and the :class:`RestTransport` protocol. The default
  transport uses ``httpx`` (:class:`HttpxRestTransport`), but it can be swapped
  for any other backend (``aiohttp``, ``requests`` in a thread, a fake for
  tests, ...) without touching call sites.

Quick start
-----------
::

    from foundation.http.rest_client import CommonRestClient, BearerAuth

    async with CommonRestClient(
        "https://api.example.com",
        auth=BearerAuth("my-token"),
        default_headers={"Accept": "application/json"},
    ) as client:
        res = await client.get("/users", params={"page": 1})
        res.raise_for_status()
        users = res.json()

        created = await client.post("/users", json={"name": "Ada"})
        print(created.status_code, created.json())

Subclassing for a concrete API
------------------------------
::

    class GithubClient(CommonRestClient):
        def __init__(self, token: str) -> None:
            super().__init__("https://api.github.com", auth=BearerAuth(token))

        async def get_repo(self, owner: str, repo: str) -> dict:
            res = await self.get(f"/repos/{owner}/{repo}")
            res.raise_for_status()
            return res.json()

Swapping the HTTP backend
-------------------------
Provide your own :class:`RestTransport` implementation and pass it in::

    client = CommonRestClient("https://api.example.com", transport=MyAiohttpTransport())

Everything above :meth:`RestTransport.request` -- URL building, auth, header and
param merging, JSON (de)serialization, error handling -- stays identical.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional, Protocol, TypeVar, runtime_checkable

from foundation.http.route import HttpMethod
from foundation.serialization import decode_json, encode_json

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    import httpx

logger: logging.Logger = logging.getLogger(__name__)

T = TypeVar('T')

__all__ = [
    # Auth strategies
    'Auth',
    'NoAuth',
    'BearerAuth',
    'ApiKeyAuth',
    'BasicAuth',
    'HeaderAuth',
    # Response + errors
    'RestResponse',
    'RestClientError',
    'RestConnectionError',
    'RestTimeoutError',
    'RestResponseError',
    # Transport
    'RestTransport',
    'HttpxRestTransport',
    'PoolConfig',
    # Client
    'CommonRestClient',
]


# ---------------------------------------------------------------------------
# Authentication strategies
# ---------------------------------------------------------------------------
class Auth:
    """Base class for authentication strategies.

    An :class:`Auth` contributes credentials to an outgoing request as HTTP
    headers and/or query parameters. Subclasses override :meth:`headers` and/or
    :meth:`params`; the default implementations contribute nothing, so a
    subclass only implements what it needs.

    Implementations should be cheap to call: :meth:`headers`/:meth:`params` are
    invoked once per request, which allows dynamic credentials (for example a
    token that is refreshed in the background) to be picked up automatically.
    """

    def headers(self) -> Mapping[str, str]:
        """Return headers to merge into the request (may be empty)."""
        return {}

    def params(self) -> Mapping[str, Any]:
        """Return query parameters to merge into the request (may be empty)."""
        return {}


class NoAuth(Auth):
    """Explicit "no authentication" strategy.

    Useful as a per-request override to send a single unauthenticated request
    through an otherwise authenticated client::

        await client.get("/public", auth=NoAuth())
    """


class BearerAuth(Auth):
    """``Authorization: Bearer <token>`` authentication.

    Args:
        token: The bearer token, or a zero-argument callable returning the
            current token. A callable is re-invoked on every request, which
            makes it trivial to plug in token rotation/refresh.
        scheme: The authorization scheme. Defaults to ``"Bearer"``; pass e.g.
            ``"Token"`` for APIs that expect ``Authorization: Token <token>``.

    Example::

        BearerAuth("static-token")
        BearerAuth(lambda: token_store.current())  # refreshed token
    """

    def __init__(self, token: str | Callable[[], str], *, scheme: str = 'Bearer') -> None:
        self._token = token
        self._scheme = scheme

    def headers(self) -> Mapping[str, str]:
        raw = self._token
        token = raw if isinstance(raw, str) else raw()
        return {'Authorization': f'{self._scheme} {token}'}


class ApiKeyAuth(Auth):
    """API-key authentication, either as a header or a query parameter.

    Args:
        api_key: The API key value.
        header_name: Header used to carry the key. Ignored when ``query_param``
            is set. Defaults to ``"X-API-Key"``.
        query_param: If provided, the key is sent as this query parameter
            instead of a header (e.g. ``query_param="api_key"``).

    Examples::

        ApiKeyAuth("secret")                       # X-API-Key: secret
        ApiKeyAuth("secret", header_name="apikey") # apikey: secret
        ApiKeyAuth("secret", query_param="api_key")# ?api_key=secret
    """

    def __init__(
        self,
        api_key: str,
        *,
        header_name: str = 'X-API-Key',
        query_param: Optional[str] = None,
    ) -> None:
        self._api_key = api_key
        self._header_name = header_name
        self._query_param = query_param

    def headers(self) -> Mapping[str, str]:
        if self._query_param is not None:
            return {}
        return {self._header_name: self._api_key}

    def params(self) -> Mapping[str, Any]:
        if self._query_param is not None:
            return {self._query_param: self._api_key}
        return {}


class BasicAuth(Auth):
    """HTTP Basic authentication (``Authorization: Basic <base64>``).

    Args:
        username: The user name.
        password: The password.
    """

    def __init__(self, username: str, password: str) -> None:
        raw = f'{username}:{password}'.encode()
        self._value = f'Basic {base64.b64encode(raw).decode("ascii")}'

    def headers(self) -> Mapping[str, str]:
        return {'Authorization': self._value}


class HeaderAuth(Auth):
    """Authentication via arbitrary custom headers.

    A catch-all for schemes not covered by the dedicated strategies, e.g. APIs
    that expect several proprietary headers::

        HeaderAuth({"X-App-Id": "id", "X-App-Secret": "secret"})
    """

    def __init__(self, headers: Mapping[str, str]) -> None:
        self._headers = dict(headers)

    def headers(self) -> Mapping[str, str]:
        return dict(self._headers)


# ---------------------------------------------------------------------------
# Neutral response + error types (no ``httpx`` in the public surface)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RestResponse:
    """A library-agnostic HTTP response.

    Wraps the concrete backend response so callers never depend on ``httpx``
    types directly. This is what every :class:`CommonRestClient` method returns.
    """

    status_code: int
    """The HTTP status code, e.g. ``200``."""

    headers: Mapping[str, str]
    """Response headers. Prefer :meth:`get_header` for case-insensitive lookup."""

    content: bytes
    """The raw response body."""

    url: str
    """The final request URL (after redirects)."""

    method: str
    """The HTTP method used for the request."""

    encoding: str = 'utf-8'
    """Charset used to decode :attr:`content` into :attr:`text`."""

    elapsed_seconds: Optional[float] = None
    """Wall-clock time taken by the request, if the backend reports it."""

    @property
    def text(self) -> str:
        """The response body decoded as text using :attr:`encoding`."""
        return self.content.decode(self.encoding, errors='replace')

    @property
    def is_success(self) -> bool:
        """``True`` for 2xx status codes."""
        return 200 <= self.status_code < 300

    @property
    def is_client_error(self) -> bool:
        """``True`` for 4xx status codes."""
        return 400 <= self.status_code < 500

    @property
    def is_server_error(self) -> bool:
        """``True`` for 5xx status codes."""
        return 500 <= self.status_code < 600

    def get_header(self, name: str, default: Optional[str] = None) -> Optional[str]:
        """Case-insensitively look up a response header."""
        lowered = name.lower()
        for key, value in self.headers.items():
            if key.lower() == lowered:
                return value
        return default

    def json(self, as_type: Optional[type[T]] = None) -> Any:
        """Decode the JSON body.

        Args:
            as_type: Optional target type. When given (a ``dict``/``list`` type,
                a :mod:`msgspec` ``Struct``, a dataclass, ...), the body is
                decoded and validated into that type; otherwise a plain
                ``dict``/``list``/scalar is returned.

        Raises:
            foundation.exceptions.SerializationException: If the body is not
                valid JSON or does not match ``as_type``.
        """
        if as_type is None:
            return decode_json(self.content)
        return decode_json(self.content, as_type)

    def raise_for_status(self) -> RestResponse:
        """Raise :class:`RestResponseError` for 4xx/5xx responses.

        Returns ``self`` on success so it can be chained::

            data = (await client.get("/x")).raise_for_status().json()
        """
        if self.is_client_error or self.is_server_error:
            raise RestResponseError(self)
        return self


class RestClientError(Exception):
    """Base class for all errors raised by :class:`CommonRestClient`."""


class RestConnectionError(RestClientError):
    """A transport-level failure (DNS, connection refused, TLS, ...).

    Wraps the underlying backend exception (available via ``__cause__``) so
    callers can handle failures without importing ``httpx``.
    """


class RestTimeoutError(RestConnectionError):
    """The request exceeded its timeout."""


class RestResponseError(RestClientError):
    """Raised by :meth:`RestResponse.raise_for_status` for 4xx/5xx responses."""

    def __init__(self, response: RestResponse) -> None:
        self.response = response
        super().__init__(
            f'{response.method} {response.url} returned HTTP {response.status_code}'
        )

    @property
    def status_code(self) -> int:
        return self.response.status_code


# ---------------------------------------------------------------------------
# Transport abstraction
# ---------------------------------------------------------------------------
@runtime_checkable
class RestTransport(Protocol):
    """The seam that makes the HTTP backend replaceable.

    Implement this protocol to run :class:`CommonRestClient` on a different HTTP
    library. Everything above :meth:`request` (URL building, auth, header/param
    merging, JSON handling) is backend-independent.
    """

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Mapping[str, str]] = None,
        params: Optional[Mapping[str, Any]] = None,
        content: Optional[bytes] = None,
        data: Optional[Mapping[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> RestResponse:
        """Perform a single HTTP request and return a :class:`RestResponse`.

        Implementations should translate their native connection/timeout errors
        into :class:`RestConnectionError`/:class:`RestTimeoutError`.
        """
        ...

    async def aclose(self) -> None:
        """Release any resources held by the transport (connection pool, ...)."""
        ...


@dataclass(frozen=True)
class PoolConfig:
    """Connection-pool configuration for the default :class:`HttpxRestTransport`.

    Backend-neutral knobs describing how many connections may be opened and kept
    alive for reuse. Pass it to :class:`CommonRestClient` via ``pool=`` (or
    straight to :class:`HttpxRestTransport`). Defaults mirror ``httpx``.

    Example::

        # A larger, longer-lived pool for a high-throughput client.
        CommonRestClient(
            "https://api.example.com",
            pool=PoolConfig(max_connections=200, max_keepalive_connections=50,
                            keepalive_expiry=30.0),
        )
    """

    max_connections: Optional[int] = 100
    """Maximum number of concurrent connections. ``None`` means unbounded."""

    max_keepalive_connections: Optional[int] = 20
    """Maximum number of idle keep-alive connections retained for reuse.
    ``None`` means unbounded; ``0`` disables keep-alive entirely."""

    keepalive_expiry: Optional[float] = 5.0
    """Seconds an idle keep-alive connection is kept before being closed.
    ``None`` disables expiry."""

    follow_redirects: bool = True
    """Whether to transparently follow 3xx redirects."""


class HttpxRestTransport:
    """Default :class:`RestTransport` backed by :class:`httpx.AsyncClient`.

    Owns a single ``AsyncClient`` (created lazily on first use) so connections
    are **pooled and reused** across requests. Call :meth:`aclose` -- or use the
    owning :class:`CommonRestClient` as an async context manager -- to close it.

    Args:
        timeout: Default per-request timeout in seconds.
        pool: Connection-pool configuration. Defaults to :class:`PoolConfig`.
        client: An existing ``AsyncClient`` to use instead of creating one.
            Handy for tests (``httpx.MockTransport``) or to share a pre-tuned
            client. When supplied, ``pool``/``timeout``/``httpx_kwargs`` are
            ignored and this transport does **not** close it.
        **httpx_kwargs: Extra keyword arguments forwarded verbatim to
            ``httpx.AsyncClient`` for advanced customisation, e.g. ``verify``
            (TLS), ``http2=True``, ``proxy=...``, ``trust_env``, ``cert``,
            ``event_hooks``.
    """

    def __init__(
        self,
        *,
        timeout: float = 10.0,
        pool: Optional[PoolConfig] = None,
        client: Optional[httpx.AsyncClient] = None,
        **httpx_kwargs: Any,
    ) -> None:
        self._timeout = timeout
        self._pool = pool if pool is not None else PoolConfig()
        self._httpx_kwargs = httpx_kwargs
        self._client = client
        self._owns_client = client is None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            import httpx  # local import keeps the module import cheap

            pool = self._pool
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=pool.follow_redirects,
                limits=httpx.Limits(
                    max_connections=pool.max_connections,
                    max_keepalive_connections=pool.max_keepalive_connections,
                    keepalive_expiry=pool.keepalive_expiry,
                ),
                **self._httpx_kwargs,
            )
        return self._client

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Mapping[str, str]] = None,
        params: Optional[Mapping[str, Any]] = None,
        content: Optional[bytes] = None,
        data: Optional[Mapping[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> RestResponse:
        import httpx

        client = self._get_client()
        try:
            response = await client.request(
                method,
                url,
                headers=dict(headers) if headers else None,
                params=dict(params) if params else None,
                content=content,
                data=dict(data) if data else None,
                timeout=timeout if timeout is not None else self._timeout,
            )
        except httpx.TimeoutException as exc:
            raise RestTimeoutError(f'{method} {url} timed out') from exc
        except httpx.RequestError as exc:
            raise RestConnectionError(f'{method} {url} failed: {exc}') from exc

        try:
            elapsed: Optional[float] = response.elapsed.total_seconds()
        except RuntimeError:  # elapsed not available (e.g. certain mock setups)
            elapsed = None

        return RestResponse(
            status_code=response.status_code,
            headers=dict(response.headers),
            content=response.content,
            url=str(response.url),
            method=method.upper(),
            encoding=response.encoding or 'utf-8',
            elapsed_seconds=elapsed,
        )

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None


# ---------------------------------------------------------------------------
# The client
# ---------------------------------------------------------------------------
class CommonRestClient:
    """A convenient, backend-agnostic REST client.

    Combines a base URL, a default :class:`Auth` strategy, default headers/params
    and a :class:`RestTransport` into an easy-to-use client with one method per
    HTTP verb. Subclass it to build a typed client for a specific API (see the
    module docstring for examples).

    Args:
        base_url: Base URL every relative path is resolved against. Passing an
            absolute URL (``http(s)://...``) to a request method bypasses it.
        auth: Default authentication strategy applied to every request. Override
            per request via the ``auth`` argument; pass :class:`NoAuth` to send
            an unauthenticated request.
        default_headers: Headers merged into every request (lowest priority).
        default_params: Query parameters merged into every request.
        timeout: Default per-request timeout in seconds. Only used when the
            default transport is created (ignored if ``transport`` is supplied).
        pool: Connection-pool configuration for the default transport (see
            :class:`PoolConfig`). Ignored when ``transport`` is supplied.
        raise_for_status: When ``True``, non-2xx responses raise
            :class:`RestResponseError` automatically. Can be overridden per call.
        transport: A custom :class:`RestTransport`. Defaults to
            :class:`HttpxRestTransport`. Supply one directly for advanced
            backends or httpx options (TLS ``verify``, ``http2``, proxies, ...).
    """

    def __init__(
        self,
        base_url: str,
        *,
        auth: Optional[Auth] = None,
        default_headers: Optional[Mapping[str, str]] = None,
        default_params: Optional[Mapping[str, Any]] = None,
        timeout: float = 10.0,
        pool: Optional[PoolConfig] = None,
        raise_for_status: bool = False,
        transport: Optional[RestTransport] = None,
    ) -> None:
        self.base_url = base_url
        self.auth: Auth = auth if auth is not None else NoAuth()
        # Normalise to plain dicts so later merges are cheap and predictable.
        self.default_headers: dict[str, str] = dict(default_headers or {})
        self.default_params: dict[str, Any] = dict(default_params or {})
        self.timeout = timeout
        self.pool = pool if pool is not None else PoolConfig()
        self.raise_for_status = raise_for_status
        self.transport: RestTransport = (
            transport
            if transport is not None
            else HttpxRestTransport(timeout=timeout, pool=self.pool)
        )

    # -- URL helpers -------------------------------------------------------
    def build_url(self, path: str) -> str:
        """Resolve ``path`` against :attr:`base_url`.

        Absolute URLs (``http://``/``https://``) are returned unchanged, so a
        caller can point a single request at a different host when needed.
        """
        if path.startswith(('http://', 'https://')):
            return path
        return f'{self.base_url.rstrip("/")}/{path.lstrip("/")}'

    def join_url(self, *parts: str) -> str:
        return '/'.join(part.strip('/') for part in parts)

    # -- Core request ------------------------------------------------------
    async def request(
        self,
        method: HttpMethod,
        path: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        json: Any = None,
        data: Optional[Mapping[str, Any]] = None,
        content: Optional[bytes] = None,
        headers: Optional[Mapping[str, str]] = None,
        auth: Optional[Auth] = None,
        timeout: Optional[float] = None,
        raise_for_status: Optional[bool] = None,
    ) -> RestResponse:
        """Send an HTTP request and return a :class:`RestResponse`.

        Args:
            method: HTTP verb (``"GET"``, ``"POST"``, ...).
            path: Relative path (resolved against :attr:`base_url`) or absolute URL.
            params: Query parameters (merged with defaults and auth params).
            json: A JSON-serialisable value used as the request body. Encoded via
                :func:`foundation.serialization.encode_json` (so ``msgspec``
                structs work) and sent with ``Content-Type: application/json``.
                Mutually exclusive with ``data``/``content``.
            data: Form-encoded body (``application/x-www-form-urlencoded``).
            content: Raw bytes body.
            headers: Per-request headers (highest priority).
            auth: Per-request auth strategy overriding :attr:`auth`. ``None``
                (default) keeps the client's auth; pass :class:`NoAuth` to
                disable auth for this call.
            timeout: Per-request timeout override, in seconds.
            raise_for_status: Override the client's ``raise_for_status`` setting
                for this call.

        Returns:
            The response wrapper.

        Raises:
            RestConnectionError: On transport-level failures.
            RestTimeoutError: When the request times out.
            RestResponseError: For non-2xx responses when ``raise_for_status``
                is in effect.
        """
        url = self.build_url(path)
        effective_auth = self.auth if auth is None else auth

        merged_headers: dict[str, str] = dict(self.default_headers)
        merged_headers.update(effective_auth.headers())

        body: Optional[bytes] = content
        if json is not None:
            if data is not None or content is not None:
                raise ValueError('`json` cannot be combined with `data` or `content`')
            body = encode_json(json)
            merged_headers.setdefault('Content-Type', 'application/json')

        if headers:
            merged_headers.update(headers)

        merged_params: dict[str, Any] = dict(self.default_params)
        merged_params.update(effective_auth.params())
        if params:
            merged_params.update(params)

        response = await self.transport.request(
            method,
            url,
            headers=merged_headers or None,
            params=merged_params or None,
            content=body,
            data=data,
            timeout=timeout,
        )

        should_raise = self.raise_for_status if raise_for_status is None else raise_for_status
        if should_raise:
            response.raise_for_status()
        return response

    # -- Verb shortcuts ----------------------------------------------------
    async def get(self, path: str, **kwargs: Any) -> RestResponse:
        """Send a ``GET`` request. See :meth:`request` for keyword arguments."""
        return await self.request('GET', path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> RestResponse:
        """Send a ``POST`` request. See :meth:`request` for keyword arguments."""
        return await self.request('POST', path, **kwargs)

    async def put(self, path: str, **kwargs: Any) -> RestResponse:
        """Send a ``PUT`` request. See :meth:`request` for keyword arguments."""
        return await self.request('PUT', path, **kwargs)

    async def patch(self, path: str, **kwargs: Any) -> RestResponse:
        """Send a ``PATCH`` request. See :meth:`request` for keyword arguments."""
        return await self.request('PATCH', path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> RestResponse:
        """Send a ``DELETE`` request. See :meth:`request` for keyword arguments."""
        return await self.request('DELETE', path, **kwargs)

    async def head(self, path: str, **kwargs: Any) -> RestResponse:
        """Send a ``HEAD`` request. See :meth:`request` for keyword arguments."""
        return await self.request('HEAD', path, **kwargs)

    async def options(self, path: str, **kwargs: Any) -> RestResponse:
        """Send an ``OPTIONS`` request. See :meth:`request` for keyword arguments."""
        return await self.request('OPTIONS', path, **kwargs)

    # -- Lifecycle ---------------------------------------------------------
    async def aclose(self) -> None:
        """Close the underlying transport and release its resources."""
        await self.transport.aclose()

    async def __aenter__(self) -> CommonRestClient:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.aclose()
