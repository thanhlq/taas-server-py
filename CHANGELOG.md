# Changelog — taas-server-py

All notable changes of this project. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions:
[Semantic Versioning](https://semver.org/) — below 1.0 a breaking change bumps the minor version. Each entry names the
package it changes and its new version; how to write entries: [CLAUDE.md → Changelog & versions](CLAUDE.MD).

## [Unreleased]

### Added

- `libs/ews` 0.2.0 — **PPM intake V2** (intake spec, ADR-47): request forms (organization or project, internal or
  public) with a draft definition — fields, show-if logic on the automation operators, defaults, mapping to item fields,
  title template, routing rules — and immutable published versions; close, rotate the public link, routing test,
  responses CSV / XLSX; submit (one transaction, `Idempotency-Key`, `invalid_answers` + `extra.errors`) creating the
  request item in the queue as the form owner with the requester as actor; public form + submit (honeypot, IP-hash
  limits, 429) and tracking page (token shown once, SHA-256 stored); requests inbox · mine · all, detail (requester view
  trimmed), accept as item / in place / project, decline, merge duplicate, ask for info, replies (comments `privacy =
  requester`) and internal notes, withdraw; requester-facing status mirrored from the item / result (§5.4,
  `ppm.request.status_changed`); notification kinds `ppm:request_submitted` · `ppm:request_update` · `ppm:request_reply`;
  routes `/api/v1/ppm/forms*`, `/requests*`, `/public-forms/*`, `/public-requests/*`. Shared: `ews.shared.file_response`
  (downloads), `random_id` · `random_token` · `token_hash` · `client_ip_hash` (sign-in free endpoints);
  `ews.ppm._projects.create_project` (the project create path of the API and intake).
- `libs/db` 0.2.0 — migration `67ade2acd43b`: `taas_ppm_forms`, `taas_ppm_form_versions`, `taas_ppm_requests`.
- Tests `tests/unit/test_ppm_intake_forms.py`, `tests/unit_dev/test_ppm_v2_intake_api.py`.
- `libs/ews` 0.2.0 — **PPM automation V2** (automation spec Part B, ADR-46): project rules WHEN · IF · THEN validated
  with JSON paths (`_automation_rules.py`), event rules run in-process as the owner, relative (due in, overdue by, start
  reached, no activity) and scheduled rules from the job `ppm.automation_tick`, actions notify · create item (+ link) ·
  assign (round robin) · set field · move stage · set due · add checklist · add comment · start approval, run log with
  before / after, undo (409 `undo_conflict`), dry-run of saved / draft rules, loop guard (depth 3, own runs), 100 runs /
  hour, auto-pause after 3 failures (`ppm:automation_failed`), template gallery, routes `/api/v1/ppm/automation-*`;
  `ews.security.scope_of` (act as a user outside a request), `_item_update.update_item` (the task update path moved out of
  the controller), `_events.acting_as`; RBAC `ppm.automation` actions `create · read · update · delete`.
- `libs/db` 0.2.0 — migration `3b4e530684c4`: `taas_ppm_automation_rules`, `taas_ppm_automation_runs`.
- Tests `tests/unit/test_ppm_automation_rules.py`, `tests/unit_dev/test_ppm_v2_automation_api.py`.
- `libs/ews` 0.2.0 — **PPM dashboards & reports V2** (dashboards spec, ADR-45): widget query model `_widgets.py`
  (items · projects · time · trend · KPI · lists · milestones · health · health matrix · activity · approvals · series,
  measures / metrics, group by + stack by, filters, viewer scope, one `{columns, rows, total, as_of}` shape), system
  dashboards (`system:ppm_overview`, `system:my_dashboard`, `system:project_overview`), custom dashboards (12-column
  layout ≤ 24 widgets, version, copy, shares, soft delete, `ppm.dashboard.*` events), widget data / preview / export,
  V2 reports (status, overdue items, time by person, time by project) with CSV / XLSX, daily project statistics +
  `/projects/{id}/metrics/series` (burnup · burndown · throughput) + job `ppm.daily_stats`, PPM overview tiles (`open`,
  `at_risk`, `my_overdue`, `my_due_week`); `ews.shared.to_xlsx` (typed cells, no formulas); RBAC `ppm.dashboard`
  actions `create · read · update · delete` (`org_member` creates personal dashboards).
- `libs/db` 0.2.0 — migration `339ae1dc6f78`: `taas_ppm_dashboards`, `taas_ppm_dashboard_shares`,
  `taas_ppm_project_daily_stats`.
- Tests `tests/unit/test_ppm_dashboards_rules.py`, `tests/unit_dev/test_ppm_v2_dashboards_api.py`.
- `libs/ews` 0.2.0 — **PPM project health V2** (health spec, ADR-23 / ADR-44): pure engine `ews/ppm/_health_engine.py`
  (schedule S1–S7, resources R1, scope C1, quality Q1–Q3, risk K3, budget ⚪ until V3; reasons with codes, params and
  evidence items; overall ADR-23), daily snapshots recomputed on read when stale and by the job `ppm.health_refresh`
  (60 s debounce, new day, override expiry, 2-year retention), `ppm.project.health_changed` · `health_override_*`,
  manual override (reason, expiry, author notified `ppm:health_changed`), policy = organization + project exception
  (thresholds, dimensions, defect item types, versions); routes `/projects/{id}/health[/history|/recalculate|/override]`,
  `/ppm/health-policy`, `/projects/{id}/health-policy`; project lists / details return `health`; RBAC `ppm.health`
  gains `override`, new `ppm.health_policy` (update, `org_admin`).
- `libs/db` 0.2.0 — migration `106f9b722e00`: `taas_ppm_health_snapshots`, `taas_ppm_health_overrides`,
  `taas_ppm_health_policies`.
- Tests `tests/unit/test_ppm_health_engine.py`, `tests/unit_dev/test_ppm_v2_health_api.py`.
- `libs/ews` 0.2.0 — **PPM time tracking V2** (time-tracking spec, ADR-43): effort on the server (manual / auto remaining,
  forecast, variance, roll-ups stored on items, alert bands with hysteresis → `ppm.task.effort_variance_crossed` +
  `ppm:effort_variance`); entries `/api/v1/ppm/time-entries` with rules (minutes > 0, daily maximum, no future — after today at UTC+14, so every time zone logs its own today — lock date,
  billable only where allowed, description rule, 409 `locked`), soft delete, corrections (reversal + corrected entry);
  timer (one per person, rounding, auto-stop job + `ppm:timer_auto_stopped`); weekly timesheets (lazy, grid cells, copy
  last week, submit, approval per project section through the approvals engine — subject `timesheet`, no
  self-approval, `auto` mode — locks, reopen; `ppm:timesheet_approval` / `ppm:timesheet_decided`); `GET
  /tasks/{id}/effort`; project time + CSV; categories; settings `time.*`; RBAC resource `ppm.time_entry`; item
  `remaining_minutes`. Item time logs go through the same rules; their response is now `PpmTimeEntryOut`.
- `libs/db` 0.2.0 — migration `8e88de5c0d0e`: `taas_ppm_timesheets`, `taas_ppm_time_categories`, time-entry columns on
  `taas_timelogs` (`entry_date`, scope, category, source, timesheet, lock, correction, review; existing rows backfilled,
  statuses lowercased), effort columns on `taas_tasks`.
- Tests `tests/unit/test_ppm_effort.py`, `tests/unit_dev/test_ppm_v2_time_api.py`.
- `libs/ews` 0.2.0 — **PPM transition rules + team workflows** (workflow standard, Ppm-0201…0206): stages take
  `allowed_next_stage_ids`, `require_assignee`, `require_due_date`, `auto_assign` + `default_assignee_id`; moves refused
  with 409 `transition_not_allowed` / `stage_requirements` (*complete* picks an allowed done stage, *reopen* is free);
  workflow privacy `team` + `team_id`, `viewer_member`, `GET /api/v1/ppm/teams`.
- `libs/ews` 0.2.0 — **PPM V2 schedule** (schedule spec, ADR-14 / 41 / 42): pure engine `ews/ppm/_schedule_engine.py`
  (working days Mon–Fri, forward pass FS · SS · FF · SF + lag / lead, constraints ASAP · SNET · MSO · FNLT, manual vs
  auto items, forecast at today, backward pass → total float / critical path, summary roll-ups, violations, "why this
  date", cycle check, duration-weighted progress; ≈ 50–70 ms for 2 000 items + 4 000 links); phases
  (`/projects/{id}/phases`, order); item links `/tasks/{id}/dependencies` (400 `invalid_link` · `dependency_cycle` with
  the path); `GET /projects/{id}/schedule` (Gantt payload), `PATCH …/schedule/settings` + `POST …/schedule/preview`
  (manual / auto), `POST …/schedule/changes` (Gantt drops on `base_version`, 409 `stale_schedule`); items take
  `phase_id`, `duration_days`, `schedule_mode`, `constraint_type` / `constraint_date` (+ `started_at`), 400
  `invalid_dates`; auto projects recalculate in the same transaction (subscriber) and write the plan back
  (`ppm.schedule.recalculated`); a new start on an auto item = SNET; links dropped on delete / move;
  `ppm.phase.*`, `ppm.item_link.*`, `ppm.milestone.reached`; templates / duplicates copy phases, links and schedule
  fields; RBAC resource `ppm.schedule` (read · update).
- `libs/db` 0.2.0 — migration `253f21d9f40e`: `taas_ppm_phases`, `taas_ppm_work_item_links`, `taas_tasks.phase_id` ·
  `duration_days` · `schedule_mode` · `constraint_type` · `constraint_date` · `started_at`, `taas_projects.schedule_version`
  (milestones made one-date).
- Tests `tests/unit/test_ppm_schedule_engine.py`, `tests/unit_dev/test_ppm_v2_schedule_api.py`.

- `libs/ews` 0.2.0 — **PPM V2 work model** (work-model spec, ADR-13 / 28 / 30 / 39 / 40): item type library per
  organization (seeded from the universal template; custom types; 9 behaviours — milestone = one date without estimate,
  RAID / request out of progress, approval = done through its approval; 409 `in_use`), custom fields (10 types, stable
  option ids, bindings per item type / project, required on create / before done, values on items `custom_fields`,
  `cf_*` filters, 400 `invalid_fields`), checklist templates (apply, save from an item, type default), generic approvals
  (subjects registry, steps any / all, policies, decide / delegate / cancel / resubmit, history, snapshot vs current;
  My Work source `approval`; notifications `ppm:approval_requested` / `ppm:approval_decided`), project templates (save
  as template with roles, create from template with working-day shifts, duplicate), recurring items (RRULE subset, next
  occurrence on completion), completion guards (`fields_required`, `approval_pending`, `approval_required`).
- `libs/db` 0.2.0 — migration `b6c587d4a357`: `taas_ppm_item_types`, `taas_ppm_custom_fields` (+ bindings, values),
  `taas_ppm_approvals` (+ approvers, events, policies), `taas_tasks.behaviour` (backfilled), `recurrence_rule`,
  `created_from_template_item_id`, checklist templates scoped by tenant + organization.
- Tests `tests/unit/test_ppm_work_model_rules.py`, `tests/unit_dev/test_ppm_v2_work_model_api.py`.

- `libs/ews` 0.2.0 — **PPM V1** (taas-specs/ppm roadmap V1, ADR-34 … 38): domain events `ews/ppm/_events.emit`
  (audit row `taas_ppm_audit_events` + outbox message + in-process subscribers, one transaction); capability levels +
  description editors per organization (`GET` · `PATCH /api/v1/ppm/settings`, default ⭐⭐, 403 `capability_disabled`);
  project members (`/api/v1/projects/{id}/members`, `member-candidates`, `/api/v1/ppm/roles`); subtasks with roll-ups
  (dates, progress weighted by estimates, ≤ 3 levels), `progress_mode`, complete / reopen (`?cascade`, mandatory
  checklist steps), move to another project, owner + collaborators (`PUT /tasks/{id}/assignees`); checklists API
  (mandatory, assignee, due date, order, convert to subtask); task + project comments with sanitized rich text,
  `@` mentions, edit, soft delete; Activity (`/tasks/{id}/activity`, `/projects/{id}/activity`); project / item files as
  File Manager source drives + web links; My Work (`/api/v1/ppm/my-work/*`: buckets, plans, snooze, reschedule, quick
  add into the personal Inbox project, settings); `/api/v1/ppm/overview`, `/projects/{id}/metrics`; `POST
  /projects/bulk`, `GET /projects/export.csv`, `GET /tasks/export.csv`; project PATCH `clear` + `settings`
  (`editors`, `notifications.off`); item `description_doc` (site document, ADR-35).
- `libs/ews` 0.2.0 — **platform notifications** `ews.notifications` (`/api/v1/notifications/*`: inbox, unread count,
  read / unread / read all, preferences): kinds registered by apps, `notify` (dedup, 10-minute grouping), e-mail
  instant (coalesced) and daily / weekly digest, quiet weekends, scheduled app jobs; runner `NOTIFICATIONS_RUNNER`
  (`api` · `worker` · `off`). PPM kinds: assigned, mentioned (mandatory), commented, status changed, due soon,
  overdue, member added.
- `libs/ews` 0.2.0 — `ews.files._sources` (`register_source`, `ensure_source_drive`, `ensure_source_folder`): File
  Manager drives owned by another app's object (`kind = project`), access delegated to it; `ews.shared._html`
  (`sanitize_html`, `html_to_text`, `mentioned_users`; new dependency `nh3`). RBAC catalog: `ppm.settings`,
  `ppm.item_type`, `ppm.custom_field`, `ppm.checklist_template`, `ppm.template`, `ppm.approval`, `ppm.form`,
  `ppm.request`, `ppm.timesheet`, `ppm.health`, `ppm.automation`, `ppm.dashboard`.
- `libs/db` 0.2.0 — migrations `4d7a1c9e5b32` (PPM V1: `taas_ppm_settings`, `taas_ppm_audit_events`,
  `taas_ppm_mentions`, `taas_ppm_attachments`, `taas_ppm_my_work_plans`, `taas_ppm_user_settings`,
  `taas_notifications`, `taas_notification_deliveries`, `taas_notification_preferences`,
  `taas_notification_user_settings`; task roll-up / collaboration columns, project `kind`, file drive `kind = project`)
  and `a6c3e8b1d742` (`taas_tasks.description_doc`).
- `apps/ews_api` 0.2.0, `apps/ews_api_litestar` 0.2.0 — the lifespan starts / stops the notifications runner
  (`NOTIFICATIONS_RUNNER=api`, default); `apps/ews_worker` 0.2.0 — runs it when `NOTIFICATIONS_RUNNER=worker`.
- Docs: `docs/developers/ppm-events-notifications-guide.md`, `.env.example` `NOTIFICATIONS_*`; tests
  `tests/unit_dev/test_ppm_v1_api.py`.

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

- `libs/ews` 0.2.0 — PPM item type library: concurrent first requests no longer fail on the seed (`INSERT … ON CONFLICT
  DO NOTHING`).
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
