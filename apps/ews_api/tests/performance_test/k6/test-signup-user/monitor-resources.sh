#!/usr/bin/env bash
#
# Sample CPU% and RSS (memory) of the three signup-pipeline services and write
# them to a CSV, then print a min/avg/max/last summary table on exit.
#
# Services are matched by the module the .venv python runs:
#   api    -> python -m ews_api
#   worker -> python -m ews_worker
#   outbox -> python -m outbox_worker
# For each service ALL matching python processes are summed (covers reloader
# child processes), so restarts / --reload children are captured automatically.
#
# Usage:
#   ./monitor-resources.sh                       # sample every 5s until Ctrl-C
#   INTERVAL=10 OUT=usage.csv ./monitor-resources.sh
#   DURATION=7200 ./monitor-resources.sh         # auto-stop after 2h (seconds)
#
# On Ctrl-C (or after DURATION) it prints the summary. CPU% is macOS `ps`
# recent-usage and is per-core: on an N-core box a fully busy process reads
# ~100% and the total across services can exceed 100 * N is impossible but a
# single multi-threaded process CAN exceed 100%.
set -uo pipefail

INTERVAL="${INTERVAL:-5}"
OUT="${OUT:-resource-usage.csv}"
DURATION="${DURATION:-0}"   # 0 = run until signalled

NCPU="$(sysctl -n hw.ncpu 2>/dev/null || echo '?')"

# service label -> match token that appears in the python command line
API_PAT='-m ews_api'
WORKER_PAT='-m ews_worker'
OUTBOX_PAT='-m outbox_worker'

# Sum rss(MB) and cpu(%) across every .venv python process matching a token.
# Prints "<cpu> <mem_mb>".
sum_stat() {
  local pat="$1"
  ps -Ao rss,%cpu,command | awk -v pat="$pat" '
    index($0, pat) && index($0, "/.venv/bin/python") { cpu += $2; rss += $1 }
    END { printf "%.1f %.1f", cpu+0, (rss+0)/1024 }'
}

echo "timestamp,api_cpu,api_mem_mb,worker_cpu,worker_mem_mb,outbox_cpu,outbox_mem_mb" > "$OUT"

summarize() {
  echo ""
  echo "================ RESOURCE USAGE SUMMARY (host cores: ${NCPU}) ================"
  echo "CSV: $(cd "$(dirname "$OUT")" 2>/dev/null && pwd)/$(basename "$OUT")"
  # Skip header, compute min/avg/max/last for each numeric column.
  awk -F, 'NR>1 {
      n++
      for (c=2;c<=7;c++){
        v=$c
        if(n==1){mn[c]=v; mx[c]=v}
        if(v<mn[c])mn[c]=v
        if(v>mx[c])mx[c]=v
        sum[c]+=v
        last[c]=v
      }
    }
    END{
      if(n==0){print "  (no samples collected)"; exit}
      split("api_cpu% api_mem_MB worker_cpu% worker_mem_MB outbox_cpu% outbox_mem_MB",name," ")
      printf "  samples: %d\n", n
      printf "  %-16s %10s %10s %10s %10s\n","metric","min","avg","max","last"
      for(c=2;c<=7;c++)
        printf "  %-16s %10.1f %10.1f %10.1f %10.1f\n", name[c-1], mn[c], sum[c]/n, mx[c], last[c]
    }' "$OUT"
  echo "==========================================================================="
}
trap 'summarize; exit 0' INT TERM

START="$(date +%s)"
printf '%-19s | %-18s | %-18s | %-18s\n' 'time' 'api cpu%/mem' 'worker cpu%/mem' 'outbox cpu%/mem'
while true; do
  ts="$(date '+%Y-%m-%d %H:%M:%S')"
  read -r api_cpu api_mem <<<"$(sum_stat "$API_PAT")"
  read -r wrk_cpu wrk_mem <<<"$(sum_stat "$WORKER_PAT")"
  read -r obx_cpu obx_mem <<<"$(sum_stat "$OUTBOX_PAT")"

  echo "${ts},${api_cpu},${api_mem},${wrk_cpu},${wrk_mem},${obx_cpu},${obx_mem}" >> "$OUT"
  printf '%-19s | %6s%% %8s MB | %6s%% %8s MB | %6s%% %8s MB\n' \
    "$ts" "$api_cpu" "$api_mem" "$wrk_cpu" "$wrk_mem" "$obx_cpu" "$obx_mem"

  if [ "$DURATION" -gt 0 ] && [ "$(( $(date +%s) - START ))" -ge "$DURATION" ]; then
    summarize
    exit 0
  fi
  sleep "$INTERVAL"
done
