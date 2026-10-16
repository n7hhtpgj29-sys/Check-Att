import os
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, jsonify
import psycopg

app = Flask(__name__)
EXPECTED = {"departments", "employees", "attendance_runs", "attendance_results", "schedule_settings"}

@app.get("/")
def index():
    return "<h1>Attendance V2 Staging</h1><p>Isolated from production. No scheduler or LINE enabled.</p><a href='/api/v2/health'>Database health</a>"

@app.get("/api/v2/health")
def health():
    result = {"service": "attendance-v2-staging", "time_bangkok": datetime.now(ZoneInfo("Asia/Bangkok")).isoformat()}
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith(("postgres://", "postgresql://")):
        return jsonify(result | {"database": "not_configured"}), 503
    try:
        with psycopg.connect(url, connect_timeout=8) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = %s", ("attendance_v2",))
                found = {r[0] for r in cur.fetchall()}
        missing = sorted(EXPECTED - found)
        return jsonify(result | {"database": "ready" if not missing else "incomplete", "tables_found": len(EXPECTED & found), "missing_tables": missing}), (503 if missing else 200)
    except Exception:
        return jsonify(result | {"database": "unavailable"}), 503
