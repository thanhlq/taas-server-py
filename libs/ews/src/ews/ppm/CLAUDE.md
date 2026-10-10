# PPM

Professional Project & Poforlio Management.

## Overview

The purpose is to build a so flexible project & poforlio management system (as https://teamworks.com, https://replicon.com) but:
- With very modern ui (look and feel)
- Very fast and AI oriented
- A project can be created with a template (or none)
- If a project is created with a template - a full template workflow will be applied for that project - customizable but within that template's limits (i.e. list of work item types)

## Specification

See `taas-specs/ppm/` (app spec `ppm-app-spec.md`, API `ppm-api.md`, decisions, roadmap) and the
workflow standard `taas-specs/ppm/project/project-workflow/README.md`.

## Workflows

- Rules live in `_workflow_service.py` (process, workflows, stages, task placement, lazy
  migration of older projects); controllers in `controllers/_workflow_api.py`.
- The template catalog is `workflow_catalog/data/` — a copy of the specs' `templates/`,
  `categories.json`, `stage-types.json` + catalog translations `i18n/<locale>.json`
  (English = source; keep every locale's keys in sync — a unit test checks it).

## V1 modules (2026-10-10)

| Concern | Where |
| --- | --- |
| Events (audit + outbox + subscribers, one transaction — ADR-38) | `_events.py` (`emit`, `subscribe`, `caused_by`, `diff`); every write path emits `ppm.<entity>.<event>` |
| Capability levels + editors (ADR-34) | `_capabilities.py` (catalog, default level ⭐⭐), `_settings.py` (`require_capability` → 403 `capability_disabled`, `update` with `version`) |
| Members | `_access.py` (`PROJECTS` = `ObjectAccess`), `_members.py` (last admin, personal project) |
| Work items | `_work_items.py`: the **single** create path `create_item`, parent checks (≤ 3 levels), roll-ups, complete / reopen (cascade, mandatory steps), move, owner + collaborators |
| Checklists · comments · activity · files | `_checklists.py`, `_comments.py` (sanitized HTML via `ews.shared._html`, mentions), `_activity.py` (audit rows), `_files.py` (File Manager source drive `kind = project`, links) |
| My Work · overview · export | `_my_work.py` (buckets, plans, snooze, Inbox = personal project), `_overview.py`, `_export.py` (CSV, formula-safe) |
| Notifications | `_notify.py`: PPM kinds + subscriber + hourly due reminders on the platform `ews.notifications` |

## V2 work model (2026-10-11)

| Concern | Where |
| --- | --- |
| Behaviours (pure) + item type library | `_behaviours.py` (catalog, default mapping, milestone rule), `_item_types.py` (library seeded from the universal template, `check_key`, `behaviour_of`, 409 `in_use`) |
| Custom fields | `_custom_fields.py`: definitions + options (stable ids), bindings (most specific wins), typed values (`set_values` → 400 `invalid_fields`), `cf_*` filters, required-before-done guard |
| Checklist templates · recurrence | `_checklist_templates.py` (apply, save from item, type default), `_recurrence.py` (RRULE subset, next occurrence on `ppm.task.completed`) |
| Approvals | `_approvals.py`: subjects registry (`task` built in), steps / policies, decide / delegate / cancel / resubmit, completion guard (ADR-39, ADR-40) |
| Project templates | `_templates.py`: one copy engine (save as template with roles, instantiate with working-day shift, duplicate) |
| Routes | `controllers/_work_model_api.py`; tests `tests/unit/test_ppm_work_model_rules.py`, `tests/unit_dev/test_ppm_v2_work_model_api.py` |

## V2 schedule (2026-10-10)

| Concern | Where |
| --- | --- |
| Engine (pure, ADR-42) | `_schedule_engine.py`: `Calendar` (Mon–Fri index), `compute` (forward pass FS · SS · FF · SF + lag, constraints, manual vs auto, forecast at today, backward pass → float / critical, summaries, violations, `why`), `find_cycle`, `schedule_progress` — tests `tests/unit/test_ppm_schedule_engine.py` |
| Service | `_schedule.py`: settings (`settings.schedule`: mode, thresholds), phases, item links (`check_link` → 400 `invalid_link` / `dependency_cycle`), `check_item_fields`, read model `read`, `recalculate` (auto items written back, `schedule_version + 1`, `ppm.schedule.recalculated`), subscriber (recalculation, `started_at`, SNET on a new start, links dropped on delete / move, `ppm.milestone.reached`), `batch()` = one recalculation for many writes |
| Transition rules · team workflows | `_workflow_rules.py`: `check_transition` (409 `transition_not_allowed`), `check_requirements` (409 `stage_requirements`), `default_assignee`, `first_allowed` (complete), `viewer_teams` / `organization_teams` / `check_team`; applied in `_work_items.on_stage_change` (every move but *reopen*); `GET /api/v1/ppm/teams` — tests `tests/unit_dev/test_ppm_v2_workflow_rules_api.py` |
| Time tracking (ADR-43) | `_effort.py` (pure: E, A, R, F, V%, roll-ups, bands, rounding), `_time_settings.py` (`time.*` defaults / validation / weeks), `_time.py`: effort refresh + variance alerts, entries (`create_entry` … `correct_entry`, locks), timer (+ job `ppm.timer_auto_stop`), timesheets (`sheet_for`, `week_view`, `write_cells`, `copy_previous`, `submit`, approval subject `timesheet` per section, `reopen`), project time + CSV; routes `controllers/_time_api.py` — tests `tests/unit/test_ppm_effort.py`, `tests/unit_dev/test_ppm_v2_time_api.py` |
| Routes | `controllers/_schedule_api.py` (`/projects/{id}/schedule[/settings\|/preview\|/changes]`, `/projects/{id}/phases`, `/tasks/{id}/dependencies`) — tests `tests/unit_dev/test_ppm_v2_schedule_api.py` |
| Automation (ADR-46) | `_automation_rules.py` (pure: catalog of triggers / fields / operators / actions, `validate` with JSON paths, `evaluate`, `render` tokens, `next_run`, `add_days`, templates), `_automation.py` (rules CRUD + quota, subscriber `on_event`, `run_rule` as the owner via `ews.security.scope_of`, actions through `_item_update.update_item` / `create_item` / comments / checklists / approvals, run log, `undo`, `test_rule` dry-run, job `ppm.automation_tick`, loop guard, throttle, auto-pause); `_item_update.py` = the single item update path (task API + automation); routes `controllers/_automation_api.py` — tests `tests/unit/test_ppm_automation_rules.py`, `tests/unit_dev/test_ppm_v2_automation_api.py` |
| Client & contacts (Ppm-0113…0117) | `_project_contacts.py`: `check_client` (CRM account of the organization), `set_contacts` (replace the set, one default, `ppm.project.contacts_changed`), `contacts_of` (project detail), `projects_of` (`GET /api/v1/ppm/contacts/{id}/projects`, `controllers/_project_contacts_api.py`); `_projects.create_project` stays the create path — tests `tests/unit_dev/test_crm_contacts_api.py` |
| Intake (ADR-47) | `_intake_forms.py` (pure: definition `validate`, `visible_keys`, `clean_answers`, `mapped`, `title`, `route` — operators of `_automation_rules.compare`, `STARTER`), `_intake.py` (forms: CRUD on `version`, publish = immutable `taas_ppm_form_versions`, close, rotate link, available, routing test, responses CSV / XLSX), `_intake_requests.py` (submit internal / public: honeypot, IP-hash limits, idempotency, routing as the form owner, item via `create_item`; inbox · mine · all, detail, accept item / in place / project, reject, merge, request info, replies = comments `privacy = requester`, withdraw, status mirror subscriber §5.4, tracking token, notifications `ppm:request_*`); `_projects.create_project` = the single project create path; routes `controllers/_intake_api.py` (incl. public `/public-forms`, `/public-requests`) — tests `tests/unit/test_ppm_intake_forms.py`, `tests/unit_dev/test_ppm_v2_intake_api.py` |
| Dashboards & reports (ADR-45) | `_stats.py` (daily statistics per project / running iteration, `current`, `series` burnup · burndown · throughput, job `ppm.daily_stats`), `_widgets.py` (query model `clean_query` / `run` with the viewer's scope, sources items · projects · time · trend · kpi · lists · milestones · health · activity · approvals · series), `_dashboards.py` (widget catalog, system dashboards `system:<key>`, layout rules, CRUD, copy, shares), `_reports.py` (V2 reports, CSV / XLSX `render`); `_overview.py` tiles; routes `controllers/_dashboards_api.py` — tests `tests/unit/test_ppm_dashboards_rules.py`, `tests/unit_dev/test_ppm_v2_dashboards_api.py` |
| Project health (ADR-23, ADR-44) | `_health_engine.py` (pure: rules S1–S7, R1, C1, Q1–Q3, K3 → rating + reasons `{rule, rating, code, params, evidence}`, overall, policy thresholds), `_health.py`: policies (organization + project exception), `facts`, `compute` (today's snapshot, `ppm.project.health_changed`, override author notice `ppm:health_changed`), `current` (recompute when stale), overrides, `history`, `latest_ratings` (list badge), job `ppm.health_refresh`; routes `controllers/_health_api.py` — tests `tests/unit/test_ppm_health_engine.py`, `tests/unit_dev/test_ppm_v2_health_api.py` |

Guide: [docs/developers/ppm-events-notifications-guide.md](../../../../../docs/developers/ppm-events-notifications-guide.md).
Tests: `libs/ews/tests/unit_dev/test_ppm_v1_api.py` (needs the local DB).

## References

- This project can be referenced from plane.so (local source code in: ~/git/ref/plane)

## Rules

Must following these rules

- Currently all database models for ppm, crm,... are located in taas-server-py/libs/db
- Can always update the v1 if the migration taas-server-py/libs/db/src/db/migrations/versions/2026-07-29_init_database_bdb25317e822.py, the database taas_next_test can be dropped in rerun the migration since there is no any deployment for now
- 

## Api Design

We can refer to the following platforms for design of our ai:

- [Following Jira rest api v3](https://developer.atlassian.com/cloud/jira/platform/rest/v3/intro/#about)
- And also following [plane.so](https://developers.plane.so/api-reference/introduction)

But should also follow our phylosophies
