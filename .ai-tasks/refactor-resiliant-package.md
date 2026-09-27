# Spec to implement

## Rules

- Must respect taas-server-py/docs/Py-Architecture.md
- Update related document i.e. Claude.md, Readme.md for updates with simple & concise information for later sessions
- For big implementation, components/services communication should be printed into a document in that project root /docs/developers for reference later
- At the end must exectue/test/fix all e2e tests in taas-tests/e2e/user-registration/e2e-user-registration.md
- At the end must execute all e2e tests in taas-web-official to make sure it's still working
- Feel free to drop database tables and recreate if there is migration - only keep one migration version for now since development phase...

## Tasks

- help me to improve idempotency in taas-server-py/libs/resiliant by support both storages in redis or postgresql and configuratable
- also make sure taas-server-py/libs/foundation/src/foundation/resiliant contain only types, definitions,.. all implementation - including settings should stay in this packages
- finally a developer guide document in taas-server-py/libs/resiliant/docs/developer-guide.md with guiding steps for integration & usage - real world exampes
