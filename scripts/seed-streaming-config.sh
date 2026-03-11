#!/usr/bin/env sh
# seed-streaming-config.sh — postStart hook for OpenWebUI
#
# OpenWebUI defaults to stream=false for pipeline models.  This script
# uses the Admin API to set DEFAULT_MODEL_PARAMS with stream_response=true
# so the PersistentConfig in-memory cache is updated (not just the DB).
#
# Usage (in a lifecycle postStart hook):
#   command: [sh, -c, "/scripts/seed-streaming-config.sh &"]

BASE="http://localhost:8080"

for i in $(seq 1 60); do
  # Wait for health endpoint
  STATUS=$(python3 -c "
import urllib.request, sys
try:
    r = urllib.request.urlopen('${BASE}/health', timeout=3)
    print(r.status)
except Exception:
    print(0)
" 2>/dev/null)

  [ "$STATUS" = "200" ] || { sleep 5; continue; }

  python3 -c "
import urllib.request, json, os, sys

base = '${BASE}'
email = os.environ.get('WEBUI_ADMIN_EMAIL', '')
password = os.environ.get('WEBUI_ADMIN_PASSWORD', '')
if not email or not password:
    print('[seed-config] WEBUI_ADMIN_EMAIL/PASSWORD not set', file=sys.stderr)
    sys.exit(0)

def api(method, path, data=None, token=None):
    body = json.dumps(data).encode() if data else None
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = urllib.request.Request(f'{base}{path}', data=body, headers=headers, method=method)
    resp = urllib.request.urlopen(req, timeout=10)
    return json.loads(resp.read())

# 1. Sign in
auth = api('POST', '/api/v1/auths/signin', {'email': email, 'password': password})
token = auth.get('token', '')
if not token:
    print('[seed-config] signin failed', file=sys.stderr)
    sys.exit(1)

# 2. Get current models config
cfg = api('GET', '/api/v1/configs/models', token=token)
params = cfg.get('DEFAULT_MODEL_PARAMS') or {}
if params.get('stream_response') is True:
    print('[seed-config] already configured')
    sys.exit(0)

# 3. Update with stream_response=true
params['stream_response'] = True
cfg['DEFAULT_MODEL_PARAMS'] = params
result = api('POST', '/api/v1/configs/models', cfg, token=token)
print(f'[seed-config] patched DEFAULT_MODEL_PARAMS: {result.get(\"DEFAULT_MODEL_PARAMS\")}')
" 2>&1

  # If python succeeded, we're done
  [ $? -eq 0 ] && exit 0
  sleep 5
done
