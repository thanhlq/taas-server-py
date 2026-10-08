# Project

## Overview

The all eworksuite (ews) implementations i..e domain model, business logic, data dictionary,... all the ews business logic.

This project will not be dependent on any api frameworks instead of that it use foundation.http for registration of api routes and in the real api projects as apps/ews_api will be responsible for wire up of the route difinitions with real api framework as fastapi or litestar

The structure:
- core: contain all core things as repositories, services,.. for users, team, tenants,...
- authz: business RBAC — roles / permissions catalog `authz/data/ews-rbac.json` (project, site, drive, knowledge
  space and blog roles + the business rights of `org_admin` / `org_member`), synced into `taas_casbin_rule` at EWS
  API start-up (`sync_catalog`), decision `can(user, resource_domains(...), 'ppm.task', 'update')`, grants `grant` /
  `revoke`. **Same RBAC as the IAM (Node)**: both catalogs shipped (`iam-rbac.json`, `rbac-cases.json` are copies —
  `taas-tools/rbac-catalogs/sync_rbac_catalogs.py`), `effective_policies` merge, 60 s policy cache —
  `taas-specs/iam/specs/authorization-rbac-spec.md` §7. Edit the JSON, run the sync, run both test suites
- access: `ObjectAccess` for business objects with their own RBAC domain (`drive:`, `kb-space:`, `blog:`, …): domains,
  404 / 403 rule, implicit roles, UI permissions, creator grant; generic members routes (`list_members`,
  `member_candidates`, `upsert_member`, `remove_member`, `object_roles`, schemas `MemberOut`, …)
- shared: helpers of every module — `parse_uuid`, `utcnow`, `sign_token`, `raw_response`, `read_form`, materialized-path
  trees (`child_path`, `check_move`, `move_subtree`, …), `clean_seo`, `user_names`, `ConflictException` (409 +
  `extra.code`), URL slugs `slugify` (one rule for every app and the web), private storage `tenant_root` /
  `use_storage` (storage resolver). Public CDN copies of media: `ews.media` (`asset_map`, `publish_assets`,
  `remove_public_scope`). Reuse first: `taas-specs/platform/architecture/building-blocks.md`
- blog: Blog app (`/api/v1/blog`, `taas_blog_*`) — blogs, posts + revisions, workflow, taxonomy, authors, public
  addresses + releases read by the site renderer (`/api/v1/sites-internal/blog-*`); guide `src/ews/blog/CLAUDE.md`
- knowledge: Knowledge Center (`/api/v1/knowledge`, `taas_kb_*`) — tenant-wide spaces with visibility (implicit
  `kb_space_viewer`), page tree, drafts / versions of site documents, soft lock, verification, templates, private
  attachments, home / search; guide `src/ews/knowledge/CLAUDE.md`
- files: File Manager (`/api/v1/files`, `taas_file_*`) — organization / shared / personal drives (implicit roles),
  folder tree, uploads + versions in `documents/`, signed downloads, trash, activity, search; guide `src/ews/files/CLAUDE.md`
- ews: for eworksuite
- ....

## Rules

Any updates or modification must respect the following rules:
- Must be easy for developer to read, navigate and understand
- Me be reusable, scalable, extensible and very good folder structure
- Must be crafted carefully because this platform is used for serious user cases as banking, finance,..
- Update code must update unit tests, e2e tests, specs documents
- Update api, types,... must regenerate types.gen.ts (in root CLAUDE.md, session 3) and reupdate the web project taas-web-official if needed (run e2e tests)
