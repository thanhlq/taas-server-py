#!/bin/bash

start=$(date +%s.%N)

# 1
curl -X 'GET' \
  'http://localhost:8191/api/v1/users/slow2' \
  -H 'accept: application/json' \
  -H 'Accept-Encoding: gzip' \
  -H 'Content-Type: application/json' | gunzip -

#  | gunzip -

end=$(date +%s.%N)
echo "\n"
echo "------------------------------------"
echo "total wall clock: $(echo "$end - $start" | bc)s"