#!/bin/bash
# 🚀 Worker Startup Script

set -e

echo "🎯 eWorksuite Worker - Starting..."

# Check if .env file exists
if [ ! -f .env ]; then
    echo "⚠️  Warning: .env file not found. Using environment variables or defaults."
fi


# Start the worker
echo "🏃 Starting worker..."

export TAAS_SERVICE_NAME=ews_worker
export MESSAGING_CONSUMER_ENABLE=true
# 7100 = ews_worker default; 7002 collides with taas-web-official ui-nextjs-demo.
export WORKER_LISTEN_PORT=7100
export SIGNUP_TEST_MODE=true
uv run python -m ews_worker.main --reload
# uv run --package ews_worker python -m ews_worker
