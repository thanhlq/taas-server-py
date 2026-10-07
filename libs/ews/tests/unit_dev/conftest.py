"""API tests of the EWS business apps (media, sites, ppm, crm) on the local Postgres of ``.env.test``.

Each session creates its own tenant + root organization (+ a sub-organization) and removes them at the
end (``ON DELETE CASCADE``). Blobs go to the in-memory adapter. Authentication: development mode
(``taas_dev_session`` cookie) unless a test configures ``ews.security`` itself.
Run: ``uv run pytest libs/ews/tests/unit_dev`` (skips when the database is unreachable).
"""

from __future__ import annotations

import base64
import json
import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from dotenv import load_dotenv


def _root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / '.env.test').exists() or (parent / 'libs').is_dir() and (parent / 'pyproject.toml').exists():
            return parent
    return Path(__file__).resolve().parents[4]


_env = _root() / '.env.test'
load_dotenv(_env if _env.exists() else _root() / '.env', override=True)
os.environ.setdefault('MEDIA_PUBLIC_BASE_URL', 'http://testserver')
os.environ['TAAS_RATE_LIMIT_ENABLED'] = 'false'

import httpx  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from sqlalchemy import text  # noqa: E402


@dataclass(frozen=True)
class TestOrg:
    tenant_id: uuid.UUID
    organization_id: uuid.UUID
    child_organization_id: uuid.UUID
    slug: str
    user_id: uuid.UUID
    email: str


def dev_cookie(email: str, name: str = 'Tester') -> str:
    raw = json.dumps({'email': email, 'name': name}).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


async def _execute(sql: str, params: dict | None = None) -> None:
    from foundation.db.advanced_db_manager import MainDatabase

    async with MainDatabase.get_instance().get_engine().begin() as conn:
        await conn.execute(text(sql), params or {})


@pytest.fixture
def sql():
    """Run one SQL statement on the test database (setup helpers)."""
    return _execute


@pytest.fixture(scope='session')
async def test_org() -> AsyncIterator[TestOrg]:
    try:
        await _execute('select 1 from taas_tenants limit 1')
    except Exception as error:  # noqa: BLE001
        pytest.skip(f'local database not usable: {error}')
    suffix = uuid.uuid4().hex[:10]
    org = TestOrg(
        tenant_id=uuid.uuid4(),
        organization_id=uuid.uuid7(),
        child_organization_id=uuid.uuid7(),
        slug=f'ews-test-{suffix}',
        user_id=uuid.uuid4(),
        email=f'ews-test-{suffix}@example.test',
    )
    code = str(uuid.uuid4().int)[:8]
    await _execute(
        "insert into taas_tenants (id, name, status, slug, created_at, updated_at, tenant_code, account_type) "
        "values (:id, :name, 'ACTIVE', :slug, now(), now(), :code, 'organization')",
        {'id': org.tenant_id, 'name': 'EWS test', 'slug': org.slug, 'code': code},
    )
    insert_org = (
        "insert into taas_organizations (id, name, status, slug, created_at, updated_at, tenant_id, parent_id, path, depth) "
        "values (:id, :name, 'ACTIVE', :slug, now(), now(), :t, :parent, :path, :depth)"
    )
    await _execute(
        insert_org,
        {'id': org.organization_id, 'name': 'EWS test', 'slug': org.slug, 't': org.tenant_id, 'parent': None,
         'path': f'/{org.organization_id}/', 'depth': 0},
    )
    await _execute(
        insert_org,
        {'id': org.child_organization_id, 'name': 'EWS test child', 'slug': f'{org.slug}-child', 't': org.tenant_id,
         'parent': org.organization_id, 'path': f'/{org.organization_id}/{org.child_organization_id}/', 'depth': 1},
    )
    await _execute(
        "insert into taas_user_account (id, email, username, email_verified, joined_at, login_count, is_root_account, "
        "failed_reset_attempts, mfa_enabled, created_at, updated_at, tenant_id, directory_id) "
        "values (:id, :email, :email, true, current_date, 0, false, 0, false, now(), now(), :t, :sub)",
        {'id': org.user_id, 'email': org.email, 't': org.tenant_id, 'sub': f'sub-{suffix}'},
    )
    yield org
    projects = 'select id from taas_projects where tenant_id = :t'
    for statement in (
        f'delete from taas_timelogs where project_id in ({projects})',
        'delete from taas_projects_comments where project_id in (select id::text from taas_projects where tenant_id = :t)',
        f'delete from taas_tasks_lists where project_id in ({projects})',
        f'delete from taas_projects_iterations where project_id in ({projects})',
        f'delete from taas_projects_workflows_assignments where project_id in ({projects})',
        f'delete from taas_tasks where project_id in ({projects})',
        'delete from taas_projects_workflows_stages where workflow_id in '
        f'(select id from taas_projects_workflows where project_id in ({projects}))',
        f'delete from taas_projects_workflows where project_id in ({projects})',
        'delete from taas_projects where tenant_id = :t',
    ):
        await _execute(statement, {'t': org.tenant_id})
    await _execute('delete from taas_crm_accounts where tenant_id = :t', {'t': org.tenant_id})
    await _execute(
        "delete from taas_casbin_rule where ptype = 'g' and (v2 like :t or (v2 like 'site:%' or v2 like 'project:%') and v0 = :u)",
        {'t': f'%{org.tenant_id}%', 'u': str(org.user_id)},
    )
    await _execute('delete from taas_user_account where id = :id', {'id': org.user_id})
    await _execute('delete from taas_tenants where id = :id', {'id': org.tenant_id})


@pytest.fixture(scope='session')
async def app(test_org: TestOrg) -> FastAPI:
    from blob_service import (
        AdapterPublicStore,
        MemoryBlobAdapter,
        MemoryTenantBucketRegistry,
        create_blob_service,
        create_storage_resolver,
    )
    from ews.media import get_media_controllers, use_storage
    from ews.sites._cdn import use_public_store
    from foundation.blob import StorageSettings
    from ews.security import EwsAuthSettings, configure_security
    from http_fastapi.adapters import include_controller
    from http_fastapi.middewares.request_context import RequestContextMiddleware
    from http_fastapi.setup_fastapi_app import setup_fastapi_app

    adapter = MemoryBlobAdapter()
    registry = MemoryTenantBucketRegistry({str(test_org.tenant_id): '12345678'})
    blob = create_blob_service(adapter=adapter, registry=registry, register=False)
    settings = StorageSettings(STORAGE_PRIVATE_MODE='pooled', STORAGE_PRIVATE_BUCKET='taas-private-test')
    use_storage(create_storage_resolver(blob, registry, settings, register=False))
    await adapter.ensure_bucket('cdn-test')
    use_public_store(AdapterPublicStore(adapter, 'cdn-test', 'https://cdn.test'))
    configure_security(settings=EwsAuthSettings(mode='dev', dev_organization_id=str(test_org.organization_id)))
    api = FastAPI()
    api.add_middleware(RequestContextMiddleware)
    setup_fastapi_app(api)
    from ews.crm import get_crm_controllers
    from ews.ppm import get_project_controllers

    controllers = [*get_media_controllers(), *get_project_controllers(), *get_crm_controllers()]
    try:
        from ews.sites import get_sites_controllers

        controllers += get_sites_controllers()
    except ImportError:
        pass
    for controller in controllers:
        include_controller(api, controller)
    return api


@pytest.fixture
async def client(app: FastAPI, test_org: TestOrg) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url='http://testserver',
        cookies={'taas_dev_session': dev_cookie(test_org.email)},
        # Origin: cookie-authenticated writes must come from an allowed origin (CSRF guard, ews.security._csrf).
        headers={
            'X-Tenant-ID': str(test_org.tenant_id),
            'X-Organization-Id': str(test_org.organization_id),
            'Origin': 'http://testserver',
        },
    ) as c:
        yield c
