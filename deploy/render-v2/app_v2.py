import os, csv, io, re, hmac
from datetime import datetime
from zoneinfo import ZoneInfo
from functools import wraps
from flask import Flask, jsonify, request, Response
import psycopg

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024
EXPECTED = {"departments","employees","attendance_runs","attendance_results","schedule_settings"}
BKK = ZoneInfo("Asia/Bangkok")

def connect():
    return psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=8, options="-c statement_timeout=10000")

def secure(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        token = os.environ.get("V2_ADMIN_TOKEN", "")
        supplied = request.headers.get("X-Admin-Token", "")
        if len(token) < 24 or not hmac.compare_digest(supplied, token):
            return jsonify(error="unauthorized"), 401
        return fn(*args, **kwargs)
    return wrapped

@app.get("/")
def home():
    return """<!doctype html><html lang="th"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Attendance V2 Staging</title><style>body{font:16px system-ui;max-width:850px;margin:40px auto;padding:18px;background:#f5f7fb;color:#17253d}main{background:white;padding:28px;border-radius:14px}input,button{padding:10px;margin:5px 0}input[type=password]{width:95%}button{cursor:pointer}pre{white-space:pre-wrap;word-break:break-word;background:#f1f4f9;padding:12px;border-radius:8px}</style>
<main><h2>Attendance V2 — Staging</h2><p>Private employee roster and missing candidates. No automatic collector or LINE sending yet.</p>
<label>Admin token (kept in this browser tab only)<input id="token" type="password" autocomplete="off"></label>
<p><button onclick="sourceProbe()">Test source connection</button> <button onclick="testOne()">Test one scan</button> <button onclick="loadSummary()">View summary</button> <button onclick="loadMissing()">View missing candidates</button></p>
<p><label>Upload employee CSV (EMP NO., NAME, DEPARTMENT, SHIFT)<br><input type="file" id="file" accept=".csv,text/csv"></label><br><button onclick="upload()">Import / update employees</button></p>
<pre id="output">Enter V2_ADMIN_TOKEN to continue.</pre></main>
<script>
const out=document.getElementById('output');
function headers(){return {'X-Admin-Token':document.getElementById('token').value}}
async function display(url,opts={}){try{const r=await fetch(url,{...opts,headers:{...headers(),...(opts.headers||{})}});out.textContent=JSON.stringify(await r.json(),null,2)}catch(e){out.textContent='Request failed'}}
function sourceProbe(){out.textContent='Testing source (up to 30 seconds)...';display('/api/v2/source-probe',{method:'POST'})}\nfunction testOne(){out.textContent='Checking one employee...';display('/api/v2/test-one',{method:'POST'})}\nfunction loadSummary(){display('/api/v2/summary')}
function loadMissing(){display('/api/v2/missing')}
function upload(){const f=document.getElementById('file').files[0];if(!f){out.textContent='Choose CSV file';return}const form=new FormData();form.append('file',f);display('/api/v2/employees/import',{method:'POST',body:form})}
</script></html>"""

@app.get("/api/v2/health")
def health():
    base={"service":"attendance-v2-staging","time_bangkok":datetime.now(BKK).isoformat()}
    if not os.getenv("DATABASE_URL","").startswith(("postgres://","postgresql://")):
        return jsonify(base | {"database":"not_configured"}),503
    try:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=%s",("attendance_v2",))
                found={r[0] for r in cur.fetchall()}
        missing=sorted(EXPECTED-found)
        return jsonify(base | {"database":"ready" if not missing else "incomplete","tables_found":len(EXPECTED & found),"missing_tables":missing}),503 if missing else 200
    except Exception:
        return jsonify(base | {"database":"unavailable"}),503

@app.get("/api/v2/summary")
@secure
def summary():
    try:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT d.code,e.shift,count(*) FROM attendance_v2.employees e JOIN attendance_v2.departments d ON d.id=e.department_id WHERE e.active GROUP BY d.code,e.shift ORDER BY d.code,e.shift")
                roster=[{"department":d,"shift":s,"employees":n} for d,s,n in cur.fetchall()]
                cur.execute("SELECT id,work_date,shift,status,missing_count,error_count,started_at FROM attendance_v2.attendance_runs ORDER BY started_at DESC LIMIT 20")
                runs=[{"run_id":i,"work_date":str(w),"shift":s,"status":st,"missing_count":m,"error_count":e,"started_at":str(t)} for i,w,s,st,m,e,t in cur.fetchall()]
        return jsonify(roster=roster,recent_runs=runs)
    except Exception:
        return jsonify(error="database_query_failed"),503

@app.get("/api/v2/missing")
@secure
def missing():
    try:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT r.id,r.work_date,r.shift,d.code,e.employee_no,e.full_name
                  FROM attendance_v2.attendance_results a
                  JOIN attendance_v2.attendance_runs r ON r.id=a.run_id
                  JOIN attendance_v2.departments d ON d.id=r.department_id
                  JOIN attendance_v2.employees e ON e.employee_no=a.employee_no
                  WHERE a.status='NO_SCAN_IN_WINDOW' AND r.status='completed'
                  ORDER BY r.started_at DESC,e.employee_no LIMIT 200""")
                rows=[{"run_id":i,"work_date":str(w),"shift":s,"department":d,"employee_no":no,"name":name} for i,w,s,d,no,name in cur.fetchall()]
        return jsonify(missing=rows)
    except Exception:
        return jsonify(error="database_query_failed"),503

@app.post("/api/v2/employees/import")
@secure
def import_employees():
    file=request.files.get("file")
    if not file or not file.filename.lower().endswith(".csv"):
        return jsonify(error="csv_file_required"),400
    try:
        raw=file.read().decode("utf-8-sig")
        reader=csv.DictReader(io.StringIO(raw))
        if not reader.fieldnames: raise ValueError("Missing header")
        aliases={"EMP NO.":"employee_no","EMP NO":"employee_no","EMPLOYEE_NO":"employee_no","NAME":"full_name","FULL_NAME":"full_name","DEPARTMENT":"department","DEPT":"department","SHIFT":"shift"}
        columns={k:aliases.get(k.strip().upper()) for k in reader.fieldnames}
        if not {"employee_no","full_name","department","shift"}.issubset(set(columns.values())):
            return jsonify(error="required_columns",expected=["EMP NO.","NAME","DEPARTMENT","SHIFT"]),400
        entries={}
        for idx,record in enumerate(reader,2):
            normalized={columns[k]:(v or "").strip() for k,v in record.items() if k in columns and columns[k]}
            no=normalized["employee_no"].upper();name=normalized["full_name"];dept=normalized["department"].upper();shift=normalized["shift"].upper()
            if not re.fullmatch(r"[A-Z0-9-]{2,24}",no) or not name or len(name)>160 or not re.fullmatch(r"[A-Z0-9_-]{1,24}",dept) or shift not in ("D","N"):
                return jsonify(error="invalid_row",row=idx),400
            if no in entries: return jsonify(error="duplicate_employee_no",row=idx),400
            entries[no]=(name,dept,shift)
            if len(entries)>5000:return jsonify(error="too_many_rows"),400
        if not entries:return jsonify(error="empty_roster"),400
        with connect() as conn:
            with conn.cursor() as cur:
                for dept in sorted({v[1] for v in entries.values()}):
                    cur.execute("INSERT INTO attendance_v2.departments(code,name) VALUES(%s,%s) ON CONFLICT(code) DO NOTHING",(dept,dept))
                    for shift,run_time in (("D","08:15"),("N","20:15")):
                        cur.execute("""INSERT INTO attendance_v2.schedule_settings(department_id,shift,enabled,run_time)
                        SELECT id,%s,false,%s FROM attendance_v2.departments WHERE code=%s
                        ON CONFLICT(department_id,shift) DO NOTHING""",(shift,run_time,dept))
                for no,(name,dept,shift) in entries.items():
                    cur.execute("""INSERT INTO attendance_v2.employees(employee_no,full_name,department_id,shift,active)
                    VALUES(%s,%s,(SELECT id FROM attendance_v2.departments WHERE code=%s),%s,true)
                    ON CONFLICT(employee_no) DO UPDATE SET full_name=excluded.full_name,
                    department_id=excluded.department_id,shift=excluded.shift,active=true,updated_at=now()""",(no,name,dept,shift))
        return jsonify(imported=len(entries),note="Upsert only; employees not in CSV are unchanged. Scheduling stays disabled.")
    except UnicodeDecodeError:
        return jsonify(error="csv_must_be_utf8"),400
    except Exception:
        return jsonify(error="import_failed"),503

@app.post("/api/v2/source-probe")
@secure
def source_probe():
    """Manual source connectivity only; never writes attendance or marks missing."""
    try:
        from collector_v2 import probe_source
        return jsonify(probe_source())
    except Exception:
        app.logger.exception("V2 source probe failed")
        return jsonify(source="unavailable",safe_to_mark_missing=False,error="browser_or_network_failure"),503

@app.post("/api/v2/test-one")
@secure
def test_one():
    """Read-only one-person scan test. Never creates a missing record."""
    try:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT employee_no FROM attendance_v2.employees WHERE active AND shift='D' ORDER BY employee_no LIMIT 1")
                row=cur.fetchone()
        if not row:
            return jsonify(error="no_day_shift_employee"),400
        from collector_v2 import query_employee
        result=query_employee(row[0],"D")
        return jsonify(result)
    except Exception:
        app.logger.exception("Single scan diagnostic failed")
        return jsonify(status="QUERY_ERROR",safe_to_mark_missing=False,error="query_failed"),503
