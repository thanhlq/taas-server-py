# Project

## Overview

The all eworksuite (ews) implementations i..e domain model, business logic, data dictionary,... all the ews business logic.

This project will not be dependent on any api frameworks instead of that it use foundation.http for registration of api routes and in the real api projects as apps/ews_api will be responsible for wire up of the route difinitions with real api framework as fastapi or litestar

The structure:
- core: contain all core things as repositories, services,.. for users, team, tenants,...
- authz: business RBAC — roles / permissions catalog `authz/data/ews-rbac.json` (Project Admin,
  Project Member, Project Viewer, PPM / CRM rights of `org_admin` / `org_member`), synced into
  `taas_casbin_rule` at EWS API start-up (`sync_catalog`), decision `can(user, resource_domains(...),
  'ppm.task', 'update')`, grants `grant` / `revoke`. Same model as the IAM (Node):
  `taas-specs/iam/specs/authorization-rbac-spec.md`. Edit the JSON, restart; the unit test validates it
- ews: for eworksuite
- ....

## Rules

Any updates or modification must respect the following rules:
- Must be easy for developer to read, navigate and understand
- Me be reusable, scalable, extensible and very good folder structure
- Must be crafted carefully because this platform is used for serious user cases as banking, finance,..
- Update code must update unit tests, e2e tests, specs documents
- Update api, types,... must regenerate types.gen.ts (in root CLAUDE.md, session 3) and reupdate the web project taas-web-official if needed (run e2e tests)
