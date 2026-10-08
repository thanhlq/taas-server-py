# ews.blog — Blog app backend

API `/api/v1/blog/*` (OpenAPI tag `Blog`) + renderer API `/api/v1/sites-internal/blog-*` (tag `Blog (renderer)`),
tables `taas_blog_*` (`libs/db/src/db/models/blog`, revisions `7e4b2a9d6c15`, `b3d9f1a2c4e7`). Specs:
`taas-specs/blog/` (app spec, `blog-publishing-spec.md`, `blog-api.md`, `decisions.md`, `roadmap.md`).

## Files

| File | What |
| --- | --- |
| `_rules.py` | Pure rules (unit-tested): status machine `transition`, own-post rule `is_own` / `can_edit`, slugs (`post_slug_error` + `RESERVED_POST_SLUGS`, `term_slug_error`, `remember_slug`), `reading_time` (same rule as `@taas/doc-editor`), `clean_settings`, `clean_links`, `schedule_instant`, snapshot parts (`snapshot_post`, `public_slugs`, `snapshot_asset_refs`, `content_digest`, `public_settings`) |
| `_access.py` | `BLOG = ObjectAccess('blog', 'blog.blog', 'blog', default_role='blog_author')`, `load_blog` / `load_post` (404 / 403, `writable` → 409 on an archived blog), `require_edit`, `readable_blog_ids`, `can_open_app` |
| `_service.py` | Blogs (CRUD, slug shared with the sites of the organization, settings, `public_url`; archive / delete remove public media, restore copies them again) + helpers `pick_slug`, `free_slug`, `check_asset`, `text_field` |
| `_posts.py` | Posts: create, list (filters + counts per status), metadata, draft autosave, revisions, restore, soft lock, soft delete, media usages; addresses (`change_slug`, title-following slug, `public_url` / `live`) |
| `_workflow.py` | submit · request_changes · approve · publish (Update) · schedule · unpublish · archive · unarchive; `publish_due()` for the scheduler. `_go_live` copies the body media to the CDN and freezes the slug |
| `_taxonomy.py` | Categories (ordered), tags, author profiles (user or guest) |
| `_release.py` | Public reading: `rebuild_release` (snapshot §5 of the publishing spec, dedup, last 20), `publish_revision_media`, `remove_blog_media` / `republish_media` (CDN scope `blog/<blogId>`), `blog_url`, `is_live`, `blog_routes` (routing table), `release_snapshot`, `published_revision`, `rebuild_missing_releases()` (blogs created before releases) |
| `schemas.py` | Wire types, all prefixed `Blog` (OpenAPI component names are global) |
| `controllers/` | `BlogController` (access, roles, validate, blogs, members), `BlogPostsController`, `BlogWorkflowController`, `BlogTaxonomyController`, `BlogInternalController` (renderer key: `/blog-releases/{id}`, `/blog-posts/{revisionId}`) |

## Rules

- Every handler: `scope = await current_scope()`, then `load_blog` / `load_post` with the needed permission. Post edits
  also call `require_edit` (`blog.post:update`, or `update_own` on a post the caller created or is credited on).
  Renderer handlers call `ews.sites.require_renderer(ctx)` instead (no user session).
- Body = site document validated by `ews.sites._document.validate_document`; never store an unvalidated document.
- `published_revision_id` changes only in `_workflow._go_live`; any edit of a published post goes to a new draft
  revision (`_posts._working_draft`) — except the slug, public at once.
- Slugs: `ews.shared.slugify`; a post slug follows its title while `slug_auto` and `published_at is null`; after the
  first publication a change appends the old slug to `former_slugs` (`_rules.remember_slug`).
- **Any change of the public output calls `rebuild_release(session, blog)`** (post publish / Update / unpublish /
  archive / delete, `publish_due`, slug change of a live post, blog update, category / tag / author changes). It
  locks the blog row, writes a release only when the content changed, never for an archived / deleted blog.
- Media publishing: `ews.media._publishing` (shared with sites) — never copy CDN code here.
- Members, roles: generic `ews.access` functions — do not add blog-specific member code.
- Shared helpers used here: `ews.shared.clean_seo`, `user_names`, `ConflictException`, `slugify`; media
  `record_usages` (`app='blog'`, refs `post` / `author`); routing `ews.sites.register_route_source` (called in
  `get_blog_controllers`).

## Tests

`libs/ews/tests/unit/test_blog_rules.py` (pure), `libs/ews/tests/unit/test_shared_slug.py`,
`libs/ews/tests/unit_dev/test_blog_api.py` (local DB, permission matrix in IAM mode),
`libs/ews/tests/unit_dev/test_blog_public_api.py` (addresses, releases, renderer API, CDN copies).

## Not here yet

Scheduler worker calling `publish_due`, notifications, previews, per-post CDN cleanup on unpublish, site mount,
series, audit table. Rendering, feeds, sitemap: the site renderer (taas-web-official `apps/site-renderer`).
