# PPM events & notifications — developer guide

Backend of PPM V1: `libs/ews/src/ews/ppm` (module map: its `CLAUDE.md`) and the platform notification service
`libs/ews/src/ews/notifications`. Specs: `taas-specs/ppm/ppm-api.md` (endpoints, events), `automation/automation-spec.md`
(notifications), decisions ADR-24…26, ADR-34…38.

## Run it locally

| Need | How |
| --- | --- |
| Tables | `uv run --offline python -m db.migrations upgrade head` (revisions `4d7a1c9e5b32` PPM V1 foundations, `a6c3e8b1d742` description documents) |
| E-mails / digests / reminders | `NOTIFICATIONS_RUNNER=api` (default: in each API process) · `worker` (`ews_worker`) · `off`; e-mail backend = section 7 of `.env.example` (Mailpit locally) |
| Tests | `uv run --offline pytest libs/ews/tests/unit_dev/test_ppm_v1_api.py` (local DB) |

## Change something → emit an event

Every PPM write goes through the module functions (`_work_items.create_item`, `set_assignees`, `complete`, …) and ends
with `_events.emit(session, scope, 'ppm.<entity>.<event>', '<subject type>', subject_id, project_id=…, changes=…,
data=…)`. In the caller's transaction it:

1. writes the audit row `taas_ppm_audit_events` (read by the Activity tabs),
2. saves the outbox message (`resiliant`, channel = topic, ordering key = project, envelope ADR-25),
3. runs each in-process subscriber (`@_events.subscribe`) in a savepoint — a failing subscriber is logged, the
   change still commits.

Use `diff(before, after)` for `changes`, `caused_by('rule')` around system changes, and add the topic to the
"Emitted today" list of `ppm-api.md`.

Subscribers that write must not loop: the schedule subscriber (`_schedule.on_event`) recalculates an auto project on
item / link events, writes the plan without emitting per-item events and emits one `ppm.schedule.recalculated`; code
that changes many items at once wraps them in `_schedule.batch()` and calls `_schedule.recalculate` once (Gantt drops,
template copies).

Derived states follow their source: the intake subscriber (`_intake_requests.on_event`) recomputes a request's
requester-facing status from its item (before a decision) or its result item / project (after) on `ppm.task.*` /
`ppm.project.*` events and emits `ppm.request.status_changed` only on a change (§5.4 of the intake spec).

Derived figures that read many events (project health) do not subscribe: `_health.current` recomputes today's snapshot
on read when the project's last audit event (its own `ppm.project.health*` events excluded) is newer, and the job
`ppm.health_refresh` does the same every 60 s (debounce 60 s); `compute` emits `ppm.project.health_changed` only when a
rating changed (ADR-44).

## Notify someone

1. Register the kind once (`_notify.py`): `register_kinds(Kind('ppm:<kind>', 'ppm', email='instant'|'digest'|'off',
   mandatory=…))`.
2. In a subscriber (or any code path): `await notify(session, tenant_id=…, organization_id=…, kind='ppm:<kind>',
   recipients=[user refs], exclude=[actor], title=…, link=…, project_id=…, occurrence='<stable id>', data={…})`.
   `occurrence` deduplicates; repeats on one subject within 10 min update one in-app row (`count`).
3. Add the web texts: `shell.json` → `notifications.kinds.<app>_<kind>` (inbox sentence, `{{actor}}`, `{{item}}`) and
   `notifications.kindNames.<app>_<kind>` (preferences) in the 14 languages.
4. Scheduled rules (due soon / overdue): `register_job(name, every_seconds, fn)` — run by the notifications runner.

Recipients may be e-mails without an account (external requesters of public intake forms): they get the e-mail
only. A secret link (tracking token) never goes through `notify` (rows are stored): send it directly with
`EmailServiceFactory` like `_intake_requests._confirmation_email`.

Recipients are filtered by project access (`_members.readers`), the project's switched-off kinds
(`settings.notifications.off`) and each user's preferences; mandatory kinds (mentions) always reach the inbox.

## Capability checks

Routes of a capability call `await _settings.require_capability(session, scope, '<key>')` (403
`capability_disabled`). New capabilities: add them to `_capabilities.CAPABILITIES` (level, `core`), to the web
`PpmCapability` type and to `settings.capabilities.<key>` in the `ppm` i18n module.
