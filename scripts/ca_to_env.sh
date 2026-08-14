#!/usr/bin/env bash
#
# Convert a PEM CA bundle into a single-line KAFKA_CA_DATA value that can be
# pasted into .env (see the Kafka section of taas-server-py/.env).
#
# Nothing is written to .env — the env line goes to stdout, every diagnostic
# goes to stderr, so redirecting gives a clean file to copy from:
#
#   ./scripts/ca_to_env.sh > ca.env
#
# Usage:
#   ./scripts/ca_to_env.sh                          # repo-root ca.crt, base64
#   ./scripts/ca_to_env.sh /path/to/other-ca.crt    # explicit cert
#   ./scripts/ca_to_env.sh -f escaped               # single-line PEM with \n
#   ./scripts/ca_to_env.sh -v KAFKA_CA_DATA_DEV     # different variable name
#   ./scripts/ca_to_env.sh -o ca.env                # also write to a file
#
# Formats (both accepted by foundation's normalize_ca_data / the JS
# KafkaHelper.normalizeCaData):
#   base64   one line of base64-encoded PEM — no quoting pitfalls (default)
#   escaped  the PEM on one line with literal \n escapes, double-quoted
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# scripts/ -> taas-server-py/ -> monorepo root, where ca.crt lives.
DEFAULT_CA="$(cd "${SCRIPT_DIR}/../.." && pwd)/ca.crt"

FORMAT='base64'
VAR_NAME='KAFKA_CA_DATA'
OUT_FILE=''

log() { printf '%s\n' "$*" >&2; }
die() { printf '❌ %s\n' "$*" >&2; exit 1; }

usage() {
    sed -n '2,27p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2
    exit "${1:-0}"
}

while getopts ':f:v:o:h' opt; do
    case "${opt}" in
        f) FORMAT="${OPTARG}" ;;
        v) VAR_NAME="${OPTARG}" ;;
        o) OUT_FILE="${OPTARG}" ;;
        h) usage 0 ;;
        :) die "option -${OPTARG} requires an argument (see -h)" ;;
        ?) die "unknown option -${OPTARG} (see -h)" ;;
    esac
done
shift $((OPTIND - 1))

CA_FILE="${1:-${DEFAULT_CA}}"

case "${FORMAT}" in
    base64|escaped) ;;
    *) die "unknown format '${FORMAT}' — use base64 or escaped" ;;
esac

command -v openssl >/dev/null 2>&1 || die 'openssl not found on PATH'
[[ -f "${CA_FILE}" ]] || die "CA file not found: ${CA_FILE}"
[[ -s "${CA_FILE}" ]] || die "CA file is empty: ${CA_FILE}"

# ---------------------------------------------------------------------------
# Validate before emitting: a mangled value fails at the TLS handshake, far
# from here, so reject it now.
# ---------------------------------------------------------------------------
openssl x509 -in "${CA_FILE}" -noout >/dev/null 2>&1 \
    || die "not a readable PEM certificate: ${CA_FILE}"

CERT_COUNT="$(grep -c 'BEGIN CERTIFICATE' "${CA_FILE}" || true)"

log "📄 source    : ${CA_FILE}"
log "🔖 subject   : $(openssl x509 -in "${CA_FILE}" -noout -subject | sed 's/^subject=//')"
log "🔖 issuer    : $(openssl x509 -in "${CA_FILE}" -noout -issuer | sed 's/^issuer=//')"
log "📅 expires   : $(openssl x509 -in "${CA_FILE}" -noout -enddate | sed 's/^notAfter=//')"
log "🔑 sha256    : $(openssl x509 -in "${CA_FILE}" -noout -fingerprint -sha256 | sed 's/^.*=//')"
log "🧾 certs     : ${CERT_COUNT}"

if ! openssl x509 -in "${CA_FILE}" -noout -checkend 0 >/dev/null 2>&1; then
    log '🚨 WARNING: this certificate has ALREADY EXPIRED'
elif ! openssl x509 -in "${CA_FILE}" -noout -checkend 2592000 >/dev/null 2>&1; then
    log '⚠️  WARNING: expires within 30 days'
fi

if [[ "${CERT_COUNT}" -gt 1 ]]; then
    # openssl x509 only reports the first cert; the encoders below take the
    # whole file, so the bundle is embedded correctly either way.
    log "ℹ️  bundle contains ${CERT_COUNT} certificates — details shown are for the first"
fi

# ---------------------------------------------------------------------------
# Emit
# ---------------------------------------------------------------------------
case "${FORMAT}" in
    # -A keeps it on one line and works on both macOS and GNU (base64 -w0 does not).
    base64)  VALUE="$(openssl base64 -A -in "${CA_FILE}")" ;;
    escaped) VALUE="\"$(awk '{printf "%s\\n", $0}' "${CA_FILE}")\"" ;;
esac

ENV_LINE="${VAR_NAME}=${VALUE}"

log "📦 format    : ${FORMAT} (${#VALUE} chars)"
log ''
log "Paste the line below into taas-server-py/.env, and comment out"
log "KAFKA_SSL_CA_LOCATION — the file path wins when both are set."
log ''

printf '%s\n' "${ENV_LINE}"

if [[ -n "${OUT_FILE}" ]]; then
    printf '%s\n' "${ENV_LINE}" > "${OUT_FILE}"
    log ''
    log "✅ also written to ${OUT_FILE}"
fi
