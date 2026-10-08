# ews.files — File Manager backend

API `/api/v1/files/*` (OpenAPI tag `File Manager`), tables `taas_file_*` (`libs/db/src/db/models/files`, revision
`3f1a9c7e2b10`). Specs: `taas-specs/files/` (app spec, `files-api.md`, `decisions.md`, `roadmap.md`).

## Files

| File | What |
| --- | --- |
| `_rules.py` | Pure rules (unit-tested): names, *keep both* names, types / quick tabs, safe inline types, `Content-Disposition`, `MAX_DEPTH = 20` |
| `_access.py` | `DRIVES = ObjectAccess('drive', 'files.drive', 'files', default_role='drive_editor')`, `DriveCtx` (drive + organization path + implicit role), `load_drive` / `load_node` (404 / 403), `log_oversight` (`admin.access`) |
| `_drives.py` | Lazy organization drive / *My files* (`INSERT … ON CONFLICT DO NOTHING`), `visible_drives`, shared drive CRUD, outputs |
| `_nodes.py` | Tree (folders, rename, move, copy, stars), trash → restore → purge, `purge_expired`, outputs |
| `_uploads.py` | API multipart, direct ticket / PUT / complete (staging key), versions (restore, comment), download URLs |
| `_storage.py` | Keys (`documents/drives/{drive}/{node}/{version}`, `documents/staging/…`), signed content / upload tokens, URLs |
| `_views.py` | Home, recent, starred, search over the readable drives |
| `_activity.py` | `record(...)` (allowed `ACTIONS`), `list_activity` |
| `schemas.py` | Wire types, all prefixed `File` / `Files` (OpenAPI component names are global) |
| `controllers/` | `FilesAppController` (`/access`, `/roles`, views, signed URLs), `FilesDrivesController` (`/drives`), `FilesNodesController` (`/nodes`) |

## Rules

- Every handler: `scope = await current_scope()`, then `load_drive` / `load_node` with the needed `files.*` permission.
  A drive is checked on **its own** organization chain (`DriveCtx.org_path`; `''` for *My files* = drive → tenant).
- Implicit roles, not grants: direct members of the organization → the organization drive's `default_member_role`;
  the owner of *My files* → `drive_manager`. Members / roles: generic `ews.access` functions only.
- Storage only through `ews.shared.tenant_root` + `kind_key('document', …)` — never a bucket. Objects are immutable
  (one key per version id); direct uploads land on a staging key and are copied on *complete*.
- Lists and searches are always restricted to `visible_drives` (permission-trimmed); a foreign id is a 404.
- Every change, download and oversight access writes an activity row (`_activity.ACTIONS`).
- Deleting for good (`purge_subtree`): rows get `deleted_at`, storage objects are removed, activity is kept.

## Tests

`libs/ews/tests/unit/test_files_rules.py` (pure), `libs/ews/tests/unit_dev/test_files_api.py` (local DB, memory storage
via `ews.shared.use_storage`, permission matrix in IAM mode).

## Not here yet (roadmap F1 web, F2 – F4)

Worker schedule of `purge_expired`, resumable multipart uploads, malware scan (`scan_status = skipped`), item ACLs /
sharing / links (F2), thumbnails / Office previews (F3), project & task sources (F4), outbox events.
