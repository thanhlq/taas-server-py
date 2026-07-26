# --package ews_api
export TAAS_SERVICE_NAME=ews_api
export MESSAGING_CONSUMER_ENABLE=false
export KAFKA_CONSUMER_ENABLE=false
uv run --no-sync python -m ews_api_litestar
