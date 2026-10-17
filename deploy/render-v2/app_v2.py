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
<main><h2>Attendance V2 — Staging</h2><p>Private employee roster and missing candidates. Review all-department no-scan results. LINE requires configuration.</p>
<label>Admin token (kept in this browser tab only)<input id="token" type="password" autocomplete="off"></label>
<p><label>กะ <select id="test-shift"><option value="D">Today (D)</option><option value="N">Tonight (N)</option></select></label> <label>วันที่ <input id="work-date" type="date"></label></p>
<p><button onclick="runGroup()">ตรวจทุกแผนก</button> <button onclick="loadMissing()">สรุปรายชื่อไม่สแกน</button> <button onclick="sendLine()">ส่ง LINE</button></p>
<p><label>Upload employee CSV (EMP NO., NAME, DEPARTMENT, SHIFT)<br><input type="file" id="file" accept=".csv,text/csv"></label><br><button onclick="upload()">Import / update employees</button></p>
<section id="run-panel" style="padding:16px;background:#eaf1fb;border-radius:10px;margin:12px 0"><strong id="run-status">Run status: idle</strong><div style="height:20px;background:#d2dbe9;border-radius:12px;overflow:hidden;margin-top:12px"><div id="run-bar" style="height:100%;width:0%;background:#2376d9;transition:width .4s"></div></div><p id="run-detail" style="margin:8px 0 0">0 / 0 (0%)</p></section><pre id="output">Enter V2_ADMIN_TOKEN to continue.</pre></main>
<script>
const out=document.getElementById('output');
function headers(){return {'X-Admin-Token':sessionStorage.getItem('v2-admin-token')||document.getElementById('token').value}}
document.getElementById('token').value=sessionStorage.getItem('v2-admin-token')||'';
document.getElementById('token').addEventListener('input',e=>sessionStorage.setItem('v2-admin-token',e.target.value));
async function display(url,opts={}){try{const r=await fetch(url,{...opts,headers:{...headers(),...(opts.headers||{})}});out.textContent=JSON.stringify(await r.json(),null,2)}catch(e){out.textContent='Request failed'}}
function sourceProbe(){out.textContent='Testing source (up to 30 seconds)...';display('/api/v2/source-probe',{method:'POST'})}\nfunction testOne(){out.textContent='Checking one employee...';display('/api/v2/test-one',{method:'POST'})}\nfunction testBatch(){out.textContent='Testing three scans; please wait...';display('/api/v2/test-batch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({department:document.getElementById('test-dept').value,shift:document.getElementById('test-shift').value})})}\nlet runId=sessionStorage.getItem('v2-run-id')||'',pollTimer=null;
function showJob(j){
 if(j.job_id){runId=j.job_id;sessionStorage.setItem('v2-run-id',runId)}
 const done=j.done||0,total=j.total||0;
 const pct=total?Math.round(done*100/total):0;
 document.getElementById('run-status').textContent='Run: '+(j.status||'unknown');\n document.getElementById('run-bar').style.width=pct+'%';\n document.getElementById('run-detail').textContent=done+' / '+total+' ('+pct+'%) | '+JSON.stringify(j.counts||{});
 out.textContent=JSON.stringify(j,null,2);
 if(j.status==='running'&&!pollTimer)pollTimer=setInterval(progress,5000);
 if(j.status!=='running'&&pollTimer){clearInterval(pollTimer);pollTimer=null}
}
async function progress(){
 try{
  const url=runId?'/api/v2/group-progress/'+runId:'/api/v2/active-group';
  const r=await fetch(url,{headers:headers()});
  const j=await r.json();
  if(j.status==='idle'&&runId){runId='';sessionStorage.removeItem('v2-run-id')}\n  if(j.status)showJob(j);else out.textContent=JSON.stringify(j,null,2);
 }catch(e){out.textContent='Progress request failed'}
}
async function runGroup(){
 const d='ALL',s=document.getElementById('test-shift').value;
 try{
  const r=await fetch('/api/v2/run-group',{method:'POST',headers:{...headers(),'Content-Type':'application/json'},body:JSON.stringify({department:d,shift:s,work_date:document.getElementById('work-date').value})});
  const j=await r.json();
  if(j.job_id){showJob(j);return}
  if(j.error==='another_run_active'){runId='';await progress();return}
  out.textContent=JSON.stringify(j,null,2);
 }catch(e){out.textContent='Run request failed'}
}
\nfunction loadSummary(){display('/api/v2/summary')}
async function loadMissing(){
 out.textContent='กำลังโหลดสรุปรายชื่อ...';
 try{
  const r=await fetch('/api/v2/no-scan-list',{headers:headers()});
  const j=await r.json();
  if(!r.ok){out.textContent='ยังไม่มีผลการตรวจที่เสร็จสมบูรณ์: '+(j.error||r.status);return}
  const lines=['🚨 Attendance — ผู้ยังไม่สแกน',
   'วันที่: '+j.work_date,'กะ: '+j.shift+' | ทุกแผนก',
   'Total HC: '+j.total,'Present: '+j.scanned,
   'No Scan: '+j.no_scan,'Query Error: '+j.query_errors,
   'ตรวจไม่ครบ: '+j.unverified,'','รายชื่อผู้ยังไม่สแกน:'];
  const grouped={};
  for(const e of j.employees){(grouped[e.department]??=[]).push(e)}
  const departments=Object.keys(grouped).sort();
  lines.push('สรุปแยกแผนก:');
  for(const d of departments)lines.push(d+': '+grouped[d].length+' คน');
  for(const d of departments){
   lines.push('','['+d+'] — '+grouped[d].length+' คน');
   for(const e of grouped[d].sort((a,b)=>a.employee_no.localeCompare(b.employee_no)))lines.push('• '+e.employee_no+' - '+e.name);
  }
  if(!j.employees.length)lines.push('ไม่พบรายชื่อผู้ยังไม่สแกน');
  out.textContent=lines.join(String.fromCharCode(10));
 }catch(e){out.textContent='โหลดสรุปไม่สำเร็จ: '+e.message}
}\nfunction sendLine(){if(!confirm('Send the latest completed no-scan list to the configured LINE recipient?'))return;display('/api/v2/send-line',{method:'POST'})}
function upload(){const f=document.getElementById('file').files[0];if(!f){out.textContent='Choose CSV file';return}const form=new FormData();form.append('file',f);display('/api/v2/employees/import',{method:'POST',body:form})}
document.getElementById('token').addEventListener('change',()=>progress());\nconst bangkok=new Date(Date.now()+7*3600000);if(bangkok.getUTCHours()<5)bangkok.setUTCDate(bangkok.getUTCDate()-1);document.getElementById('work-date').value=bangkok.toISOString().slice(0,10);\n</script></html>"""

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

@app.post("/api/v2/test-batch")
@secure
def test_batch():
    """Three read-only queries. Does not store or classify missing employees."""
    payload=request.get_json(silent=True) or {}
    dept=payload.get("department")
    shift=payload.get("shift")
    if dept not in ("PEM","TE") or shift not in ("D","N"):
        return jsonify(error="invalid_department_or_shift"),400
    try:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT e.employee_no FROM attendance_v2.employees e
                    JOIN attendance_v2.departments d ON d.id=e.department_id
                    WHERE e.active AND d.code=%s AND e.shift=%s
                    ORDER BY e.employee_no LIMIT 3""",(dept,shift))
                employees=[r[0] for r in cur.fetchall()]
        if not employees:
            return jsonify(error="no_active_employees"),400
        from collector_v2 import query_employee
        from collections import Counter
        outcomes=[]
        for emp in employees:
            try:
                outcome=query_employee(emp,shift)
                outcomes.append(outcome.get("status","QUERY_ERROR"))
            except Exception:
                app.logger.exception("Batch diagnostic query failed")
                outcomes.append("QUERY_ERROR")
        return jsonify(department=dept,shift=shift,tested=len(outcomes),
                       counts=dict(Counter(outcomes)),safe_to_mark_missing=False,
                       note="Read-only diagnostic; no attendance runs or missing records saved.")
    except Exception:
        app.logger.exception("Batch diagnostic failed")
        return jsonify(error="batch_failed",safe_to_mark_missing=False),503

@app.post("/api/v2/run-group")
@secure
def run_group():
    import uuid
    from group_runner import launch, active_job
    data=request.get_json(silent=True) or {}
    dept=data.get("department");shift=data.get("shift")
    if dept not in ("PEM","TE","ALL") or shift not in ("D","N"):
        return jsonify(error="invalid_selection"),400
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT e.employee_no,e.full_name,d.code FROM attendance_v2.employees e
                JOIN attendance_v2.departments d ON d.id=e.department_id
                WHERE e.active AND (%s='ALL' OR d.code=%s) AND e.shift=%s
                ORDER BY e.employee_no""",(dept,dept,shift))
            roster=cur.fetchall()
            employees=[r[0] for r in roster]
            employee_names={r[0]:r[1] for r in roster}
            employee_departments={r[0]:r[2] for r in roster}
    if not employees:return jsonify(error="empty_roster"),400
    job_id=str(uuid.uuid4())
    from datetime import date as _date
    from zoneinfo import ZoneInfo as _ZoneInfo
    from datetime import datetime as _datetime
    work_date=data.get("work_date") or _datetime.now(_ZoneInfo("Asia/Bangkok")).date().isoformat()
    try:
        _date.fromisoformat(work_date)
    except ValueError:
        return jsonify(error="invalid_work_date"),400
    if not launch(job_id,employees,shift,work_date,dept,employee_names,employee_departments):
        return jsonify(error="another_run_active",**(active_job() or {})),409
    return jsonify(job_id=job_id,total=len(employees),status="running",
                   safe_to_mark_missing=False,note="Temporary in-memory progress; no attendance results saved."),202

@app.get("/api/v2/group-progress/<job_id>")
@secure
def group_progress(job_id):
    from group_runner import jobs
    job=jobs.get(job_id)
    if job is None:return jsonify(error="job_not_found_or_worker_restarted"),404
    return jsonify(**job,safe_to_mark_missing=False)

@app.get("/api/v2/active-group")
@secure
def active_group():
    from group_runner import active_job
    job=active_job()
    if job is None:
        return jsonify(status="idle",total=0,done=0,counts={})
    return jsonify(**job,safe_to_mark_missing=False)

@app.get("/api/v2/review-candidates")
@secure
def review_candidates():
    from group_runner import jobs
    result=[]
    for job_id,job in reversed(list(jobs.items())[-10:]):
        candidates=[{"employee_no":r["employee_no"],"name":r["name"],"status":r["status"]}
                    for r in job.get("results",[]) if r["status"] in ("INCOMPLETE","QUERY_ERROR")]
        if candidates:
            result.append({"job_id":job_id,"department":job.get("department"),
                "shift":job.get("shift"),"work_date":job.get("work_date"),
                "run_status":job["status"],"checked":job["done"],"total":job["total"],
                "candidates":candidates})
    return jsonify(review_only=True,confirmed_absent=0,runs=result,
                   note="Unverified scans are not confirmed absences. In-memory only.")

def _latest_completed_job():
    from group_runner import jobs
    return next(((jid,j) for jid,j in reversed(list(jobs.items())) if j.get("status")=="completed"),(None,None))

def _no_scan_report():
    jid,job=_latest_completed_job()
    if not job:
        return None
    missing=[{"employee_no":r["employee_no"],"name":r["name"],"department":r.get("department",job["department"])}
             for r in job.get("results",[]) if r["status"]=="NO_SCAN_IN_WINDOW"]
    missing.sort(key=lambda r:(r["department"],r["employee_no"]))
    from collections import Counter
    department_counts=dict(sorted(Counter(r["department"] for r in missing).items()))
    return {"department_counts":department_counts,"job_id":jid,"department":job["department"],"shift":job["shift"],
            "work_date":job["work_date"],"total":job["total"],
            "scanned":job["counts"].get("SCAN_FOUND",0),
            "no_scan":len(missing),
            "unverified":job["counts"].get("INCOMPLETE",0),
            "query_errors":job["counts"].get("QUERY_ERROR",0),
            "employees":missing}

def _format_no_scan_message(report):
    from datetime import timedelta
    day=datetime.strptime(report["work_date"],"%Y-%m-%d").date()
    date_label=day.strftime("%d/%m/%Y")
    if report["shift"]=="N":
        date_label+=" → "+(day+timedelta(days=1)).strftime("%d/%m/%Y")
    lines=["🚨 Attendance — ผู้ยังไม่สแกน",
           "วันที่: "+date_label,
           "กะ: "+report["shift"]+" | ทุกแผนก",
           "",
           "Total HC: "+str(report["total"]),
           "Present: "+str(report["scanned"]),
           "No Scan: "+str(report["no_scan"]),
           "Query Error: "+str(report["query_errors"]),
           "ตรวจไม่ครบ: "+str(report["unverified"]),
           "",
           "สรุปแยกแผนก:"]
    lines += [dept+": "+str(count)+" คน" for dept,count in report["department_counts"].items()]
    lines.append("")
    lines.append("รายชื่อผู้ยังไม่สแกน:")
    for dept,count in report["department_counts"].items():
        lines.append("["+dept+"] — "+str(count)+" คน")
        lines += ["• "+r["employee_no"]+" - "+r["name"] for r in report["employees"] if r["department"]==dept]
    if not report["employees"]:
        lines.append("ไม่พบรายชื่อผู้ยังไม่สแกน")
    return "\n".join(lines)


def _db_no_scan_report(shift=None, work_date=None, scheduled_only=False):
    """Read a completed, durable ALL-department result; never return partial runs."""
    from collections import Counter
    conditions=["r.status='completed'","d.code='ALL'"]
    args=[]
    if shift:
        conditions.append("r.shift=%s")
        args.append(shift)
    if work_date:
        conditions.append("r.work_date=%s")
        args.append(work_date)
    if scheduled_only:
        conditions.append("r.trigger_type='scheduled'")
    query="""SELECT r.id,r.shift,r.work_date,r.total_employees,
                    r.trigger_type,r.scheduled_key
             FROM attendance_v2.attendance_runs r
             JOIN attendance_v2.departments d ON d.id=r.department_id
             WHERE """+" AND ".join(conditions)+" ORDER BY r.finished_at DESC,r.id DESC LIMIT 1"
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(query,tuple(args))
            row=cur.fetchone()
            if row is None:
                return None
            run_id,s,day,total,trigger_type,key=row
            cur.execute("""SELECT a.employee_no,e.full_name,d.code,a.status
                           FROM attendance_v2.attendance_results a
                           JOIN attendance_v2.employees e ON e.employee_no=a.employee_no
                           JOIN attendance_v2.departments d ON d.id=e.department_id
                           WHERE a.run_id=%s ORDER BY d.code,a.employee_no""",(run_id,))
            rows=cur.fetchall()
    if len(rows)!=total or total==0:
        return None
    counts=Counter(r[3] for r in rows)
    missing=[{"employee_no":r[0],"name":r[1],"department":r[2]}
             for r in rows if r[3]=="NO_SCAN_IN_WINDOW"]
    department_counts=dict(sorted(Counter(r["department"] for r in missing).items()))
    return {"department_counts":department_counts,
            "job_id":key or "V2:DB:"+str(run_id),
            "department":"ALL","shift":s,"work_date":str(day),
            "trigger_type":trigger_type,"status":"completed",
            "total":total,"scanned":counts.get("SCAN_FOUND",0),
            "no_scan":len(missing),"unverified":counts.get("INCOMPLETE",0),
            "query_errors":counts.get("QUERY_ERROR",0),"employees":missing}

@app.get("/api/v2/no-scan-list")
@secure
def no_scan_list():
    shift=request.args.get("shift")
    work_date=request.args.get("work_date")
    scheduled_only=request.args.get("scheduled_only")=="1"
    if bool(shift) != bool(work_date):
        return jsonify(error="shift_and_work_date_must_be_paired"),400
    if shift and shift not in ("D","N"):
        return jsonify(error="invalid_shift"),400
    if work_date:
        from datetime import date as _date
        try:
            _date.fromisoformat(work_date)
        except ValueError:
            return jsonify(error="invalid_work_date"),400
    try:
        if shift or scheduled_only:
            report=_db_no_scan_report(shift,work_date,scheduled_only)
        else:
            report=_no_scan_report() or _db_no_scan_report()
    except Exception:
        app.logger.exception("Failed to read V2 completed report")
        return jsonify(error="report_database_unavailable"),503
    if not report:
        if scheduled_only:
            return jsonify(ready=False,status="not_ready",shift=shift,work_date=work_date),200
        return jsonify(error="no_matching_completed_run",shift=shift,work_date=work_date),404
    return jsonify(ready=True,**report,line_message=_format_no_scan_message(report),
                   note="No scan detected, not confirmed absence; verify leave and shift exceptions.")

@app.post("/api/v2/send-line")
@secure
def send_line():
    import urllib.request,json
    report=_no_scan_report()
    if not report:return jsonify(error="no_completed_run"),409
    token=os.getenv("LINE_CHANNEL_ACCESS_TOKEN","")
    recipient=os.getenv("LINE_TO_ID","")
    if not token or not recipient:
        return jsonify(error="line_not_configured",
                       required=["LINE_CHANNEL_ACCESS_TOKEN","LINE_TO_ID"]),409
    lines=["Attendance — No scan detected",
           f"{report['department']} / {report['shift']} / {report['work_date']}",
           f"Total: {report['total']} | Scanned: {report['scanned']} | No scan: {report['no_scan']}",
           f"Unverified: {report['unverified']} | Query errors: {report['query_errors']}"]
    lines.append('สรุปแยกแผนก:')
    lines += [f'{dept}: {count} คน' for dept,count in report['department_counts'].items()]
    for dept,count in report['department_counts'].items():
        lines.append(f'[{dept}] — {count} คน')
        lines += ['• '+r['employee_no']+' - '+r['name'] for r in report['employees'] if r['department']==dept]
    lines.append("No scan is not confirmed absence; check leave records.")
    message="\n".join(lines)
    if len(message)>4800:
        return jsonify(error="line_message_too_long"),409
    payload=json.dumps({"to":recipient,"messages":[{"type":"text","text":message}]}).encode()
    req=urllib.request.Request("https://api.line.me/v2/bot/message/push",
        data=payload,headers={"Authorization":"Bearer "+token,
        "Content-Type":"application/json"},method="POST")
    try:
        with urllib.request.urlopen(req,timeout=12) as response:
            if response.status!=200:return jsonify(error="line_send_failed"),502
        return jsonify(sent=True,job_id=report["job_id"],no_scan=report["no_scan"])
    except Exception:
        app.logger.exception("LINE push failed")
        return jsonify(error="line_send_failed"),502

@app.post('/api/v2/scheduled-run')
@secure
def scheduled_run():
    from datetime import date as _date
    import uuid
    from group_runner import launch,active_job,jobs
    payload=request.get_json(silent=True) or {}
    shift=payload.get('shift')
    work_date=payload.get('work_date')
    if shift not in ('D','N') or not isinstance(work_date,str):
        return jsonify(error='shift_and_work_date_required'),400
    try:
        day=_date.fromisoformat(work_date)
    except ValueError:
        return jsonify(error='invalid_work_date'),400
    if abs((_date.today()-day).days)>7:
        return jsonify(error='date_outside_allowed_range'),400
    try:
        completed=_db_no_scan_report(shift,work_date,scheduled_only=True)
    except Exception:
        app.logger.exception("Failed to check previously completed schedule")
        return jsonify(error="schedule_database_unavailable"),503
    if completed:
        return jsonify(job_id=completed["job_id"],status="completed",already_exists=True,
                       total=completed["total"]),200
    for jid,j in reversed(list(jobs.items())):
        if j.get('department')=='ALL' and j.get('shift')==shift and j.get('work_date')==work_date and j.get('status') in ('running','completed'):
            return jsonify(job_id=jid,status=j['status'],already_exists=True),200
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT e.employee_no,e.full_name,d.code FROM attendance_v2.employees e JOIN attendance_v2.departments d ON d.id=e.department_id WHERE e.active AND e.shift=%s ORDER BY e.employee_no',(shift,))
            roster=cur.fetchall()
    if not roster:
        return jsonify(error='empty_roster'),409
    ids=[r[0] for r in roster]
    names={r[0]:r[1] for r in roster}
    depts={r[0]:r[2] for r in roster}
    jid=str(uuid.uuid4())
    if not launch(jid,ids,shift,work_date,'ALL',names,depts,trigger_type='scheduled'):
        return jsonify(error='another_run_active',active=active_job()),409
    return jsonify(job_id=jid,status='running',total=len(ids)),202
