#!/usr/bin/env sh
# seed-streaming-config.sh — postStart hook for OpenWebUI
#
# OpenWebUI defaults to stream=false for pipeline models.  On a fresh DB
# the admin user is auto-created at startup, but their settings still have
# streaming disabled.  This script backgrounds a 5-minute retry loop that
# patches both the global config (new-user defaults) and any existing user
# rows the moment the SQLite DB appears.
#
# Usage (in a lifecycle postStart hook):
#   command: [sh, -c, "/scripts/seed-streaming-config.sh &"]

DB=/app/backend/data/webui.db

for i in $(seq 1 60); do
  [ -f "$DB" ] || { sleep 5; continue; }

  python3 -c '
import sqlite3, json, sys
db = "/app/backend/data/webui.db"
try:
    conn = sqlite3.connect(db)
    c = conn.cursor()
    changed = False
    # 1. Global config — sets default for future registrations
    c.execute("SELECT id, data FROM config ORDER BY id DESC LIMIT 1")
    row = c.fetchone()
    if row:
        data = json.loads(row[1]) if isinstance(row[1], str) else row[1]
        dp = data.setdefault("models", {}).setdefault("default_params", {})
        if dp.get("stream_response") is not True:
            dp["stream_response"] = True
            c.execute("UPDATE config SET data = ? WHERE id = ?",
                      (json.dumps(data), row[0]))
            changed = True
    # 2. Existing users — catches accounts created after boot
    c.execute("SELECT id, settings FROM user")
    for uid, raw in c.fetchall():
        s = json.loads(raw) if raw else {}
        if not isinstance(s, dict):
            s = {}
        p = s.setdefault("ui", {}).setdefault("params", {})
        if p.get("stream_response") is not True:
            p["stream_response"] = True
            c.execute("UPDATE user SET settings = ? WHERE id = ?",
                      (json.dumps(s), uid))
            changed = True
    if changed:
        conn.commit()
        print("[seed-config] patched stream_response = true")
    conn.close()
except Exception as e:
    print(f"[seed-config] {e}", file=sys.stderr)
' 2>/dev/null

  sleep 5
done
