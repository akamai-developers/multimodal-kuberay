#!/usr/bin/env bash
# prepare-deps-nemotron.sh — initContainer for Nemotron Parse RayService workers.
#
# Downloads the model from object storage and pre-warms the pip cache
# in parallel, so the runtime_env pip install hits only local wheels.
#
# Required env vars (via obj-store-secret):
#   OBJ_ACCESS_KEY, OBJ_SECRET_KEY, OBJ_REGION, OBJ_ENDPOINT_HOSTNAME, MODEL_BUCKET

set -e

# ── Model download (background) ──────────────────────────────────
/scripts/model-sync.sh "nvidia/NVIDIA-Nemotron-Parse-v1.2" /model-cache &
MODEL_PID=$!

# ── Pre-warm pip cache (background) ──────────────────────────────
# Download wheels into the shared pip cache volume so the
# runtime_env pip install (which runs inside the worker container)
# hits only local files instead of fetching from PyPI.
(
  echo "[prepare-deps] Pre-downloading pip wheels..."
  pip download --quiet \
    --cache-dir=/home/ray/.cache/pip \
    --dest=/tmp/pip-wheels \
    "numpy<2.0" "cloudpickle>=3.1.0" \
    timm==1.0.22 albumentations==2.0.8 open_clip_torch
  echo "[prepare-deps] Pip cache warm complete."
) &
PIP_PID=$!

# Wait for both — fail if either fails
FAIL=0
wait $MODEL_PID || FAIL=1
wait $PIP_PID  || FAIL=1
if [ $FAIL -ne 0 ]; then
  echo "[prepare-deps] ERROR: one or more tasks failed"
  exit 1
fi
echo "[prepare-deps] All dependencies ready."
