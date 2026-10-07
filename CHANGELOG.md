# Changelog — taas-server-py

All notable changes of this project. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions:
[Semantic Versioning](https://semver.org/) — below 1.0 a breaking change bumps the minor version. Each entry names the
package it changes and its new version; how to write entries: [CLAUDE.md → Changelog & versions](CLAUDE.MD).

## [Unreleased]

### Security

- `libs/ews` 0.2.0 — PPM and CRM routes require sign-in, are scoped to the request's tenant and organization and check
  RBAC permissions (taas-specs Ppm-0001 / 0002, Crm-0001 / 0002): `ews/ppm/_access.py` (`load_project`, `load_task`,
  `readable_projects`), CRM `_scope` / `_load`. A project outside the organization or unreadable → 404, readable without
  the right → 403; the creator of a project becomes its `project_admin`.
- `libs/ews` 0.2.0 — the organization of a request can come from `X-Organization-Slug` (the web URL's `/<org>/`).
- `libs/ews` 0.2.0 — CSRF guard: cookie-authenticated writes need an `Origin` from `ALLOWED_CORS_ORIGINS` or the
  API's own origin (`ews/security/_csrf.py`).
- `libs/iam` 0.2.0 — the legacy, unauthenticated `/api/v1/users/*` is no longer mounted (users are managed by the IAM
  admin API).
- `libs/ews` 0.2.0 — demo routes `/api/v1/test-apis/*` are mounted only when `ENVIRONMENT` is local / test / development.

### Changed

- `libs/ews` 0.2.0 — comment authors come from the session; workflow privacy (`assigned`) uses the session user — the
  `user_id` query parameter of the task and workflow lists is removed; a task's parent, task list and iteration must
  belong to its project (400); `org_id` in project / account bodies is ignored.
- `libs/ews` 0.2.0 — projects, tasks, comments and time logs are soft-deleted (`deleted_at`).
- `libs/db` 0.2.0 — `taas_projects.organization_id`, `taas_crm_accounts.tenant_id` / `organization_id` (migration
  `9b3e61d4a7c2`); rows created before the scoping move to the development organization (`demo`, else the oldest root
  organization).

### Fixed

- `libs/db` 0.2.0 — 17 text column defaults written as `'…'::character` were `character(1)` (`'New'` stored as `'N'`);
  defaults fixed and truncated values repaired by the migration.
- `libs/ews` 0.2.0 — malformed or unknown ids on PPM / CRM routes → 404 instead of 500.

## [0.1.0] - 2026-10-07

Baseline: the first changelog entry. There were no releases before; this summarizes the work from 2026-05-17 to
2026-10-07 (194 commits).

### Added

- EWS API from framework-agnostic controllers (`libs/ews`): FastAPI app `apps/ews_api` (:8191) and Litestar app
  `apps/ews_api_litestar`, adapters `libs/http_fastapi` / `libs/http_litestar`.
- PPM (`ews/ppm`): projects with the status catalog, 49 workflow templates and the sticky project process, workflows
  and stages, tasks, task lists, iterations, comments, time logs.
- CRM accounts with their status catalog (`ews/crm`).
- Site Builder and Media library APIs (`ews/sites`, `ews/media`), public CDN copies on publish, AI gateway (`ews/ai`).
- EWS security and RBAC: IAM session introspection or development sign-in (`ews/security`), catalog
  `ews/authz/data/ews-rbac.json` synced into `taas_casbin_rule` (`ews/authz`).
- Blob storage: contract in `foundation.blob`, service `libs/blob_service` (tenant buckets, storage resolver, public
  store), adapters `libs/blob_s3` (S3, R2, RustFS), `libs/blob_gcp`, `libs/blob_azure`.
- Resilience `libs/resiliant` (outboxes, DLQ, idempotency, schedule; `resiliant_*` tables shared with taas-server-js),
  `apps/outbox_worker`, `apps/ews_worker`.
- Database models and the single Alembic tree (`libs/db`), incl. the IAM directory tables (tenants, organizations,
  members).
- Messaging (`libs/messaging_kafka`, `libs/messaging_faststream`), rate limiting (`libs/slowapi_advanced`), key/value
  stores (`libs/store_redis`, `libs/store_memcached`), `libs/banking_core`, `libs/block-kaspa`, IAM library
  (`libs/iam`, `libs/iam_keycloak`).

[Unreleased]: https://github.com/thanhlq/taas-server-py/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/thanhlq/taas-server-py/releases/tag/v0.1.0
