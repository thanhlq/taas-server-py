# Business apps: authentication, Site Builder, Media library

Code: `libs/ews/src/ews/{security,sites,media,ai,shared}`, models `libs/db/src/db/models/{sites,media}`.
Specs: `taas-specs/site-builder` (decisions ADR-1…10), `taas-specs/media`, authorization in
`taas-specs/iam/specs/authorization-rbac-spec.md`.

## 1. Request scope and permissions (`ews/security`)

```python
from ews.security import authorize, current_scope

scope = await current_scope()                          # user, tenant, organization of the current request (cached)
await authorize(scope, 'sites.page', 'update', domains) # 403 unless granted on one of the domains
```

| `EWS_AUTH_MODE` | Who is the user |
| --- | --- |
| `iam` (default) | Cookie / `Authorization` forwarded to `GET {IAM_INTERNAL_URL}/api/v1/auth/session` (cached `EWS_AUTH_CACHE_SECONDS`); tenant + organization from `X-Tenant-ID` / `X-Organization-Id` (membership, ancestor membership or tenant admin, else 404) or the home organization |
| `dev` | `taas_dev_session` cookie of the web's development sign-in; **every permission**; organization `EWS_DEV_ORGANIZATION_ID` → slug `demo` → oldest root organization |

Domains: `resource_domains(site_id=…)` → `site:<id>` → `org:<id>` chain → `tenant:<id>`. Grants are Casbin rows
`g, <user>, <role>, <domain>` (`ews.authz.grant`, `revoke_domain`, `granted_permissions`).

## 2. Site Builder (`ews/sites`, `/api/v1/sites/*`)

| File | Role |
| --- | --- |
| `data/blocks.json` | Block catalog — **source of truth** (copied to `@taas/site-blocks`, parity test on the web) |
| `_document.py` | `validate_document`, `migrate_document`, `asset_ids`, `page_ids`, `plain_text`, `is_safe_url` |
| `_rules.py` | Slugs + reserved paths, theme normalization + contrast, menus, redirect loops, accessibility issues |
| `_service.py` | Sites, pages (paths, automatic 301 on moves), drafts (base-revision conflict, 60 s revision reuse, lock 120 s), revisions, menus, redirects, export / import |
| `_publish.py` | Snapshots, releases (partial, a11y gate), rollback, unpublish, preview links (signed), routing table |
| `_forms.py`, `_members.py`, `_ai.py`, `_audit.py` | Form submissions (+ e-mail, CSV), site roles, AI actions (credits, rate limit), audit |
| `controllers/_internal.py` | `/api/v1/sites-internal/*` for `apps/site-renderer` — header `X-Sites-Renderer-Key` = `SITES_RENDERER_KEY`; internal network only |

Add a block: row in `blocks.json` → `pnpm --filter @taas/site-blocks sync-catalog` (taas-web-official) → React component +
Markdown round-trip test there.

## 3. Media library (`ews/media`, `/api/v1/media/*`)

Private storage via `StorageResolverT.root(tenant)` (registered in `apps/ews_api/app.py`, pooled or dedicated —
`taas-specs/platform/storage`): originals `uploads/media/<org>/<asset>/<version>/original.<ext>`, variants
`derived/media/<asset>/<version>/w<width>.webp|avif` (SHA-256 stored per variant). Publishing a site copies them to
the public CDN bucket (`ews/sites/_cdn.py` over the shared `ews/media/_publishing.py`:
`{tenantId}/site/{siteId}/{sha256}.{ext}`, URLs in the release snapshot); unpublish / archive / delete remove that
prefix. Blogs use the same helpers with the scope `blog/<blogId>` (`ews/blog/_release.py`). Tests swap the stores with `use_storage(...)` / `use_public_store(...)`. `_processing.py` sniffs the bytes, strips
EXIF GPS, builds variants, sanitizes SVG, refuses documents (415 `document_not_media`). Delivery: `MEDIA_DELIVERY=proxy`
(signed `/api/v1/media/files/<token>`, needs `MEDIA_PUBLIC_BASE_URL`) or `presigned`. Usages: `record_usages(...)`
from the owning app (site drafts on save).

## 4. AI gateway (`ews/ai`)

`get_ai_gateway()` → `AnthropicGateway` (official `anthropic` SDK), `FakeGateway` (`AI_GATEWAY_PROVIDER=fake`,
deterministic, used by tests / e2e) or disabled (`none`). Tests swap it with `use_ai_gateway(...)`.

## 5. Local run & tests

```bash
# .env §8: BLOB_STORAGE_PROVIDER=s3 + AWS_* (R2 or local RustFS), STORAGE_PRIVATE_*, CDN_* (optional public CDN)
# .env §11: SITES_RENDERER_KEY, AI_GATEWAY_PROVIDER=fake
uv run python -m db.migrations upgrade        # taas_site_* / taas_media_*
TAAS_RATE_LIMIT_REDIS_HOST=localhost bash start_fastapi_ews_api.sh
cd libs/ews && uv run pytest                  # tests/unit (catalog, processing, rules, scope)
cd libs/ews && uv run pytest tests/unit_dev   # API tests on the local Postgres (dev + iam auth modes); local only
```

Public sites: `pnpm --filter site-renderer dev` in taas-web-official → `http://<org-slug>.sites.localhost:7300/<site>/`.
