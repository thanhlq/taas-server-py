# --package ews_api

export TAAS_SERVICE_NAME=ews_api
export MESSAGING_CONSUMER_ENABLE=false
export CONSUMER_ENABLE=false

# Total memory buffer capacity before spans are dropped.
# Default = 2048, production: 16384 to 65536
export OTEL_BSP_MAX_QUEUE_SIZE=2048
# export OTEL_BSP_MAX_QUEUE_SIZE=1024

# Max spans sent per network call (must be ≤ max queue size).
# default: 512, production: 2048 to 4096, 8192
export OTEL_BSP_MAX_EXPORT_BATCH_SIZE=512

# Time to wait before flushing the queue.
# default=5000 (5 seconds), production: 1000 to 2000 (1-2 seconds)
export OTEL_BSP_SCHEDULE_DELAY=5000

# Maximum allowed time for a single network export to finish.
# default=30000 (30 seconds), production: 5000 to 30000 (5-30 seconds)
export OTEL_BSP_EXPORT_TIMEOUT=30000
uv run --no-sync python -m ews_api
