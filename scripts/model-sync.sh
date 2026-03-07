#!/bin/sh
# model-sync.sh — Download model weights from Linode Object Storage.
# Shared by all init containers that need to fetch cached models.
#
# Usage: model-sync.sh <bucket-prefix> <local-path>
# Env:   OBJ_ENDPOINT_HOSTNAME, OBJ_ACCESS_KEY, OBJ_SECRET_KEY,
#        OBJ_REGION, MODEL_BUCKET  (all injected via obj-store-secret envFrom)
#
# Tuning (optional env vars):
#   S5CMD_CONCURRENCY  — concurrent parts per file (default: 5)
#                        Increase for models with few large files (e.g. 64).
#   S5CMD_PART_SIZE    — part size in MiB (default: 50)
#                        Increase to reduce round-trips for very large files.
set -e

BUCKET_PREFIX="${1:?Usage: model-sync.sh <bucket-prefix> <local-path>}"
LOCAL_PATH="${2:?Usage: model-sync.sh <bucket-prefix> <local-path>}"

# s5cmd uses AWS env vars for auth — alias from Linode Object Storage credentials
export AWS_ACCESS_KEY_ID="${OBJ_ACCESS_KEY}"
export AWS_SECRET_ACCESS_KEY="${OBJ_SECRET_KEY}"
export AWS_REGION="${OBJ_REGION}"

# Install s5cmd if not already available
S5CMD=""
if command -v s5cmd >/dev/null 2>&1; then
    S5CMD=s5cmd
elif [ -x /tmp/s5cmd ]; then
    S5CMD=/tmp/s5cmd
else
    echo "Installing s5cmd v2.3.0..."
    wget -q -O /tmp/s5cmd.tar.gz \
        "https://github.com/peak/s5cmd/releases/download/v2.3.0/s5cmd_2.3.0_Linux-64bit.tar.gz"
    tar xzf /tmp/s5cmd.tar.gz -C /tmp && rm /tmp/s5cmd.tar.gz
    S5CMD=/tmp/s5cmd
fi

# Per-file multipart download tuning
CONCURRENCY="${S5CMD_CONCURRENCY:-5}"
PART_SIZE="${S5CMD_PART_SIZE:-50}"

echo "Syncing ${MODEL_BUCKET}/${BUCKET_PREFIX} -> ${LOCAL_PATH} (concurrency=${CONCURRENCY}, part_size=${PART_SIZE}MiB)"
SYNC_START=$(date +%s)
"$S5CMD" --endpoint-url "https://${OBJ_ENDPOINT_HOSTNAME}" \
    sync --exclude ".cache/**" \
    --concurrency "${CONCURRENCY}" --part-size "${PART_SIZE}" \
    "s3://${MODEL_BUCKET}/${BUCKET_PREFIX}/*" "${LOCAL_PATH}/"
SYNC_END=$(date +%s)
ELAPSED=$(( SYNC_END - SYNC_START ))

# Report download metrics
FILE_COUNT=$(find "${LOCAL_PATH}" -type f 2>/dev/null | wc -l | tr -d ' ')
# du -sb is GNU-only; use du -sk (POSIX) and convert KB -> bytes
TOTAL_KB=$(du -sk "${LOCAL_PATH}" 2>/dev/null | awk '{print $1}')
TOTAL_BYTES=$(( ${TOTAL_KB:-0} * 1024 ))
TOTAL_GB=$(awk "BEGIN {printf \"%.2f\", ${TOTAL_BYTES} / 1073741824}")
if [ "$ELAPSED" -gt 0 ]; then
  SPEED_GBPS=$(awk "BEGIN {printf \"%.2f\", ${TOTAL_BYTES} / 1073741824 / ${ELAPSED}}")
else
  SPEED_GBPS="N/A"
fi

echo "Download complete — ${FILE_COUNT} files, ${TOTAL_GB} GB in ${ELAPSED}s (${SPEED_GBPS} GB/s)"
