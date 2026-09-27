#!/usr/bin/env bash
#
# Start the outbox relay worker: one poller per outbox table (messaging, transaction;
# narrow with OUTBOX_POLL_OUTBOXES) delivering pending records to their target. Mirrors
# start_ews_worker.sh.
#
# Usage:
#   ./start_outbox.sh                     # uses .env
#   ENV_FILE=.env.test ./start_outbox.sh
#
# Requires the messaging/db infrastructure to be up (Kafka, Postgres).
# See docker-compose.yml.

set -euo pipefail

export TAAS_SERVICE_NAME=outbox_worker
# 7110 = worker default; 7001 collides with taas-web-official ui-vite-demo.
export WORKER_LISTEN_PORT=7110
export OUTBOX_INITIAL_POLL_INTERVAL_MS=15000
export KAFKA_CONSUMER_GROUP_ID=
uv run --package outbox_worker python -m outbox_worker
