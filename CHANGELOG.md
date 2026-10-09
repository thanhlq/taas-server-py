# Changelog — taas-server-py

All notable changes of this project. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions:
[Semantic Versioning](https://semver.org/) — below 1.0 a breaking change bumps the minor version. Each entry names the
package it changes and its new version; how to write entries: [CLAUDE.md → Changelog & versions](CLAUDE.MD).

## [Unreleased]

### Added

- `libs/ews` 0.2.0 — Knowledge Center: `POST /api/v1/knowledge/pages/{id}/draft/discard` — the draft goes back to the
  published version (409 `never_published` / `no_changes` / `locked`), the discarded draft stays in the history (Kb-0302,
  ADR-9).
- `libs/ews` 0.2.0 — site documents accept rich text checklists (`taskList` / `taskItem`, `checked` boolean) in
  `validate_document`; their text is in `plain_text` (search, AI context) — Site-0104.

- `libs/ews` 0.2.0 — **File Manager F3 core** (taas-specs/files File-0302, File-0400, File-0500 … File-0605; ADR-9 … ADR-13):
  processing **pipeline** (queue = `taas_file_versions.pipeline_status`, `SKIP LOCKED` claims, retries, `drain`,
  `run_pipeline`, `start_pipeline` / `stop_pipeline`, hourly `purge_expired`) with pure `_derive` (type sniffed from
  the content; WebP thumbnails, renditions and placeholders for images, PDF page 1 via PDFium, Office / OpenDocument
  covers; text of PDF / Office / text files; metadata: dimensions, pages, title, author, date taken, words; SHA-256 of
  direct uploads); **local index** search by content (`taas_file_contents.tsv`, prefix queries, `match`, highlighted
  `snippet`, `rank`; trigram index on names); **cached signed URLs** (view URLs 24 h on standard drives, rounded
  windows, `ETag` / 304, `Range` / 206), **revocation** (`POST /drives/{id}/links/revoke`, automatic on member removal
  and sensitivity change, trashed / purged items), drive `sensitivity` (`standard` · `confidential`);
  `GET /nodes/{id}/preview`, `POST /nodes/{id}/reprocess`; item fields `preview_status`, `thumbnail_url`,
  `placeholder`; version fields `pipeline_status`, `pipeline_error`, `preview_status`, `index_status`, `meta`; activity
  `drive.links_revoked`, `file.reprocessed`; settings `FILES_VIEW_URL_TTL_HOURS`, `FILES_PIPELINE*`,
  `FILES_INDEX_MAX_CHARS`. New dependency `pypdfium2`.
- `libs/ews` 0.2.0 — `ews.shared.SignedUrlCache` + `rounded_expiry`: sign once per window, same URL for every caller
  (in-process LRU, Redis for provider signatures).
- `libs/db` 0.2.0 — migration `8c4f2d6b1a95`: `taas_file_previews`, `taas_file_contents` (generated `tsvector`, GIN),
  pipeline columns of `taas_file_versions`, trigram index `ix_taas_file_nodes_name_trgm` (when `pg_trgm` is available).
- `apps/ews_api` 0.2.0, `apps/ews_api_litestar` 0.2.0 — the lifespan starts / stops the File Manager pipeline
  (`FILES_PIPELINE=api`, default).
- `apps/ews_worker` 0.2.0 — runs the File Manager pipeline when `FILES_PIPELINE=worker` (initialises the storage
  resolver); depends on `ews` and `blob_service`.
- Docs: `docs/developers/files-guide.md`; tests `test_files_derive.py`, `test_files_delivery.py`,
  `test_files_pipeline_api.py`.

- `libs/ews` 0.2.0 — **File Manager** API `ews/files` (`/api/v1/files`, taas-specs F1 + drive roles of F2): organization
  drives (implicit role of the organization's members), shared drives with members, *My files*, folder / file tree,
  multipart and direct upload (storage kind `document`), versions, signed downloads / previews, trash + restore + purge,
  activity, stars, recent, search.
- `libs/ews` 0.2.0 — **Knowledge Center** API `ews/knowledge` (`/api/v1/knowledge`, K1 + K2): spaces with tenant /
  organization (+ sub-organizations) / restricted visibility (implicit viewer), members, page tree (≤ 10 levels, move /
  reorder), drafts + published versions, soft lock, verification and review list, 6 templates, attachments (storage
  kind `knowledge`), home and search.
- `libs/ews` 0.2.0 — **Blog** API `ews/blog` (`/api/v1/blog`, B1 + B2 transitions): blogs, members, posts with draft /
  published revisions, autosave, soft lock, workflow (submit, request changes, approve, publish / update, schedule,
  unpublish, archive), categories, tags, author profiles; `publish_due(now)` for the scheduler.
- `libs/ews` 0.2.0 — `ews.access`: `ObjectAccess` (object → organization chain → tenant domains, 404 / 403 rule,
  implicit roles, UI permissions, creator grant) + generic members routes (`list_members`, `member_candidates`,
  `upsert_member`, `remove_member`, `object_roles`, schemas `MemberOut` …).
- `libs/ews` 0.2.0 — `ews.shared`: materialized-path trees (`child_path`, `check_move`, `move_subtree` …), private storage
  (`use_storage`, `storage_resolver`, `tenant_root`), `clean_seo`, `user_names`, `ConflictException`,
  `path_segment_taken` (sites and blogs share the organization's address).
- `libs/ews` 0.2.0 — RBAC: roles `drive_*`, `kb_space_*`, `kb_admin`, `blog_*` and `org_admin` rights on `files.*`,
  `kb.*`, `blog.*` (`ews-rbac.json`); **one RBAC with Node**: the IAM catalog (`authz/data/iam-rbac.json`) and the shared
  decision vectors (`rbac-cases.json`) ship here too, `iam_catalog()`, `effective_policies` (merge rule),
  `resource_domains(objects=…)`, catalog validation of role keys / scopes, policies cached 60 s.
- `libs/db` 0.2.0 — tables `taas_file_*` (5), `taas_kb_*` (4), `taas_blog_*` (8); migrations `3f1a9c7e2b10` →
  `5c2d8e4a1f63` → `7e4b2a9d6c15`.
- `libs/ews` 0.2.0 — **Blog public reading** (taas-specs/blog/blog-publishing-spec.md, B3 core): post addresses follow the
  title until the first publication or a manual edit (`slug_auto`), are frozen afterwards and keep `former_slugs`
  (public 301); reserved post slugs; `public_url` on blogs and posts, `live` on posts, the draft autosave answer carries
  the address; blog releases (`taas_blog_releases`, immutable index snapshot rebuilt on every public change, last 20
  kept); post media copied to the public CDN at publish; renderer API `GET /api/v1/sites-internal/blog-releases/{id}`,
  `/blog-posts/{revisionId}` and blog routes in `/routes` (`RouteOut.kind = 'blog'`, `blog_id`; `redirect_status` for
  redirect routes).
- `libs/ews` 0.2.0 — rich text **tables** in site documents (Site-0104): `ews/sites/_document.py` accepts `table` /
  `tableRow` / `tableHeader` / `tableCell` with the structure rules (header row, same cell count, no merged cells) and
  the catalog limits `maxTableColumns` 20 / `maxTableRows` 500; cell text counts for search and reading time.
- `libs/ews` 0.2.0 — shared `ews.shared.slugify` (transliteration of đ, ß, æ, ø, ł, œ, þ …) used by sites, blog, knowledge,
  CRM; shared media publishing `ews.media` (`asset_map`, `publish_assets`, `remove_public_scope`) used by sites and blog;
  `ews.sites.register_route_source` (other apps add renderer routes).
- `libs/db` 0.2.0 — migration `b3d9f1a2c4e7`: `taas_blog_posts.slug_auto` / `former_slugs`, `taas_blog_post_revisions.assets`
  / `cdn_origin`, `taas_blog_blogs.live_release_id`, table `taas_blog_releases`.
- Tests: RBAC parity on the shared vectors, unique wire type names (`test_schema_names.py`), object access, API tests
  with permission matrices for the three apps (`libs/ews/tests/unit_dev`).

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

- `libs/ews` 0.2.0 — File Manager: `GET /search` returns `FileSearchPage` (hits = items + `match`, `snippet`, `rank`) and
  matches content too (`match=name` for names only); inline downloads of standard drives are view URLs (24 h, cacheable);
  `/content/{token}` sends `private, max-age, immutable` for view URLs and answers 404 for revoked links.

- `libs/ews` 0.2.0 — comment authors come from the session; workflow privacy (`assigned`) uses the session user — the
  `user_id` query parameter of the task and workflow lists is removed; a task's parent, task list and iteration must
  belong to its project (400); `org_id` in project / account bodies is ignored.
- `libs/ews` 0.2.0 — projects, tasks, comments and time logs are soft-deleted (`deleted_at`).
- `libs/db` 0.2.0 — `taas_projects.organization_id`, `taas_crm_accounts.tenant_id` / `organization_id` (migration
  `9b3e61d4a7c2`); rows created before the scoping move to the development organization (`demo`, else the oldest root
  organization).

- `libs/ews` 0.2.0 — the Site Builder reuses the shared pieces: member schemas (`ews.access.schemas`), SEO / user labels
  / 409 errors (`ews.shared`), and refuses a slug already used by a blog of the organization; the media library uses
  the shared private-storage override (`ews.media.use_storage` = `ews.shared.use_storage`).

### Fixed

- `libs/http_litestar` 0.1.1 — the Litestar API builds again (ADR-P2 parity with FastAPI): path parameters in a
  controller prefix are typed, routes without an explicit status answer 200 like FastAPI (Litestar defaulted POST to
  201 and DELETE to 204, which refused DELETE handlers with a body), no-content routes are re-wrapped as `-> None`;
  unit tests in `libs/http_litestar/tests/unit`.
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
