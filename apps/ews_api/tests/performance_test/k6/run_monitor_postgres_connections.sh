export PGPASSWORD=Pa55w0rd

while true; do
  psql -h localhost -U postgres -d taas_dev_next -tAc "
    SELECT now()::time(0),
           sum(CASE WHEN state='active' THEN 1 ELSE 0 END) AS active,
           sum(CASE WHEN state='idle' THEN 1 ELSE 0 END) AS idle,
           sum(CASE WHEN state='idle in transaction' THEN 1 ELSE 0 END) AS idle_tx
    FROM pg_stat_activity WHERE datname='taas_dev_next';"
  sleep 0.5
done