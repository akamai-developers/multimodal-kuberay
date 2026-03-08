#!/usr/bin/env bash
# nuke-bucket.sh — Empties and deletes the model cache bucket.
# Destructive operation — requires confirmation unless --yes is passed.
#
# Required env vars (loaded from .env by Makefile):
#   OBJ_ACCESS_KEY          — Object storage access key
#   OBJ_SECRET_KEY          — Object storage secret key
#   OBJ_REGION              — Object storage region
#   OBJ_ENDPOINT_HOSTNAME   — Object storage endpoint hostname
#   MODEL_BUCKET            — Bucket name to destroy

set -euo pipefail

# ── Validate required env vars ──────────────────────────────────────────────
for var in OBJ_ACCESS_KEY OBJ_SECRET_KEY OBJ_REGION OBJ_ENDPOINT_HOSTNAME MODEL_BUCKET; do
  if [ -z "${!var:-}" ]; then
    echo "ERROR: ${var} is not set. Ensure .env is configured."
    exit 1
  fi
done

OBJ_ENDPOINT="https://${OBJ_ENDPOINT_HOSTNAME}"
export AWS_ACCESS_KEY_ID="${OBJ_ACCESS_KEY}"
export AWS_SECRET_ACCESS_KEY="${OBJ_SECRET_KEY}"
export AWS_REGION="${OBJ_REGION}"

# ── Check if s5cmd is available, install if needed ──────────────────────────
if ! command -v s5cmd &>/dev/null; then
  echo "s5cmd not found — installing v2.3.0..."
  ARCH=$(uname -m)
  OS=$(uname -s)
  case "${OS}_${ARCH}" in
    Darwin_arm64) BINARY="s5cmd_2.3.0_macOS-arm64.tar.gz" ;;
    Darwin_x86_64) BINARY="s5cmd_2.3.0_macOS-64bit.tar.gz" ;;
    Linux_x86_64) BINARY="s5cmd_2.3.0_Linux-64bit.tar.gz" ;;
    Linux_aarch64) BINARY="s5cmd_2.3.0_Linux-arm64.tar.gz" ;;
    *) echo "ERROR: Unsupported platform ${OS}_${ARCH}"; exit 1 ;;
  esac
  curl -fsSL -o /tmp/s5cmd.tar.gz \
    "https://github.com/peak/s5cmd/releases/download/v2.3.0/${BINARY}"
  tar xzf /tmp/s5cmd.tar.gz -C /usr/local/bin 2>/dev/null \
    || sudo tar xzf /tmp/s5cmd.tar.gz -C /usr/local/bin
  rm /tmp/s5cmd.tar.gz
  echo "s5cmd installed."
fi

# ── Check if bucket exists ──────────────────────────────────────────────────
echo "Checking bucket s3://${MODEL_BUCKET} at ${OBJ_ENDPOINT}..."
if ! s5cmd --endpoint-url "$OBJ_ENDPOINT" ls "s3://${MODEL_BUCKET}" &>/dev/null; then
  echo "Bucket s3://${MODEL_BUCKET} does not exist or is not accessible. Nothing to do."
  exit 0
fi

# ── Count objects ───────────────────────────────────────────────────────────
OBJECT_COUNT=$(s5cmd --endpoint-url "$OBJ_ENDPOINT" ls "s3://${MODEL_BUCKET}/**" 2>/dev/null | wc -l | tr -d ' ')
echo "Found ${OBJECT_COUNT} objects in s3://${MODEL_BUCKET}"

# ── Confirmation ────────────────────────────────────────────────────────────
if [ "${1:-}" != "--yes" ]; then
  echo ""
  echo "WARNING: This will permanently delete ALL objects and the bucket itself."
  echo "  Bucket:   ${MODEL_BUCKET}"
  echo "  Endpoint: ${OBJ_ENDPOINT_HOSTNAME}"
  echo "  Objects:  ${OBJECT_COUNT}"
  echo ""
  printf "Type 'yes' to confirm: "
  read -r confirm
  if [ "$confirm" != "yes" ]; then
    echo "Aborted."
    exit 1
  fi
fi

# ── Delete all objects ──────────────────────────────────────────────────────
if [ "$OBJECT_COUNT" -gt 0 ]; then
  echo "Deleting all objects from s3://${MODEL_BUCKET}..."
  START=$(date +%s)
  s5cmd --endpoint-url "$OBJ_ENDPOINT" rm "s3://${MODEL_BUCKET}/*"
  ELAPSED=$(( $(date +%s) - START ))
  echo "Deleted ${OBJECT_COUNT} objects in ${ELAPSED}s"
else
  echo "Bucket is already empty."
fi

# ── Delete bucket ───────────────────────────────────────────────────────────
echo "Deleting bucket s3://${MODEL_BUCKET}..."
s5cmd --endpoint-url "$OBJ_ENDPOINT" rb "s3://${MODEL_BUCKET}"
echo ""
echo "=== Bucket s3://${MODEL_BUCKET} destroyed ==="
