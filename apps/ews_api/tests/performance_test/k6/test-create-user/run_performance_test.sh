#!/bin/bash

# Important:
# This often 256 (white k6 open huge numbers of connections), so we need to
# increase the limit to avoid "too many open files" error.
ulimit -n

ulimit -n 1048576

# k6 run create-user-test.js


k6 run stress-test-create-user.js
