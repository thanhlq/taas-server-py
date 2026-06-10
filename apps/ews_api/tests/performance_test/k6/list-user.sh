#!/bin/bash

start=$(date +%s.%N)

# 1
curl -X 'GET' \
  'http://localhost:8191/api/v1/users/' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json'

end=$(date +%s.%N)
echo "------------------------------------"
echo "total wall clock: $(echo "$end - $start" | bc)s"