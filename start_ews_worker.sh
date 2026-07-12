#!/usr/bin/env bash
#
# Start the EWS background worker (Kafka consumer + event processing + optional
# outbox relay). Mirrors start_ews_api_fastapi.sh.
#
# Usage:
#   ./start_ews_worker.sh                 # uses .env
#   ENV_FILE=.env.test ./start_ews_worker.sh
#
# Requires the messaging/cache/db infrastructure to be up (Kafka, Redis,
# Postgres). See docker-compose.yml.

set -euo pipefail

# --package ews_worker
uv run --package ews_worker python -m ews_worker
