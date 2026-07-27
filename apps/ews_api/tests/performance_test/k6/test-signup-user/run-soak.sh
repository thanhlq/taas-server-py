#!/usr/bin/env bash
#
# Orchestrate a signup stability soak: start the resource monitor, run the k6
# soak, then print a single combined final report (k6 summary + CPU/RAM summary
# for api / worker / outbox). All artifacts land in ./runs/<timestamp>/.
#
# Prereqs: the three services are already running --
#   ./start_fastapi_ews_api.sh   ./start_outbox.sh   ./start_worker.sh
# and k6 is installed.
#
# Usage (all optional, defaults shown):
#   VUS=1 DURATION=2h INTERVAL=5 ./run-soak.sh
#   VUS=1 DURATION=20s ./run-soak.sh           # quick smoke run
#
# Env knobs are forwarded to k6 (VUS, DURATION, EMAIL_MODE, BASE_URL, ...) and
# to the monitor (INTERVAL). See README.md.
set -uo pipefail

cd "$(dirname "$0")"

VUS="${VUS:-1}"
DURATION="${DURATION:-2h}"
INTERVAL="${INTERVAL:-5}"
BASE_URL="${BASE_URL:-http://localhost:8191}"
EMAIL_MODE="${EMAIL_MODE:-per-vu}"

STAMP="$(date '+%Y%m%d-%H%M%S')"
RUN_DIR="runs/${STAMP}"
mkdir -p "$RUN_DIR"

CSV="${RUN_DIR}/resource-usage.csv"
MON_LOG="${RUN_DIR}/monitor.log"
K6_LOG="${RUN_DIR}/k6-output.log"

echo "=========================================================================="
echo " Signup soak test"
echo "   vus (conc) : ${VUS}"
echo "   duration   : ${DURATION}"
echo "   email mode : ${EMAIL_MODE}"
echo "   base url   : ${BASE_URL}"
echo "   sample int : ${INTERVAL}s"
echo "   run dir    : ${RUN_DIR}"
echo "=========================================================================="

# Fail fast if the API isn't reachable.
if ! curl -s -o /dev/null --max-time 5 "${BASE_URL}/api/v1/auth/signup" -X POST \
      -H 'Content-Type: application/json' -d '{}'; then
  echo "ERROR: cannot reach ${BASE_URL}. Start the services first." >&2
  exit 1
fi

# 1. Start the resource monitor in the background.
INTERVAL="$INTERVAL" OUT="$CSV" DURATION=0 ./monitor-resources.sh >"$MON_LOG" 2>&1 &
MON_PID=$!

# Make sure the monitor is stopped (and thus prints its summary) no matter how
# k6 exits.
cleanup() { kill -TERM "$MON_PID" 2>/dev/null; wait "$MON_PID" 2>/dev/null; }
trap cleanup EXIT

# 2. Run k6, streaming its output to console AND the log file.
echo ">> starting k6 (live output below; full log: ${K6_LOG})"
VUS="$VUS" DURATION="$DURATION" BASE_URL="$BASE_URL" EMAIL_MODE="$EMAIL_MODE" \
  k6 run stress-signup.js 2>&1 | tee "$K6_LOG"
K6_STATUS=${PIPESTATUS[0]}

# 3. Stop the monitor so it flushes its summary into MON_LOG.
cleanup
trap - EXIT

# 4. Combined final report.
echo ""
echo "########################  FINAL REPORT  ########################"
echo ""
echo "----- k6 summary (from ${K6_LOG}) -----"
# Keep the end-of-test metrics block; drop the live "running (...)" progress
# lines and the ramp bar so only the summary numbers show.
grep -aE 'data_received|data_sent|scenarios:|✓|✗|http_req_|signup_|iterations|checks|vus|iteration_duration' "$K6_LOG" \
  | grep -avE '^running \(|VUs  ' | tail -n 40
echo ""
echo "----- resource usage (api / worker / outbox) -----"
# Print the summary table the monitor wrote when it was stopped.
sed -n '/RESOURCE USAGE SUMMARY/,/====$/p' "$MON_LOG"
echo ""
echo "Artifacts:"
echo "  k6 output     : ${K6_LOG}"
echo "  resource CSV  : ${CSV}"
echo "  monitor log   : ${MON_LOG}"
echo ""
if [ "$K6_STATUS" -eq 0 ]; then
  echo "RESULT: k6 thresholds PASSED ✅  (system stable at VUS=${VUS} for ${DURATION})"
else
  echo "RESULT: k6 thresholds FAILED ❌  (exit ${K6_STATUS}) -- inspect ${K6_LOG}"
fi
echo "################################################################"
exit "$K6_STATUS"
