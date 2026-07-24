#!/usr/bin/env bash
#
# Start the outbox relay worker: polls the transactional outbox and publishes
# pending events to the broker via the pure OutboxPoller. Mirrors
# start_ews_worker.sh.
#
# Usage:
#   ./start_outbox.sh                     # uses .env
#   ENV_FILE=.env.test ./start_outbox.sh
#
# Requires the messaging/db infrastructure to be up (Kafka, Postgres).
# See docker-compose.yml.

set -euo pipefail

uv run --package outbox_worker python -m outbox_worker
