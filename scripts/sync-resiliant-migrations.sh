#!/usr/bin/env bash
# Copy the resiliant drizzle migrations (the DDL source of truth) from taas-server-js.
# Run after `pnpm --filter @taas/resiliant db:generate` there; commit both repos together.
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
src="$here/../taas-server-js/packages/resiliant/drizzle"
dst="$here/libs/resiliant/src/resiliant/migrations/drizzle"
[[ -d "$src" ]] || { echo "not found: $src" >&2; exit 1; }
rm -rf "$dst" && cp -R "$src" "$dst"
echo "synced $(find "$dst" -type f | wc -l | tr -d ' ') files from $src"
