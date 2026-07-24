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

uv run python -m ews_worker.main --reload
# uv run --package ews_worker python -m ews_worker
