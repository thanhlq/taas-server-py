# performance improvement

```sql
-- count fastest
SELECT reltuples::bigint FROM pg_class WHERE relname = 'taas_user_account';
```
