#!/bin/sh
# model-sync.sh — Download model weights from Linode Object Storage.
# Shared by all init containers that need to fetch cached models.
#
# Usage: model-sync.sh <bucket-prefix> <local-path>
# Env:   OBJ_ENDPOINT_HOSTNAME, OBJ_ACCESS_KEY, OBJ_SECRET_KEY,
#        OBJ_REGION, MODEL_BUCKET  (all injected via obj-store-secret envFrom)
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

echo "Syncing ${MODEL_BUCKET}/${BUCKET_PREFIX} -> ${LOCAL_PATH}"
"$S5CMD" --endpoint-url "https://${OBJ_ENDPOINT_HOSTNAME}" \
    sync "s3://${MODEL_BUCKET}/${BUCKET_PREFIX}/*" "${LOCAL_PATH}/"
echo "Download complete."
