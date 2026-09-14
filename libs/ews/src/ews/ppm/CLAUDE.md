# PPM

Professional Project & Poforlio Management.

## Overview

The purpose is to build a so flexible project & poforlio management system (as https://teamworks.com, https://replicon.com) but:
- With very modern ui (look and feel)
- Very fast and AI oriented
- A project can be created with a template (or none)
- If a project is created with a template - a full template workflow will be applied for that project - customizable but within that template's limits (i.e. list of work item types)

## Specification

See taas-server-py/libs/ews/docs/specs/ppm

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
