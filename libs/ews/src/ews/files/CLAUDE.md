# ews.files — File Manager backend

API `/api/v1/files/*` (OpenAPI tag `File Manager`), tables `taas_file_*` (`libs/db/src/db/models/files`, revisions
`3f1a9c7e2b10` → `8c4f2d6b1a95`). Specs: `taas-specs/files/` (app spec, `files-architecture.md`, `files-api.md`,
`decisions.md`, `roadmap.md`). Developer guide: `docs/developers/files-guide.md`.

## Files

| File | What |
| --- | --- |
| `_rules.py` | Pure rules (unit-tested): names, *keep both* names, types / quick tabs, safe inline types, `viewer_kind`, `Content-Disposition`, `prefix_tsquery` (content search), `MAX_DEPTH = 20` |
| `_access.py` | `DRIVES = ObjectAccess('drive', 'files.drive', 'files', default_role='drive_editor')`, `DriveCtx` (drive + organization path + implicit role), `load_drive` / `load_node` (404 / 403), `log_oversight` (`admin.access`) |
| `_drives.py` | Lazy organization drive / *My files* (`INSERT … ON CONFLICT DO NOTHING`), `visible_drives`, shared drive CRUD, sensitivity, `revoke_links` (URL epoch), outputs |
| `_nodes.py` | Tree (folders, rename, move, copy, stars), trash → restore → purge (versions + variants + index rows), `purge_expired`, outputs (with thumbnails) |
| `_uploads.py` | API multipart, direct ticket / PUT / complete (staging key), versions (restore, comment), downloads, `preview` (viewer payload) |
| `_storage.py` | Keys (`documents/drives/{drive}/{node}/{version}`, `documents/staging/…`, `derived/files/{node}/{version}/{variant}.webp`), put / delete, upload tokens |
| `_delivery.py` | Signed view / download URLs: policy per drive sensitivity, rounded expiry + `SignedUrlCache`, revocation state (`link_alive`, epoch), `/content` response (ETag / 304, Range / 206) |
| `_derive.py` | Pure processing of bytes (unit-tested): `sniff`, image / PDF (PDFium) / Office / text → variants, placeholder, text, metadata |
| `_pipeline.py` | Queue = `taas_file_versions.pipeline_status`: claim (`SKIP LOCKED`), `process_version`, `run_pipeline` / `drain`, retries, `reprocess`, `run_retention`, background runner (`start_pipeline`, `stop_pipeline`, `kick`) |
| `_previews.py` | Thumbnails of listed items (one query + cached view URLs) |
| `_views.py` | Home, recent, starred, search (names + local full-text index, snippets) over the readable drives |
| `_activity.py` | `record(...)` (allowed `ACTIONS`), `list_activity` |
| `schemas.py` | Wire types, all prefixed `File` / `Files` (OpenAPI component names are global) |
| `controllers/` | `FilesAppController` (`/access`, `/roles`, views, signed URLs), `FilesDrivesController` (`/drives`), `FilesNodesController` (`/nodes`) |

## Rules

- Every handler: `scope = await current_scope()`, then `load_drive` / `load_node` with the needed `files.*` permission.
  A drive is checked on **its own** organization chain (`DriveCtx.org_path`; `''` for *My files* = drive → tenant).
- Implicit roles, not grants: direct members of the organization → the organization drive's `default_member_role`;
  the owner of *My files* → `drive_manager`. Members / roles: generic `ews.access` functions only.
- Storage only through `ews.shared.tenant_root` + `kind_key('document' | 'derived', …)` — never a bucket. Objects are
  immutable (one key per version id / variant); direct uploads land on a staging key and are copied on *complete*.
- URLs only through `_delivery.signed_url` **after** the permission check (view = 24 h on standard drives, downloads
  ≤ 5 min); anything that removes access (trash, purge, member removal, sensitivity) forgets the link states and / or
  bumps the drive epoch.
- New versions are `pipeline_status = pending` (the queue): never process files inside a request; keep `_derive` pure.
- Lists and searches are always restricted to `visible_drives` (permission-trimmed); a foreign id is a 404.
- Every change, download, preview and oversight access writes an activity row (`_activity.ACTIONS`).

## Tests

`libs/ews/tests/unit/test_files_rules.py`, `test_files_derive.py`, `test_files_delivery.py` (pure),
`libs/ews/tests/unit_dev/test_files_api.py`, `test_files_pipeline_api.py` (local DB, memory storage via
`ews.shared.use_storage`, permission matrix in IAM mode, pipeline driven with `drain`).

## Not here yet (roadmap F1 – F6)

Resumable multipart uploads, malware scan (`scan_status = skipped`), lazy heavy jobs (Office → PDF, video posters /
HLS, OCR), reconciler, private CDN, item ACLs / sharing / links (F2), project & task sources (F4), outbox events, AI (F6).
