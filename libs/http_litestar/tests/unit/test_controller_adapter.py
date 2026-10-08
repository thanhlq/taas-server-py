"""``foundation.http`` controllers on Litestar behave like on FastAPI (ADR-P2): typed path parameters in the
controller prefix, status 200 by default for every method, no-content routes without a body."""

from __future__ import annotations

from foundation.http import BaseController, delete, get, post, status
from litestar import Litestar
from litestar.testing import TestClient

from http_litestar.adapters import build_router_for_controller


class _Items(BaseController):
    api_prefix = '/api/v1/sites/{site_id}/items'

    @get('/{item_id}')
    async def read(self, site_id: str, item_id: str) -> dict[str, str]:
        return {'site': site_id, 'item': item_id}

    @post('/')
    async def create(self, site_id: str) -> dict[str, str]:
        return {'site': site_id}

    @delete('/{item_id}')
    async def remove(self, site_id: str, item_id: str) -> dict[str, str]:
        return {'deleted': item_id}

    @delete('/{item_id}/hard', status_code=status.HTTP_204_NO_CONTENT)
    async def purge(self, site_id: str, item_id: str) -> None:
        return None


def _client() -> TestClient:
    return TestClient(Litestar(route_handlers=[build_router_for_controller(_Items())]))


def test_prefix_path_parameters_are_typed():
    with _client() as client:
        res = client.get('/api/v1/sites/s1/items/i1')
        assert res.status_code == 200
        assert res.json() == {'site': 's1', 'item': 'i1'}


def test_status_200_by_default_like_fastapi():
    with _client() as client:
        assert client.post('/api/v1/sites/s1/items').status_code == 200
        res = client.delete('/api/v1/sites/s1/items/i1')
        assert res.status_code == 200
        assert res.json() == {'deleted': 'i1'}


def test_no_content_route():
    with _client() as client:
        res = client.delete('/api/v1/sites/s1/items/i1/hard')
        assert res.status_code == 204
        assert res.content == b''
