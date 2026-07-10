# Project

The all eworksuite (ews) implementations i..e domain model, business logic, data dictionary,... all the ews business logic.

This project will not be dependent on any api frameworks instead of that it use foundation.http for registration of api routes and in the real api projects as apps/ews_api will be responsible for wire up of the route difinitions with real api framework as fastapi or litestar

The structure:
- core: contain all core things as repositories, services,.. for users, team, tenants,...
- ews: for eworksuite
- ....
