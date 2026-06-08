# pgdog test

The purpose is to test if pgdog integration works as exptected:

To connect to pgdog admin db to check:

```bash
PGPASSWORD=sa21481 psql -h localhost -p 6432 -U admin admin
```

then execute

```bash
SHOW PREPARED;     -- names + count of globally-cached statements
SHOW SERVERS;      -- each server connection reports its prepared-statement count
```
