# CLAUDE

## Projects

The is the uv workspace which include the following libraries, applications and services

### Libraries (libs/)

| Project | Description |
| --- | --- |
| libs/foundation | Contain all core definitions and common utils for building of application |
| libs/db | Platform db models and the single Alembic migration tree (also migrates `resiliant.models`). |
| libs/ews | Core eworksuite business (ddd patterns): api definitions which can be used for building apps as: `ews_api` (Fastapi, adapter: libs/http_fastapi) and `ews_api_litestar` (Litestar, adapter: libs/http_litestar) |
| libs/banking_core | Banking domain core, including crypto factory/utilities |
| libs/blob_service | Tenant-based blob storage: `create_blob_service()` (adapter by `BLOB_STORAGE_PROVIDER`, tenant bucket in `taas_tenants.sys_settings.bucket`), memory adapter; **storage resolver** `create_storage_resolver()` (pooled / dedicated private storage, kinds `uploads/` `derived/` `knowledge/` `documents/`) and **public CDN store** `create_public_store()` (`CDN_*`). Interfaces in `foundation.blob`. See `docs/developers/blob-storage-guide.md`, `taas-specs/platform/storage` |
| libs/blob_s3 | Blob adapter for S3 compatible storage: AWS S3, Cloudflare R2, RustFS (aiobotocore) |
| libs/blob_gcp | Blob adapter for Google Cloud Storage |
| libs/blob_azure | Blob adapter for Azure Blob Storage (aio + SAS) |
| libs/block-kaspa | Kaspa blockchain integration: transactions, fee estimation and typed client |
| libs/http_fastapi | the Fastapi adatper for deploying of the api (i.e. ews) using Fastapi. |
| libs/http_litestar | the Fastapi adatper for deploying of the api (i.e. ews) using Litestar. |
| libs/iam | Contain iam implementation (with underline platform as Keycloak) but maximum Oauth 2.1 and OIDC compatible |
| libs/iam_keycloak | The iam implementation using Keycloak |
| libs/messaging_faststream | FastStream messaging utilities |
| libs/messaging_kafka | Kafka messaging utilities |
| libs/resiliant | All resilience implementations, settings and models (outboxes per use case, DLQ, idempotency on Postgres or Redis, saga, schedule, retry, circuit breaker, …) — covers key features of Temporal.io; `foundation.resiliant` keeps definitions only. See `docs/developers/resiliant-*.md` |
| libs/slowapi_advanced | The rate limit library - allowing to use decorator as @rate_limit('5/minutes') which internally use the limits library |
| libs/store_memcached | Key/value store implementation using memcached |
| libs/store_redis | Key/value store implementation using redis |

### Applications (apps/)

| Project | Description |
| --- | --- |
| apps/ews_api | The ews api deployed using Fastapi (adapter: libs/http_fastapi) |
| apps/ews_api_litestar | The ews api deployed using Litestar (adapter: libs/http_litestar) |
| apps/ews_worker | Background worker for ews |
| apps/outbox_worker | Outbox relay: one poller per outbox table + scheduler (`start_outbox.sh`, health port 7110) |

## Changelog & versions

Every change (feature, fix, breaking change, security fix) updates, in the same commit:

1. [CHANGELOG.md](CHANGELOG.md) — an entry under `## [Unreleased]` in its group (Added · Changed · Deprecated ·
   Removed · Fixed · Security) that names the package and its new version, e.g. `` `<pkg>` 0.3.0 — what changed ``;
   mark **breaking** changes. Simple, concise, for the people who use the package.
2. The version of every package / app it changes (SemVer: fix → patch, feature → minor, breaking → major; below 1.0
   a breaking change → minor). Python: `version` in the package's `pyproject.toml` (`libs/<pkg>`, `apps/<app>`),
   then `uv lock --offline` (only the version lines of `uv.lock` change). One bump per package per release: if
   `[Unreleased]` already bumped it, bump again only for a bigger change (a feature after a fix).
3. Release: `[Unreleased]` becomes `## [x.y.z] - YYYY-MM-DD` with x.y.z = the project version (`version` of the root
   `pyproject.toml`, bumped the same way), a new empty `[Unreleased]`, compare links updated, tag `vx.y.z`.

## Rules

- **Reuse first** (platform for an unlimited number of apps): before writing a helper, check
  `taas-specs/platform/architecture/building-blocks.md`; generic mechanics live in `ews/shared` (ids, signed tokens,
  materialized-path trees), `ews/access` (`ObjectAccess`: objects with their own roles — 404 / 403 rule, implicit
  roles, generic members routes), `ews/authz` (RBAC), `ews/security` (scope). A piece a second app needs is extracted,
  not copied.
- **Wire type names are unique across the EWS API** (OpenAPI components are named by class, first one wins): prefix
  app types (`KbPageOut`, `BlogPostOut`, `FileNodeOut`) or reuse a shared type — `libs/ews/tests/unit/test_schema_names.py`.
- **One RBAC with Node**: `ews/authz/data/ews-rbac.json` is owned here, `iam-rbac.json` and `rbac-cases.json` are
  copies from taas-server-js — after a catalog change run `python3 ../taas-tools/rbac-catalogs/sync_rbac_catalogs.py`
  and the unit tests of both projects (`taas-specs/iam/specs/authorization-rbac-spec.md` §7).

## Conventions

- In each implementation, if there is factory.py then this file should be the entry point for building of the implemented services in this folder.

## Start the app

There are two scripts to start the api service in fastapi and litestar framework:

- start_fastapi_ews_api.sh: start the api service under fastapi framework
- start_litestar_ews_api.sh: start the api service under litestar framework

## Environment configuration

- Start from `cp .env.example .env`; each key is documented there with default, allowed values
  and whether it is required. Use `cp .env.test.example .env.test` only for local test overrides.
- `foundation.config.get_settings()` loads `ENV_FILE` or `.env` with `python-dotenv`; process
  environment variables take precedence. `.env.local` is not layered automatically.
- Keep real `.env` / `.env.test` gitignored. Check sync with
  `python3 ../taas-tools/env-check/check_env.py taas-server-py`.

### Local run gotchas (FastAPI EWS API — binds :8191)

- **Rate limiter Redis**: `RateLimitConfig.redis_host` defaults to `redis` (a docker-network
  name, unreachable from the host) and is wrapped as `redis://<host>:6379/0`, so it needs a
  BARE host. Locally run with `TAAS_RATE_LIMIT_REDIS_HOST=localhost bash start_fastapi_ews_api.sh`,
  otherwise every route returns `503 "Rate limit storage backend is unreachable"`.
- **CORS**: the FastAPI adapter installs `CORSMiddleware` in
  `libs/http_fastapi/.../configuration.py:configure_app` from `config.cors_config`. Allowed
  origins come from `.env` `ALLOWED_CORS_ORIGINS` and MUST include the scheme
  (`http://localhost:7101`). Browser SPA clients (web web-vite) need this; Next server-side
  fetches do not.
- **EWS controllers** are registered in `libs/ews/src/ews/__init__.py:get_ews_controllers`
  (`ppm.get_project_controllers` + `crm.get_crm_controllers` + `media` + `sites.get_sites_controllers` +
  `files.get_files_controllers` +
  `blog.get_blog_controllers` + `knowledge.get_knowledge_controllers` + `PlatformController`). CRM
  accounts live at `/api/v1/crm/accounts` (`libs/ews/src/ews/crm`). `CrmAccount` uses
  advanced_alchemy `SlugKey` → set a unique `slug` on create.

## Business apps: auth, Site Builder, Media library, Blog, Knowledge Center, File Manager

- **Auth** (`libs/ews/src/ews/security`): `await current_scope()` → user + tenant + organization,
  `authorize(...)` → `ews.authz.can`. `EWS_AUTH_MODE=iam` introspects the IAM session; `dev` trusts the web's
  development sign-in cookie (all permissions). The organization comes from `X-Organization-Id`, else
  `X-Organization-Slug` (the web URL's `/<org>/`, slugs are unique). `current_scope()` also rejects cookie writes from
  an `Origin` outside `ALLOWED_CORS_ORIGINS` (CSRF, `_csrf.py`). Every business route uses it: sites, media, PPM
  (`ews/ppm/_access.py`: `load_project` / `load_task`, 404 outside the scope) and CRM. Never load a business record by
  id without the scope. Demo routes `/api/v1/test-apis` mount only for `ENVIRONMENT` local / test / development; the
  legacy `/api/v1/users` (`iam.accounts`) is not mounted.
- **Tests**: `libs/ews/tests/unit_dev/test_ppm_crm_api.py` (scoping, permissions, CSRF, soft deletes) on the local DB.
- **Site Builder** (`ews/sites`, `/api/v1/sites/*`, tables `taas_site_*`) and **Media library** (`ews/media`,
  `/api/v1/media/*`, tables `taas_media_*`, private storage through `StorageResolverT`: `uploads/media/…`,
  `derived/media/…`); publishing copies media to the public CDN (`ews/media/_publishing.py` shared by sites and blogs,
  `PublicStoreT`); AI gateway `ews/ai`. URL slugs of every app: `ews.shared.slugify`.
  Never pick buckets in app code — always the resolver (`taas-specs/platform/storage`).
  `ews/sites/data/blocks.json` is the block catalog source of truth (copied to taas-web-official `@taas/site-blocks`).
- Guide: [docs/developers/sites-media-guide.md](docs/developers/sites-media-guide.md). Env: `.env.example` §11.
- **Blog** (`ews/blog`, `/api/v1/blog/*`, tables `taas_blog_*`): blogs on `blog:<id>` (`ews.access.ObjectAccess`, roles
  `blog_admin` · `blog_editor` · `blog_author` · `blog_viewer`), posts whose body is the site document (draft / published
  revisions), workflow submit → review → publish / schedule (`ews.blog.publish_due` for the scheduler), categories,
  tags, author profiles; public reading: post addresses (`slug_auto`, `former_slugs`, `public_url`, `live`), releases
  `taas_blog_releases` rebuilt after every public change, renderer API `/api/v1/sites-internal/blog-*` + blog routes
  in the routing table, media on the CDN scope `blog/<blogId>`. Module guide `libs/ews/src/ews/blog/CLAUDE.md`, API
  `taas-specs/blog/blog-api.md`, publishing `taas-specs/blog/blog-publishing-spec.md`; tests
  `tests/unit/test_blog_rules.py`, `tests/unit_dev/test_blog_api.py` (permission matrix in IAM mode),
  `tests/unit_dev/test_blog_public_api.py`.
- **Knowledge Center** (`ews/knowledge`, `/api/v1/knowledge/*`, tables `taas_kb_*`): tenant-wide spaces on
  `kb-space:<id>` (`ObjectAccess`, roles `kb_space_admin` · `kb_space_editor` · `kb_space_viewer`, tenant `kb_admin`);
  visibility tenant / organization (± sub-organizations) / restricted grants `kb_space_viewer` implicitly; page tree
  (≤ 10 levels) of site documents with drafts (autosave, discard), versions on publish, restore, soft lock, owner + verification, templates,
  private attachments (storage kind `knowledge/`, 5-minute signed URLs), home / review / simple search. Module guide
  `libs/ews/src/ews/knowledge/CLAUDE.md`, API `taas-specs/knowledge/knowledge-api.md`; tests
  `tests/unit/test_knowledge_rules.py`, `tests/unit_dev/test_knowledge_api.py` (permission matrix in IAM mode).
- **File Manager** (`ews/files`, `/api/v1/files/*`, tables `taas_file_*`): drives on `drive:<id>` (`ObjectAccess`, roles
  `drive_manager` · `drive_editor` · `drive_commenter` · `drive_viewer`): organization drive (implicit role of its direct
  members), shared drives, *My files* (owner only, drive → tenant); folder / file tree (≤ 20 levels), uploads (multipart
  or direct ticket → PUT → complete), versions, trash → purge, activity. **Processing pipeline** (queue =
  `taas_file_versions.pipeline_status`, runner `FILES_PIPELINE=api|worker|off`): thumbnails / renditions in `derived/files/…`,
  metadata, checksum, text in the **local index** (`taas_file_contents.tsv`, search by content with snippets), hourly
  trash retention. **Signed delivery**: view URLs 24 h (rounded + cached, `ews.shared.SignedUrlCache`), downloads ≤ 5 min,
  revocable (drive epoch), confidential drives. Storage kinds `documents/` + `derived/` through `ews.shared.tenant_root`.
  Module guide `libs/ews/src/ews/files/CLAUDE.md`, developer guide `docs/developers/files-guide.md`, API
  `taas-specs/files/files-api.md`, architecture `taas-specs/files/files-architecture.md`; tests
  `tests/unit/test_files_{rules,derive,delivery}.py`, `tests/unit_dev/test_files_api.py` (permission matrix in IAM mode),
  `tests/unit_dev/test_files_pipeline_api.py`. Env `FILES_*` (`.env.example` §11).

