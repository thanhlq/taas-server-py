"""Tests for `foundation.http.rest_client`.

Two layers of testing:

* A :class:`RecordingTransport` (implements :class:`RestTransport`) exercises the
  backend-independent logic of :class:`CommonRestClient` -- URL building, auth,
  header/param merging, JSON encoding, ``raise_for_status`` -- with no network.
* :class:`httpx.MockTransport` exercises :class:`HttpxRestTransport` end to end:
  the real ``httpx`` wiring, response conversion and error translation.

Run from the repo root::

    uv run --package foundation pytest -v libs/foundation/tests/unit_local/test_rest_client.py
"""

from __future__ import annotations

from typing import Any, Optional

import httpx
import msgspec
import pytest
from foundation.http.rest_client import (
    ApiKeyAuth,
    BasicAuth,
    BearerAuth,
    CommonRestClient,
    HeaderAuth,
    HttpxRestTransport,
    NoAuth,
    PoolConfig,
    RestConnectionError,
    RestResponse,
    RestResponseError,
    RestTimeoutError,
    RestTransport,
)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------
class RecordedRequest:
    """A single request captured by :class:`RecordingTransport`."""

    def __init__(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        params: dict[str, Any],
        content: Optional[bytes],
        data: Optional[dict[str, Any]],
        timeout: Optional[float],
    ) -> None:
        self.method = method
        self.url = url
        self.headers = headers
        self.params = params
        self.content = content
        self.data = data
        self.timeout = timeout


class RecordingTransport:
    """A :class:`RestTransport` that records calls and returns a canned response."""

    def __init__(
        self,
        status_code: int = 200,
        content: bytes = b'{}',
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        self.status_code = status_code
        self.content = content
        self.response_headers = headers or {'Content-Type': 'application/json'}
        self.calls: list[RecordedRequest] = []
        self.closed = False

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[dict[str, str]] = None,
        params: Optional[dict[str, Any]] = None,
        content: Optional[bytes] = None,
        data: Optional[dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> RestResponse:
        self.calls.append(
            RecordedRequest(
                method,
                url,
                dict(headers or {}),
                dict(params or {}),
                content,
                dict(data) if data else None,
                timeout,
            )
        )
        return RestResponse(
            status_code=self.status_code,
            headers=self.response_headers,
            content=self.content,
            url=url,
            method=method,
        )

    async def aclose(self) -> None:
        self.closed = True

    @property
    def last(self) -> RecordedRequest:
        return self.calls[-1]


# The recording double must satisfy the protocol.
def test_recording_transport_is_a_rest_transport() -> None:
    assert isinstance(RecordingTransport(), RestTransport)


# ---------------------------------------------------------------------------
# URL building
# ---------------------------------------------------------------------------
def test_build_url_joins_relative_path() -> None:
    client = CommonRestClient('https://api.example.com/')
    assert client.build_url('/users') == 'https://api.example.com/users'
    assert client.build_url('users') == 'https://api.example.com/users'


def test_build_url_passes_through_absolute_url() -> None:
    client = CommonRestClient('https://api.example.com')
    assert client.build_url('https://other.test/x') == 'https://other.test/x'


async def test_absolute_path_bypasses_base_url() -> None:
    transport = RecordingTransport()
    client = CommonRestClient('https://api.example.com', transport=transport)
    await client.get('https://other.test/ping')
    assert transport.last.url == 'https://other.test/ping'


# ---------------------------------------------------------------------------
# Verb dispatch
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    'verb, expected',
    [
        ('get', 'GET'),
        ('post', 'POST'),
        ('put', 'PUT'),
        ('patch', 'PATCH'),
        ('delete', 'DELETE'),
        ('head', 'HEAD'),
        ('options', 'OPTIONS'),
    ],
)
async def test_verb_shortcuts_dispatch_the_right_method(verb: str, expected: str) -> None:
    transport = RecordingTransport()
    client = CommonRestClient('https://api.example.com', transport=transport)
    await getattr(client, verb)('/thing')
    assert transport.last.method == expected
    assert transport.last.url == 'https://api.example.com/thing'


# ---------------------------------------------------------------------------
# Header / param merging + defaults
# ---------------------------------------------------------------------------
async def test_default_headers_and_params_are_merged() -> None:
    transport = RecordingTransport()
    client = CommonRestClient(
        'https://api.example.com',
        default_headers={'Accept': 'application/json'},
        default_params={'lang': 'en'},
        transport=transport,
    )
    await client.get('/x', headers={'X-Trace': 'abc'}, params={'page': 2})
    assert transport.last.headers['Accept'] == 'application/json'
    assert transport.last.headers['X-Trace'] == 'abc'
    assert transport.last.params == {'lang': 'en', 'page': 2}


async def test_per_request_header_overrides_default() -> None:
    transport = RecordingTransport()
    client = CommonRestClient(
        'https://api.example.com',
        default_headers={'Accept': 'application/json'},
        transport=transport,
    )
    await client.get('/x', headers={'Accept': 'text/plain'})
    assert transport.last.headers['Accept'] == 'text/plain'


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
async def test_bearer_auth_adds_authorization_header() -> None:
    transport = RecordingTransport()
    client = CommonRestClient(
        'https://api.example.com', auth=BearerAuth('tok'), transport=transport
    )
    await client.get('/me')
    assert transport.last.headers['Authorization'] == 'Bearer tok'


async def test_bearer_auth_supports_dynamic_token() -> None:
    tokens = iter(['first', 'second'])
    transport = RecordingTransport()
    client = CommonRestClient(
        'https://api.example.com',
        auth=BearerAuth(lambda: next(tokens)),
        transport=transport,
    )
    await client.get('/a')
    await client.get('/b')
    assert transport.calls[0].headers['Authorization'] == 'Bearer first'
    assert transport.calls[1].headers['Authorization'] == 'Bearer second'


async def test_api_key_auth_as_header() -> None:
    transport = RecordingTransport()
    client = CommonRestClient(
        'https://api.example.com',
        auth=ApiKeyAuth('secret', header_name='X-Api-Token'),
        transport=transport,
    )
    await client.get('/x')
    assert transport.last.headers['X-Api-Token'] == 'secret'


async def test_api_key_auth_as_query_param() -> None:
    transport = RecordingTransport()
    client = CommonRestClient(
        'https://api.example.com',
        auth=ApiKeyAuth('secret', query_param='api_key'),
        transport=transport,
    )
    await client.get('/x', params={'page': 1})
    assert transport.last.params == {'api_key': 'secret', 'page': 1}
    assert 'X-API-Key' not in transport.last.headers


async def test_basic_auth_encodes_credentials() -> None:
    transport = RecordingTransport()
    client = CommonRestClient(
        'https://api.example.com', auth=BasicAuth('user', 'pass'), transport=transport
    )
    await client.get('/x')
    # base64("user:pass") == "dXNlcjpwYXNz"
    assert transport.last.headers['Authorization'] == 'Basic dXNlcjpwYXNz'


async def test_header_auth_injects_custom_headers() -> None:
    transport = RecordingTransport()
    client = CommonRestClient(
        'https://api.example.com',
        auth=HeaderAuth({'X-App-Id': 'id', 'X-App-Secret': 'sec'}),
        transport=transport,
    )
    await client.get('/x')
    assert transport.last.headers['X-App-Id'] == 'id'
    assert transport.last.headers['X-App-Secret'] == 'sec'


async def test_per_request_auth_overrides_client_default() -> None:
    transport = RecordingTransport()
    client = CommonRestClient(
        'https://api.example.com', auth=BearerAuth('default'), transport=transport
    )
    await client.get('/x', auth=BearerAuth('override'))
    assert transport.last.headers['Authorization'] == 'Bearer override'


async def test_noauth_disables_client_default_for_one_request() -> None:
    transport = RecordingTransport()
    client = CommonRestClient(
        'https://api.example.com', auth=BearerAuth('default'), transport=transport
    )
    await client.get('/public', auth=NoAuth())
    assert 'Authorization' not in transport.last.headers


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------
async def test_json_body_is_encoded_and_content_type_set() -> None:
    transport = RecordingTransport()
    client = CommonRestClient('https://api.example.com', transport=transport)
    await client.post('/users', json={'name': 'Ada', 'age': 36})
    assert transport.last.headers['Content-Type'] == 'application/json'
    assert msgspec.json.decode(transport.last.content) == {'name': 'Ada', 'age': 36}


async def test_json_body_accepts_msgspec_struct() -> None:
    class Payload(msgspec.Struct):
        name: str
        active: bool

    transport = RecordingTransport()
    client = CommonRestClient('https://api.example.com', transport=transport)
    await client.post('/users', json=Payload(name='Bob', active=True))
    assert msgspec.json.decode(transport.last.content) == {'name': 'Bob', 'active': True}


async def test_json_conflicts_with_data_raises() -> None:
    transport = RecordingTransport()
    client = CommonRestClient('https://api.example.com', transport=transport)
    with pytest.raises(ValueError):
        await client.post('/x', json={'a': 1}, data={'b': 2})


async def test_form_data_is_forwarded_to_transport() -> None:
    transport = RecordingTransport()
    client = CommonRestClient('https://api.example.com', transport=transport)
    await client.post('/login', data={'user': 'a', 'pass': 'b'})
    assert transport.last.data == {'user': 'a', 'pass': 'b'}
    assert transport.last.content is None


# ---------------------------------------------------------------------------
# Response wrapper
# ---------------------------------------------------------------------------
def test_response_status_helpers() -> None:
    ok = RestResponse(200, {}, b'{}', 'u', 'GET')
    client_err = RestResponse(404, {}, b'{}', 'u', 'GET')
    server_err = RestResponse(503, {}, b'{}', 'u', 'GET')
    assert ok.is_success and not ok.is_client_error
    assert client_err.is_client_error and not client_err.is_success
    assert server_err.is_server_error


def test_response_text_uses_encoding() -> None:
    res = RestResponse(200, {}, 'héllo'.encode('utf-8'), 'u', 'GET')
    assert res.text == 'héllo'


def test_response_json_typed_decode() -> None:
    class User(msgspec.Struct):
        id: int
        name: str

    res = RestResponse(200, {}, b'{"id": 1, "name": "Ada"}', 'u', 'GET')
    user = res.json(User)
    assert isinstance(user, User)
    assert user.id == 1 and user.name == 'Ada'


def test_get_header_is_case_insensitive() -> None:
    res = RestResponse(200, {'Content-Type': 'application/json'}, b'{}', 'u', 'GET')
    assert res.get_header('content-type') == 'application/json'
    assert res.get_header('missing', 'fallback') == 'fallback'


# ---------------------------------------------------------------------------
# raise_for_status
# ---------------------------------------------------------------------------
async def test_raise_for_status_per_request() -> None:
    transport = RecordingTransport(status_code=500, content=b'{"error": "boom"}')
    client = CommonRestClient('https://api.example.com', transport=transport)
    # No raise by default.
    res = await client.get('/x')
    assert res.status_code == 500
    # Opt in per request.
    with pytest.raises(RestResponseError) as exc:
        await client.get('/x', raise_for_status=True)
    assert exc.value.status_code == 500


async def test_client_level_raise_for_status() -> None:
    transport = RecordingTransport(status_code=404)
    client = CommonRestClient(
        'https://api.example.com', raise_for_status=True, transport=transport
    )
    with pytest.raises(RestResponseError):
        await client.get('/missing')


def test_raise_for_status_returns_self_on_success() -> None:
    res = RestResponse(200, {}, b'{"ok": true}', 'u', 'GET')
    assert res.raise_for_status() is res


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
async def test_context_manager_closes_transport() -> None:
    transport = RecordingTransport()
    async with CommonRestClient('https://api.example.com', transport=transport) as client:
        await client.get('/x')
    assert transport.closed is True


# ---------------------------------------------------------------------------
# HttpxRestTransport end-to-end (via httpx.MockTransport)
# ---------------------------------------------------------------------------
def _mock_httpx_client(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_httpx_transport_roundtrip() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == 'GET'
        assert request.url.path == '/users'
        assert request.url.params.get('page') == '2'
        return httpx.Response(
            200, json={'items': [1, 2]}, headers={'X-Total': '2'}
        )

    transport = HttpxRestTransport(client=_mock_httpx_client(handler))
    client = CommonRestClient(
        'https://api.example.com',
        auth=BearerAuth('tok'),
        transport=transport,
    )
    res = await client.get('/users', params={'page': 2})
    assert res.status_code == 200
    assert res.json() == {'items': [1, 2]}
    assert res.get_header('x-total') == '2'
    await client.aclose()


async def test_httpx_transport_forwards_auth_header() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen['authorization'] = request.headers.get('authorization', '')
        return httpx.Response(204)

    transport = HttpxRestTransport(client=_mock_httpx_client(handler))
    client = CommonRestClient(
        'https://api.example.com', auth=BearerAuth('secret'), transport=transport
    )
    await client.delete('/things/1')
    assert seen['authorization'] == 'Bearer secret'


async def test_httpx_transport_wraps_connection_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError('refused', request=request)

    transport = HttpxRestTransport(client=_mock_httpx_client(handler))
    client = CommonRestClient('https://api.example.com', transport=transport)
    with pytest.raises(RestConnectionError):
        await client.get('/x')


async def test_httpx_transport_wraps_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout('slow', request=request)

    transport = HttpxRestTransport(client=_mock_httpx_client(handler))
    client = CommonRestClient('https://api.example.com', transport=transport)
    with pytest.raises(RestTimeoutError):
        await client.get('/x')


async def test_httpx_transport_does_not_close_injected_client() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    injected = _mock_httpx_client(handler)
    transport = HttpxRestTransport(client=injected)
    await transport.aclose()
    # Injected client is owned by the caller and must stay usable.
    assert injected.is_closed is False
    await injected.aclose()


# ---------------------------------------------------------------------------
# Connection pooling / PoolConfig
# ---------------------------------------------------------------------------
def test_pool_config_defaults() -> None:
    pool = PoolConfig()
    assert pool.max_connections == 100
    assert pool.max_keepalive_connections == 20
    assert pool.keepalive_expiry == 5.0
    assert pool.follow_redirects is True


def test_client_forwards_pool_to_default_transport() -> None:
    pool = PoolConfig(max_connections=200, max_keepalive_connections=50)
    client = CommonRestClient('https://api.example.com', pool=pool)
    assert client.pool is pool
    assert isinstance(client.transport, HttpxRestTransport)
    assert client.transport._pool is pool


def test_client_uses_default_pool_when_unset() -> None:
    client = CommonRestClient('https://api.example.com')
    assert isinstance(client.transport, HttpxRestTransport)
    assert client.transport._pool == PoolConfig()


def test_pool_ignored_when_custom_transport_supplied() -> None:
    recording = RecordingTransport()
    client = CommonRestClient(
        'https://api.example.com',
        pool=PoolConfig(max_connections=1),
        transport=recording,
    )
    assert client.transport is recording


async def test_httpx_transport_applies_pool_and_extra_kwargs(monkeypatch: Any) -> None:
    """PoolConfig maps to httpx.Limits; ``**httpx_kwargs`` reach the client."""
    captured: dict[str, Any] = {}
    real_init = httpx.AsyncClient.__init__

    def spy(self: httpx.AsyncClient, *args: Any, **kwargs: Any) -> None:
        captured.update(kwargs)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, '__init__', spy)

    pool = PoolConfig(
        max_connections=7,
        max_keepalive_connections=3,
        keepalive_expiry=12.0,
        follow_redirects=False,
    )
    transport = HttpxRestTransport(timeout=2.5, pool=pool, verify=False)
    transport._get_client()  # lazy build

    limits = captured['limits']
    assert limits.max_connections == 7
    assert limits.max_keepalive_connections == 3
    assert limits.keepalive_expiry == 12.0
    assert captured['follow_redirects'] is False
    assert captured['verify'] is False
    assert captured['timeout'] == 2.5

    await transport.aclose()


async def test_httpx_transport_reuses_single_pooled_client() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    transport = HttpxRestTransport()
    client = CommonRestClient('https://api.example.com', transport=transport)
    # Swap in a mock client so no real sockets are opened, then confirm the
    # transport keeps reusing that one instance across requests.
    transport._client = _mock_httpx_client(handler)
    first = transport._get_client()
    await client.get('/a')
    await client.get('/b')
    assert transport._get_client() is first
    await client.aclose()
