# ews.knowledge — Knowledge Center

App `knowledge`, API `/api/v1/knowledge` (tag *Knowledge Center*), tables `taas_kb_*` (`db.models.knowledge`).
Spec: `taas-specs/knowledge/` (app spec, `knowledge-api.md`, `decisions.md`, `roadmap.md`). Requirement ids `Kb-xxxx`.

## Files

| File | Content |
| --- | --- |
| `_access.py` | `KB_SPACES = ObjectAccess('kb-space', 'kb.space', 'kb')`, `load_space` / `load_page` (404 / 403, drafts hidden from readers), `readable_spaces` (batched list trimming), `SpaceAccess.member_scope` |
| `_rules.py` | Pure rules: limits (`MAX_DEPTH` 10, `LOCK_TTL` 2 min, review 180 / 14 days, 50 MB, 5 min URLs), `implicit_role`, `page_status`, `review_status`, `visible_tree_ids`, slugs, search helpers |
| `_spaces.py` · `_pages.py` · `_revisions.py` | Spaces · page tree (create, move, delete, detail) · drafts, publish, discard (draft back to the published version), versions, restore, soft lock, verify |
| `_attachments.py` · `_home.py` | Private attachments + signed URLs · home, review list, simple search |
| `_document.py` · `_templates.py` | Site document adapter (`ews.sites._document`) · built-in templates `data/templates/*.json` |
| `schemas.py` · `controllers/` | Wire types (all prefixed `Kb…` — names are global in OpenAPI) · `_app.py`, `_spaces.py`, `_pages.py` |

## Rules

- Access: domains `kb-space:<id>` → **the space's organization** chain → `tenant:<id>`. Visibility gives
  `kb_space_viewer` implicitly (tenant → everyone in the tenant; organization → its members, + sub-organizations with
  `include_sub_orgs`; restricted → explicit members). Org admins of the space's organization (or ancestors), `kb_admin`
  and `tenant_admin` hold every right. Never load a space / page without `load_space` / `load_page`.
- Spaces are **tenant-wide**: found by id in the caller's tenant, whatever the URL organization; created in the request
  organization by `kb.space:create` (org admin / `kb_admin`), the creator becomes `kb_space_admin`. Members routes are the
  generic `ews.access` ones, run with `member_scope(scope)` (candidates = the space organization's subtree).
- Drafts (never-published pages, unpublished changes, revisions) are for editors (`kb.page:update`); readers get the
  published version and title, a tree of published pages under published ancestors, published search results.
- Draft = one revision with `version` null, autosaved in place by the same author; another author or a save after a
  publish starts a new one; `base_revision_id` → 409 `stale_draft`. Publish = draft becomes version n (immutable),
  `search_text` refreshed, first publish = first verification. Discard = `draft_revision_id` back to the published
  revision (409 `never_published` / `no_changes`; the discarded draft stays a revision). Soft lock `locked_by` /
  `locked_until` → 409 `locked`.
- Page bodies are site documents: validate with `check_document`, never store unvalidated JSON.
- Attachments: storage kind `knowledge/` through `ews.shared.tenant_root` (the storage resolver), key
  `knowledge/<space>/<attachment>/<version>/original[.ext]`; download = permission check, then a 5-minute URL
  (`presigned`, or `proxy` → `GET /files/{token}`, signed `kb.file`). Deletes are soft (blobs kept for the retention job).

## Tests

`libs/ews/tests/unit/test_knowledge_rules.py` (pure) · `libs/ews/tests/unit_dev/test_knowledge_api.py` (local DB:
flows + IAM-mode permission matrix). Next: share links (K3), search & Ask (K4) — see `roadmap.md`.
