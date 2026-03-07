#!/usr/bin/env bash
# model-upload.sh — Downloads models from HuggingFace and uploads to Object Storage.
# Idempotent — skips models that are already cached in the bucket.
#
# Required env vars:
#   HUGGING_FACE_HUB_TOKEN  — HuggingFace auth token
#   OBJ_ACCESS_KEY          — Object storage access key
#   OBJ_SECRET_KEY          — Object storage secret key
#   OBJ_REGION              — Object storage region
#   OBJ_ENDPOINT_HOSTNAME   — Object storage endpoint hostname
#   MODEL_BUCKET            — Bucket name for model cache

set -euo pipefail
START_TIME=$(date +%s)

echo "=== Installing tools ($(date -u +%H:%M:%S)) ==="
pip install -q "huggingface_hub" boto3
apt-get update -qq && apt-get install -y -qq wget > /dev/null 2>&1

echo "Installing s5cmd v2.3.0..."
wget -q -O /tmp/s5cmd.tar.gz \
  "https://github.com/peak/s5cmd/releases/download/v2.3.0/s5cmd_2.3.0_Linux-64bit.tar.gz"
tar xzf /tmp/s5cmd.tar.gz -C /usr/local/bin && rm /tmp/s5cmd.tar.gz
s5cmd version

# s5cmd and boto3 require AWS env vars for auth
export AWS_ACCESS_KEY_ID="${OBJ_ACCESS_KEY}"
export AWS_SECRET_ACCESS_KEY="${OBJ_SECRET_KEY}"
export AWS_REGION="${OBJ_REGION}"
OBJ_ENDPOINT="https://${OBJ_ENDPOINT_HOSTNAME}"

echo "Ensuring bucket ${MODEL_BUCKET} exists..."
python3 - <<'PYEOF'
import os, boto3, botocore
s3 = boto3.client("s3",
    endpoint_url="https://" + os.environ["OBJ_ENDPOINT_HOSTNAME"],
    aws_access_key_id=os.environ["OBJ_ACCESS_KEY"],
    aws_secret_access_key=os.environ["OBJ_SECRET_KEY"],
    region_name=os.environ["OBJ_REGION"],
    config=botocore.config.Config(s3={"addressing_style": "path"}),
)
bucket = os.environ["MODEL_BUCKET"]
try:
    s3.head_bucket(Bucket=bucket)
    print(f"Bucket {bucket} exists.")
except botocore.exceptions.ClientError as e:
    code = int(e.response["Error"].get("Code", 0))
    if code == 404:
        print(f"Creating bucket {bucket}...")
        # Linode Object Storage ignores LocationConstraint — region
        # is determined by the endpoint URL, so create without it.
        try:
            s3.create_bucket(Bucket=bucket)
        except botocore.exceptions.ClientError as e2:
            if "BucketAlreadyOwnedByYou" in str(e2):
                pass
            else:
                raise
        print(f"Bucket {bucket} created.")
    else:
        raise
PYEOF

upload_model() {
  local hf_repo="$1"
  local s3_prefix="$2"
  local file_count
  file_count=$(s5cmd --endpoint-url "$OBJ_ENDPOINT" \
    ls "s3://${MODEL_BUCKET}/${s3_prefix}/*" 2>/dev/null | wc -l) || file_count=0
  if [ "$file_count" -gt 5 ]; then
    echo "[$(date -u +%H:%M:%S)] SKIP ${hf_repo} already cached (${file_count} files)"
    return 0
  fi
  local model_start=$(date +%s)
  echo "[$(date -u +%H:%M:%S)] DOWNLOADING ${hf_repo} from HuggingFace..."
  python3 -c "import os,sys;from huggingface_hub import snapshot_download;snapshot_download(sys.argv[1],local_dir=sys.argv[2],token=os.environ.get('HUGGING_FACE_HUB_TOKEN'));print('Downloaded '+sys.argv[1])" "${hf_repo}" "/staging/${s3_prefix}"
  local dl_end=$(date +%s)
  echo "[$(date -u +%H:%M:%S)] HF download took $((dl_end - model_start))s. UPLOADING to ${MODEL_BUCKET}/${s3_prefix}..."
  s5cmd --endpoint-url "$OBJ_ENDPOINT" sync "/staging/${s3_prefix}/*" "s3://${MODEL_BUCKET}/${s3_prefix}/"
  local upload_end=$(date +%s)
  rm -rf "/staging/${s3_prefix}"
  echo "[$(date -u +%H:%M:%S)] DONE ${hf_repo} — download: $((dl_end - model_start))s, upload: $((upload_end - dl_end))s, total: $((upload_end - model_start))s"
}

echo "=== Caching models ($(date -u +%H:%M:%S)) ==="
# MiniMax-M2.5 — large frontier MoE; download may take 30-60+ minutes
upload_model "MiniMaxAI/MiniMax-M2.5" "MiniMaxAI/MiniMax-M2.5"
# Nemotron Parse v1.2 — sub-1B OCR model, fast download
upload_model "nvidia/NVIDIA-Nemotron-Parse-v1.2" "nvidia/NVIDIA-Nemotron-Parse-v1.2" \
  || echo "WARNING: Nemotron Parse upload failed"
TOTAL_ELAPSED=$(( $(date +%s) - START_TIME ))
echo "=== Done ($(date -u +%H:%M:%S)) — total elapsed: ${TOTAL_ELAPSED}s ==="
