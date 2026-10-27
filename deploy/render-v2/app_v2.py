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
<p><button onclick="runGroup()">ตรวจทุกแผนก</button> <button onclick="loadMissing()">สรุปรายชื่อไม่สแกน</button> <button onclick="auditRoster()">ตรวจยอดทะเบียน</button> <button onclick="sendLine()">ส่ง LINE</button></p>
<div style="border:1px solid #d5deef;border-radius:10px;padding:14px;margin:14px 0">
<strong>นำเข้าทะเบียนพนักงาน / Employee Roster</strong><p style="margin:8px 0;font-size:13px">รองรับ CSV: Emp., Name, Dept, SHIFT (DS/NS หรือ D/N)</p>
<input type="file" id="roster-file" accept=".csv,text/csv" style="width:100%;max-width:100%;box-sizing:border-box">
<p style="font-size:14px"><label><input type="checkbox" id="replace-roster"> แทนที่ทะเบียนทั้งชุด (ปิดใช้งานพนักงานเดิมที่ไม่มีในไฟล์ใหม่)</label></p>
<button type="button" id="roster-import-btn" onclick="uploadRoster()">ตรวจสอบและนำเข้ารายชื่อ</button>
<pre id="import-feedback" role="status" aria-live="polite" style="min-height:28px">กรุณาเลือกไฟล์ CSV</pre>
</div>
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
 if(j.status==='completed' && j.roster_matches_current===false){
  document.getElementById('run-status').textContent='ผลตรวจเก่า — ไม่ตรงทะเบียนล่าสุด';
  document.getElementById('run-detail').textContent='เคยตรวจ '+total+' คน / Active ปัจจุบัน '+j.active_shift_count+' คน — กรุณากดตรวจใหม่';
  out.textContent='ผลตรวจเดิมไม่สามารถใช้สรุป No Scan ปัจจุบันได้'+
   '\\nรหัสที่อยู่ในผลเดิม แต่ไม่อยู่ในกะ Active: '+(j.no_longer_in_shift||[]).join(', ')+
   '\\nรหัส Active ที่ยังไม่ได้ตรวจในรอบเดิม: '+(j.not_checked_from_active_roster||[]).join(', ');
 }else{
  out.textContent=JSON.stringify(j,null,2);
 }
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
async function auditRoster(){
 out.textContent='กำลังตรวจยอดทะเบียน Active จาก Supabase...';
 try{
  const response=await fetch('/api/v2/roster-audit',{headers:headers()});
  const data=await response.json();
  if(!response.ok){out.textContent='ตรวจยอดไม่สำเร็จ: '+(data.error||response.status);return}
  const lines=['ฐานข้อมูล: '+data.source,
    'ทะเบียน Active '+data.active_total+' คน | กะ D '+data.shifts.D+' คน | กะ N '+data.shifts.N+' คน',
    'พนักงานที่ปิดใช้งาน: '+data.inactive_total+' คน'];
  if(data.last_completed_run){
   const x=data.last_completed_run;
   lines.push('','ผลตรวจล่าสุด ('+x.source+'): กะ '+x.shift+' วันที่ '+x.work_date,
              'รอบนี้ตรวจ '+x.total+' คน | Active ปัจจุบันกะนี้ '+x.active_shift_count+' คน',
              x.roster_matches_current?'ผลตรวจตรงกับทะเบียน Active ล่าสุด':'ผลตรวจเก่าไม่ตรงทะเบียน Active — ต้องตรวจใหม่');
   if(x.no_longer_in_shift?.length)lines.push('รหัสในผลเก่าแต่ไม่อยู่ในกะ Active: '+x.no_longer_in_shift.join(', '));
   if(x.not_checked_from_active_roster?.length)lines.push('รหัส Active ที่ไม่ถูกตรวจ: '+x.not_checked_from_active_roster.join(', '));
  }
  out.textContent=lines.join(String.fromCharCode(10));
 }catch(e){out.textContent='ตรวจยอดไม่สำเร็จ: '+e.message}
}
async function loadMissing(){
 out.textContent='กำลังโหลดสรุปรายชื่อ...';
 try{
  const r=await fetch('/api/v2/no-scan-list',{headers:headers()});
  const j=await r.json();
  if(!r.ok){
   if(j.error==='roster_changed_after_scan'){
    out.textContent='ผลตรวจเดิมไม่ตรงทะเบียนล่าสุด — ยังไม่ใช่ข้อมูลสำหรับส่ง LINE'+
     '\\nรอบเดิมตรวจ '+j.previous_checked+' คน | Active ปัจจุบันกะ '+j.shift+': '+j.active_shift_count+' คน'+
     '\\nคนในผลเก่าที่ไม่ได้ Active ในกะนี้: '+(j.no_longer_in_shift||[]).join(', ')+
     '\\nคนใน Active ปัจจุบันที่ไม่ถูกตรวจในรอบเดิม: '+(j.not_checked_from_active_roster||[]).join(', ')+
     '\\nกรุณากด ตรวจทุกแผนก ใหม่ก่อนสรุป';
    return;
   }
   out.textContent='ยังไม่มีผลตรวจที่พร้อมใช้: '+(j.message||j.error||r.status);return
  }
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
  lines.push('','ข้อมูลล่าสุด query เมื่อ : '+(j.last_query_display||'ไม่พบเวลาจบการตรวจ'));
  out.textContent=lines.join(String.fromCharCode(10));
 }catch(e){out.textContent='โหลดสรุปไม่สำเร็จ: '+e.message}
}\nfunction sendLine(){if(!confirm('Send the latest completed no-scan list to the configured LINE recipient?'))return;display('/api/v2/send-line',{method:'POST'})}
async function uploadRoster(){
 const fileInput=document.querySelector('#roster-file');
 const status=document.querySelector('#import-feedback');
 const button=document.querySelector('#roster-import-btn');
 const file=fileInput && fileInput.files && fileInput.files.item(0);
 if(!file){status.textContent='ยังไม่ได้เลือกไฟล์ CSV กรุณาเลือกไฟล์ก่อนนำเข้า';return}
 if(!file.name.toLowerCase().endsWith('.csv')){status.textContent='รองรับไฟล์ CSV เท่านั้น';return}
 const replace=document.querySelector('#replace-roster').checked;
 const form=new FormData();form.append('file',file);form.append('replace_roster',replace?'1':'0');
 button.disabled=true;
 try{
  status.textContent='กำลังตรวจสอบไฟล์ '+file.name+' ...';
  const auth=headers();
  const opts={method:'POST',headers:auth,body:form};
  const previewRes=await fetch('/api/v2/employees/import?dry_run=1',opts);
  const preview=await previewRes.json();
  if(!previewRes.ok){status.textContent='ตรวจไฟล์ไม่ผ่าน ('+previewRes.status+'): '+(preview.message||preview.error||JSON.stringify(preview));return}
  let details='ตรวจพบ '+preview.imported+' คน (D '+preview.shifts.D+', N '+preview.shifts.N+')'+
   '\\nเพิ่มใหม่ '+preview.added+' | เปลี่ยนข้อมูล '+preview.changed+' | ใช้งานอยู่แล้ว '+preview.unchanged+
   '\\nโหมด: '+(replace?'แทนที่ทะเบียนทั้งหมด (ปิดใช้งาน '+preview.deactivated+' คน)':'เพิ่ม/อัปเดตเท่านั้น ไม่ปิดคนเดิม')+
   '\\nแผนก: '+Object.entries(preview.departments).map(([k,v])=>k+'='+v).join(', ');
  status.textContent=details;
  if(!confirm(details+'\\n\\nยืนยันนำเข้าทะเบียนนี้หรือไม่?')){status.textContent+='\\nยกเลิกการนำเข้า ยังไม่ได้แก้ไขฐานข้อมูล';return}
  status.textContent='กำลังบันทึกข้อมูล '+file.name+' ...';
  const res=await fetch('/api/v2/employees/import',{method:'POST',headers:auth,body:form});
  const result=await res.json();
  if(!res.ok){status.textContent='นำเข้าไม่สำเร็จ ('+res.status+'): '+(result.message||result.error||JSON.stringify(result));return}
  status.textContent='นำเข้าสำเร็จ ✓ '+result.imported+' คน | เพิ่มใหม่ '+result.added+
   ' | เปลี่ยนข้อมูล '+result.changed+' | ปิดคนที่ไม่มีในไฟล์ '+result.deactivated+
   '\\nกะ D '+result.shifts.D+' คน / กะ N '+result.shifts.N+' คน'+
   '\\nยอดพนักงาน Active หลังนำเข้า: '+result.active_total+
   '\\nผลตรวจเดิมใช้ทะเบียนก่อน Import กรุณากด ตรวจทุกแผนก ใหม่';
  runId='';
  sessionStorage.removeItem('v2-run-id');
  if(pollTimer){clearInterval(pollTimer);pollTimer=null}
  document.getElementById('run-status').textContent='ทะเบียนอัปเดตแล้ว — ต้องตรวจใหม่';
  document.getElementById('run-bar').style.width='0%';
  document.getElementById('run-detail').textContent='Active D '+result.shifts.D+' / N '+result.shifts.N+' | ผลเดิมถูกยกเลิกจากหน้าจอ';
  out.textContent='นำเข้าแล้ว '+result.active_total+' คน (D '+result.shifts.D+', N '+result.shifts.N+')'+
    '\\nโปรดกด ตรวจทุกแผนก เพื่อใช้ทะเบียนล่าสุด';
 }catch(e){status.textContent='การเชื่อมต่อล้มเหลว: '+e.message}
 finally{button.disabled=false}
}
document.querySelector('#roster-file').addEventListener('change',e=>{
 const f=e.target.files && e.target.files.item(0);
 document.querySelector('#import-feedback').textContent=f?'เลือกไฟล์ '+f.name+' ('+f.size+' bytes)':'กรุณาเลือกไฟล์ CSV';
});
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
                cur.execute("SELECT d.name,e.shift,count(*) FROM attendance_v2.employees e JOIN attendance_v2.departments d ON d.id=e.department_id WHERE e.active GROUP BY d.code,e.shift ORDER BY d.code,e.shift")
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
                cur.execute("""SELECT r.id,r.work_date,r.shift,d.name,e.employee_no,e.full_name
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
    """Preview and import complete CSV rosters, without silently deleting employees."""
    from collections import Counter
    from group_runner import active_job

    source=request.files.get("file")
    if source is None or not source.filename or not source.filename.lower().endswith(".csv"):
        return jsonify(error="csv_file_required",
                       message="กรุณาเลือกไฟล์ CSV ก่อนกดนำเข้า"),400

    try:
        text=source.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        return jsonify(error="csv_must_be_utf8",
                       message="ไฟล์ต้องบันทึกเป็น CSV UTF-8"),400

    reader=csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return jsonify(error="missing_csv_headers"),400
    aliases={
        "EMP.":"employee_no","EMP":"employee_no","EMP NO.":"employee_no",
        "EMP NO":"employee_no","EMPLOYEE_NO":"employee_no",
        "EMPLOYEE ID":"employee_no","NAME":"full_name","FULL_NAME":"full_name",
        "DEPARTMENT":"department","DEPT":"department","SHIFT":"shift"
    }
    columns={key:aliases.get((key or "").strip().upper()) for key in reader.fieldnames}
    if not {"employee_no","full_name","department","shift"}.issubset(set(columns.values())):
        return jsonify(error="required_columns",
                       message="หัวตารางไม่ตรง กรุณาใช้ Emp., Name, Dept, SHIFT",
                       found=reader.fieldnames,
                       accepted=["Emp.","Name","Dept","SHIFT"]),400

    entries={}
    labels={}
    for lineno,record in enumerate(reader,2):
        data={columns[key]:(value or "").strip() for key,value in record.items()
              if key is not None and columns.get(key)}
        number=data.get("employee_no","").upper()
        name=data.get("full_name","").strip()
        display_dept=data.get("department","").upper()
        # Preserve "ME/EE" in the department display name, while using a
        # constraint-safe code "ME-EE" in attendance_v2.departments.code.
        dept_code=display_dept.replace("/","-")
        raw_shift=data.get("shift","").upper()
        shift={"DS":"D","NS":"N","D":"D","N":"N"}.get(raw_shift)
        if (not re.fullmatch(r"[A-Z0-9-]{2,24}",number) or not name or
            len(name)>160 or not re.fullmatch(r"[A-Z0-9_/-]{1,24}",display_dept) or
            not re.fullmatch(r"[A-Z0-9_-]{1,24}",dept_code) or shift is None):
            return jsonify(error="invalid_row",row=lineno,
                           message="ข้อมูลรหัสพนักงาน ชื่อ แผนก หรือกะไม่ถูกต้อง",
                           employee_no=number),400
        if number in entries:
            return jsonify(error="duplicate_employee_no",row=lineno,
                           employee_no=number),400
        if dept_code in labels and labels[dept_code]!=display_dept:
            return jsonify(error="department_code_conflict",row=lineno),400
        labels[dept_code]=display_dept
        entries[number]=(name,dept_code,shift)
        if len(entries)>5000:
            return jsonify(error="too_many_rows"),400

    if not entries:
        return jsonify(error="empty_roster"),400

    dry_run=request.args.get("dry_run")=="1"
    replace_roster=request.form.get("replace_roster")=="1"
    if not dry_run and active_job() is not None:
        return jsonify(error="attendance_run_in_progress",
                       message="กำลังตรวจพนักงานอยู่ กรุณานำเข้าหลังตรวจเสร็จ"),409

    try:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT e.employee_no,e.full_name,d.code,e.shift,e.active
                               FROM attendance_v2.employees e
                               JOIN attendance_v2.departments d ON d.id=e.department_id""")
                existing={no:(name,dept,shift,active)
                          for no,name,dept,shift,active in cur.fetchall()}
                currently_active={no for no,values in existing.items() if values[3]}
                added=sum(no not in existing for no in entries)
                changed=sum(no in existing and (
                    existing[no][0]!=v[0] or existing[no][1]!=v[1] or
                    existing[no][2]!=v[2] or not existing[no][3]
                ) for no,v in entries.items())
                unchanged=len(entries)-added-changed
                deactivated=(len(currently_active-set(entries)) if replace_roster else 0)
                active_total=(len(entries) if replace_roster else
                              len(currently_active|set(entries)))
                shifts=dict(Counter(v[2] for v in entries.values()))
                shifts={"D":shifts.get("D",0),"N":shifts.get("N",0)}
                departments=dict(sorted(Counter(labels[v[1]] for v in entries.values()).items()))
                summary={"imported":len(entries),"added":added,
                         "changed":changed,"unchanged":unchanged,
                         "deactivated":deactivated,
                         "active_total":active_total,
                         "replace_roster":replace_roster,
                         "departments":departments,"shifts":shifts}
                if dry_run:
                    return jsonify(preview=True,**summary)

                for code,label in sorted(labels.items()):
                    cur.execute("""INSERT INTO attendance_v2.departments(code,name)
                                   VALUES(%s,%s)
                                   ON CONFLICT(code) DO UPDATE SET name=excluded.name""",
                                (code,label))
                    for shift_name,run_time in (("D","08:15"),("N","20:15")):
                        cur.execute("""INSERT INTO attendance_v2.schedule_settings(
                                         department_id,shift,enabled,run_time)
                                       SELECT id,%s,false,%s FROM attendance_v2.departments
                                       WHERE code=%s
                                       ON CONFLICT(department_id,shift) DO NOTHING""",
                                    (shift_name,run_time,code))

                for no,(name,code,shift_name) in entries.items():
                    cur.execute("""INSERT INTO attendance_v2.employees(
                                      employee_no,full_name,department_id,shift,active)
                                   VALUES(%s,%s,
                                      (SELECT id FROM attendance_v2.departments WHERE code=%s),
                                      %s,true)
                                   ON CONFLICT(employee_no) DO UPDATE SET
                                      full_name=excluded.full_name,
                                      department_id=excluded.department_id,
                                      shift=excluded.shift,active=true,updated_at=now()""",
                                (no,name,code,shift_name))
                if replace_roster:
                    cur.execute("""UPDATE attendance_v2.employees
                                   SET active=false,updated_at=now()
                                   WHERE active=true AND NOT (employee_no = ANY(%s))""",
                                (list(entries),))
                cur.execute("SELECT count(*) FROM attendance_v2.employees WHERE active=true")
                summary["active_total"]=cur.fetchone()[0]
                return jsonify(success=True,**summary)
    except Exception:
        app.logger.exception("V2 employee roster import failed")
        return jsonify(error="import_failed",
                       message="ไม่สามารถบันทึกข้อมูลได้ กรุณาตรวจสอบ Server log"),503


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
        # Use the SAME collector as the scheduled V2 run, not the obsolete
        # single-person diagnostic that had a different query implementation.
        from fast_collector import scan_group
        shift_date=datetime.now(BKK).date().isoformat()
        status=next(scan_group([row[0]],"D",shift_date),"QUERY_ERROR")
        return jsonify(employee_no=row[0],status=status,
                       safe_to_mark_missing=False,
                       note="Diagnostic only. Does not store results or send LINE.")
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
            cur.execute("""SELECT e.employee_no,e.full_name,d.name FROM attendance_v2.employees e
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
    if job.get("status")=="completed":
        comparison=_compare_run_to_active_roster(
            job["shift"],[r["employee_no"] for r in job.get("results",[])])
        return jsonify(**job,**comparison,safe_to_mark_missing=False)
    return jsonify(**job,safe_to_mark_missing=False)

@app.get("/api/v2/active-group")
@secure
def active_group():
    from group_runner import active_job
    job=active_job()
    if job is None:
        return jsonify(status="idle",total=0,done=0,counts={})
    return jsonify(**job,safe_to_mark_missing=False)

@app.get("/api/v2/roster-audit")
@secure
def roster_audit():
    """Show the current roster and whether the last checked run is still valid."""
    from group_runner import jobs
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT e.shift,count(*)
                           FROM attendance_v2.employees e
                           WHERE e.active=true GROUP BY e.shift ORDER BY e.shift""")
            counts=dict(cur.fetchall())
            cur.execute("SELECT count(*) FROM attendance_v2.employees WHERE active=false")
            inactive=cur.fetchone()[0]
    latest=next(((jid,j) for jid,j in reversed(list(jobs.items()))
                 if j.get("status")=="completed"),None)
    last=None
    if latest:
        jid,job=latest
        last={"job_id":jid,"shift":job["shift"],"work_date":job["work_date"],
              "total":job["total"],"source":"current_server_memory",
              **_compare_run_to_active_roster(
                  job["shift"],[r["employee_no"] for r in job.get("results",[])])}
    else:
        saved=_db_no_scan_report()
        if saved:
            last={"job_id":saved["job_id"],"shift":saved["shift"],
                  "work_date":saved["work_date"],"total":saved["total"],
                  "source":"attendance_v2.attendance_runs",
                  "roster_matches_current":saved["roster_matches_current"],
                  "active_shift_count":saved["active_shift_count"],
                  "no_longer_in_shift":saved["no_longer_in_shift"],
                  "not_checked_from_active_roster":saved["not_checked_from_active_roster"]}
    return jsonify(source="Supabase PostgreSQL / attendance_v2.employees",
                   active_total=counts.get("D",0)+counts.get("N",0),
                   shifts={"D":counts.get("D",0),"N":counts.get("N",0)},
                   inactive_total=inactive,last_completed_run=last)


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

def _compare_run_to_active_roster(shift, snapshot_ids):
    """Compare employee IDs checked in one run with the current ACTIVE roster."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT employee_no FROM attendance_v2.employees
                           WHERE active=true AND shift=%s""",(shift,))
            current={r[0] for r in cur.fetchall()}
    checked=set(snapshot_ids)
    removed=sorted(checked-current)
    added=sorted(current-checked)
    return {
        "roster_matches_current": not removed and not added,
        "active_shift_count":len(current),
        "checked_roster_count":len(checked),
        "no_longer_in_shift":removed,
        "not_checked_from_active_roster":added
    }


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
    comparison=_compare_run_to_active_roster(
        job["shift"],[r["employee_no"] for r in job.get("results",[])])
    return {"department_counts":department_counts,**comparison,
            "job_id":jid,"department":job["department"],"shift":job["shift"],
            "work_date":job["work_date"],"total":job["total"],
            "last_query_at":job.get("query_completed_at") or job.get("finished_at"),
            "scanned":job["counts"].get("SCAN_FOUND",0),
            "no_scan":len(missing),
            "unverified":job["counts"].get("INCOMPLETE",0),
            "query_errors":job["counts"].get("QUERY_ERROR",0),
            "employees":missing}

def _format_query_completed_at(value):
    """Format the actual scan completion time in Bangkok, not LINE sent time."""
    if not value:
        return "ไม่พบเวลาจบการตรวจ"
    try:
        moment=datetime.fromisoformat(value.replace("Z","+00:00")) if isinstance(value,str) else value
        if moment.tzinfo is None:
            moment=moment.replace(tzinfo=BKK)
        moment=moment.astimezone(BKK)
    except (TypeError,ValueError,AttributeError):
        return "ไม่พบเวลาจบการตรวจ"
    month=("Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec")[moment.month-1]
    return f"{moment.day:02d}/{month}/{moment.year:04d} {moment:%H:%M:%S}"


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
    lines.extend(["", "ข้อมูลล่าสุด query เมื่อ : "+_format_query_completed_at(report.get("last_query_at"))])
    return "\n".join(lines)


def _db_no_scan_report(shift=None, work_date=None, scheduled_only=False, run_key=None):
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
    if run_key:
        conditions.append("r.scheduled_key=%s")
        args.append(run_key)
    query="""SELECT r.id,r.shift,r.work_date,r.total_employees,
                    r.trigger_type,r.scheduled_key,r.finished_at
             FROM attendance_v2.attendance_runs r
             JOIN attendance_v2.departments d ON d.id=r.department_id
             WHERE """+" AND ".join(conditions)+" ORDER BY r.finished_at DESC,r.id DESC LIMIT 1"
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(query,tuple(args))
            row=cur.fetchone()
            if row is None:
                return None
            run_id,s,day,total,trigger_type,key,query_finished_at=row
            cur.execute("""SELECT a.employee_no,e.full_name,d.name,a.status,a.detail
                           FROM attendance_v2.attendance_results a
                           JOIN attendance_v2.employees e ON e.employee_no=a.employee_no
                           JOIN attendance_v2.departments d ON d.id=e.department_id
                           WHERE a.run_id=%s ORDER BY d.code,a.employee_no""",(run_id,))
            rows=cur.fetchall()
            cur.execute("""SELECT employee_no FROM attendance_v2.employees
                           WHERE active=true AND shift=%s""",(s,))
            current={r[0] for r in cur.fetchall()}
    if len(rows)!=total or total==0:
        return None
    checked={r[0] for r in rows}
    removed=sorted(checked-current)
    added=sorted(current-checked)
    roster_audit={"roster_matches_current":not removed and not added,
                  "active_shift_count":len(current),
                  "checked_roster_count":len(checked),
                  "no_longer_in_shift":removed,
                  "not_checked_from_active_roster":added}
    counts=Counter(r[3] for r in rows)
    import json
    missing=[]
    for r in rows:
        if r[3]!="NO_SCAN_IN_WINDOW":
            continue
        try:
            snapshot=json.loads(r[4]) if r[4] else {}
        except (TypeError,ValueError):
            snapshot={}
        missing.append({"employee_no":r[0],
                        "name":snapshot.get("name",r[1]),
                        "department":snapshot.get("department",r[2])})
    department_counts=dict(sorted(Counter(r["department"] for r in missing).items()))
    return {"department_counts":department_counts,**roster_audit,
            "job_id":key or "V2:DB:"+str(run_id),
            "department":"ALL","shift":s,"work_date":str(day),
            "trigger_type":trigger_type,"status":"completed",
            "last_query_at":query_finished_at.isoformat() if query_finished_at else None,
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
    if not report.get("roster_matches_current",False):
        return jsonify(ready=False,error="roster_changed_after_scan",
                       message="ผลตรวจชุดนี้ใช้รายชื่อก่อนแก้ไขทะเบียน กรุณากดตรวจทุกแผนกใหม่",
                       shift=report["shift"],work_date=report["work_date"],
                       previous_checked=report["total"],
                       active_shift_count=report["active_shift_count"],
                       no_longer_in_shift=report["no_longer_in_shift"],
                       not_checked_from_active_roster=report["not_checked_from_active_roster"]),409
    return jsonify(ready=True,**report,
                   last_query_display=_format_query_completed_at(report.get("last_query_at")),
                   line_message=_format_no_scan_message(report),
                   note="No scan detected, not confirmed absence; verify leave and shift exceptions.")

@app.post("/api/v2/send-line")
@secure
def send_line():
    import urllib.request,json
    report=_no_scan_report()
    if not report:return jsonify(error="no_completed_run"),409
    if not report.get("roster_matches_current",False):
        return jsonify(error="roster_changed_after_scan",
                       message="กรุณาตรวจพนักงานใหม่ก่อนส่ง LINE"),409
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
    lines.append("")
    lines.append("ข้อมูลล่าสุด query เมื่อ : "+_format_query_completed_at(report.get("last_query_at")))
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
    from datetime import timedelta
    payload=request.get_json(silent=True)
    if payload is None:
        payload={}
    if not isinstance(payload,dict):
        return jsonify(error='invalid_json_body'),400
    shift=payload.get('shift')
    work_date=payload.get('work_date')
    now=datetime.now(BKK)
    if shift is None and work_date is None:
        # Make.com sends {} only. Resolve dates and shifts on the Thailand server.
        # 00:00-04:59 belongs to the preceding night shift.
        shift='N' if now.hour < 5 or now.hour >= 17 else 'D'
        work_day=now.date()-timedelta(days=1) if now.hour < 5 else now.date()
        work_date=work_day.isoformat()
    elif shift not in ('D','N') or not isinstance(work_date,str):
        return jsonify(error='shift_and_work_date_required',
                       detail='Either omit both to use Bangkok time, or send shift D/N and YYYY-MM-DD work_date'),400
    try:
        day=_date.fromisoformat(work_date)
    except ValueError:
        return jsonify(error='invalid_work_date'),400
    if abs((now.date()-day).days)>7:
        return jsonify(error='date_outside_allowed_range'),400
    # Every Make execution starts a new scan against the ACTIVE roster.
    # Previously completed results must never be reused after a roster import.
    current=active_job()
    if current:
        return jsonify(error='another_run_active',job_id=current.get('job_id'),
                       status=current.get('status')),409
    invocation_id=str(uuid.uuid4())
    scheduled_key='V2:ALL:'+shift+':'+work_date+':'+invocation_id
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT e.employee_no,e.full_name,d.name FROM attendance_v2.employees e JOIN attendance_v2.departments d ON d.id=e.department_id WHERE e.active AND e.shift=%s ORDER BY e.employee_no',(shift,))
            roster=cur.fetchall()
    if not roster:
        return jsonify(error='empty_roster'),409
    ids=[r[0] for r in roster]
    names={r[0]:r[1] for r in roster}
    depts={r[0]:r[2] for r in roster}
    jid=str(uuid.uuid4())
    if not launch(jid,ids,shift,work_date,'ALL',names,depts,
                  trigger_type='scheduled',scheduled_key=scheduled_key):
        return jsonify(error='another_run_active',active=active_job()),409
    return jsonify(job_id=scheduled_key,status='running',total=len(ids),shift=shift,
                   work_date=work_date,invocation_id=invocation_id),202


def _ensure_delivery_claims(cur):
    """Private V2-only, durable LINE idempotency table."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance_v2.line_delivery_claims (
            job_key text PRIMARY KEY,
            shift text NOT NULL CHECK (shift IN ('D','N')),
            work_date date NOT NULL,
            state text NOT NULL DEFAULT 'claimed'
                CHECK (state IN ('claimed','sent')),
            claimed_at timestamptz NOT NULL DEFAULT now(),
            sent_at timestamptz
        )
    """)


@app.post("/api/v2/line-delivery-claim")
@secure
def line_delivery_claim():
    """Acquire one sending permission per Make execution, not per day.

    Repeated poll bundles within one Run once share invocation_id and cannot
    generate duplicate LINE sends. A second Run once gets a new invocation_id.
    """
    data=request.get_json(silent=True) or {}
    if not isinstance(data,dict):
        return jsonify(error="invalid_json"),400
    shift=data.get("shift")
    work_date=data.get("work_date")
    job_id=data.get("job_id")
    invocation_id=data.get("invocation_id")
    import uuid
    try:
        if not isinstance(invocation_id,str) or str(uuid.UUID(invocation_id))!=invocation_id:
            raise ValueError("missing or invalid invocation ID")
    except ValueError:
        return jsonify(error="valid_invocation_id_required"),400
    if shift not in ("D","N") or not isinstance(work_date,str):
        return jsonify(error="shift_and_work_date_required"),400
    try:
        from datetime import date as _date
        day=_date.fromisoformat(work_date)
    except ValueError:
        return jsonify(error="invalid_work_date"),400
    if abs((datetime.now(BKK).date()-day).days)>1:
        return jsonify(error="date_outside_allowed_range"),400
    legacy="V2:ALL:"+shift+":"+work_date
    expected=legacy+":"+invocation_id
    claim_key="V2:RUN:"+invocation_id
    # Legacy Make v6 constructs the day-level key; accept it only alongside
    # the valid invocation ID while reading exclusively that run's snapshot.
    if job_id is not None and job_id not in (legacy,expected):
        return jsonify(error="job_id_mismatch",claimed=False),400
    try:
        report=_db_no_scan_report(shift,work_date,scheduled_only=True,run_key=expected)
        if report is None:
            return jsonify(ready=False,claimed=False,reason="not_ready"),200
        if report["job_id"]!=expected or report["status"]!="completed" or report["department"]!="ALL":
            return jsonify(ready=False,claimed=False,reason="report_mismatch"),200
        if not report.get("roster_matches_current",False):
            return jsonify(ready=False,claimed=False,reason="roster_changed_after_scan",
                           previous_checked=report["total"],
                           active_shift_count=report["active_shift_count"]),200
        if report["query_errors"] or report["unverified"] or report["total"] <= 0 or (
            report["scanned"]+report["no_scan"] != report["total"]
        ):
            return jsonify(ready=False,claimed=False,reason="incomplete_report"),200
        message=_format_no_scan_message(report)
        if len(message)>4800:
            return jsonify(ready=False,claimed=False,reason="line_message_too_long"),200
        with connect() as conn:
            with conn.cursor() as cur:
                _ensure_delivery_claims(cur)
                cur.execute("""
                    INSERT INTO attendance_v2.line_delivery_claims(job_key,shift,work_date)
                    VALUES (%s,%s,%s)
                    ON CONFLICT (job_key) DO NOTHING
                    RETURNING job_key
                """,(claim_key,shift,work_date))
                claimed=cur.fetchone() is not None
        if not claimed:
            return jsonify(ready=True,claimed=False,already_claimed=True,job_id=expected,invocation_id=invocation_id),200
        return jsonify(ready=True,claimed=True,job_id=expected,
                       invocation_id=invocation_id,line_message=message,shift=shift,work_date=work_date,
                       total=report["total"],no_scan=report["no_scan"]),200
    except Exception:
        app.logger.exception("V2 LINE delivery claim failure")
        return jsonify(error="claim_database_unavailable"),503


@app.post("/api/v2/line-delivery-ack")
@secure
def line_delivery_ack():
    """Record a confirmed successful LINE response; does not unlock the claim."""
    data=request.get_json(silent=True) or {}
    if not isinstance(data,dict):
        return jsonify(error="invalid_json"),400
    invocation_id=data.get("invocation_id")
    import uuid
    try:
        if not isinstance(invocation_id,str) or str(uuid.UUID(invocation_id))!=invocation_id:
            raise ValueError("missing or invalid invocation ID")
    except ValueError:
        return jsonify(error="valid_invocation_id_required"),400
    claim_key="V2:RUN:"+invocation_id
    try:
        with connect() as conn:
            with conn.cursor() as cur:
                _ensure_delivery_claims(cur)
                cur.execute("""
                    UPDATE attendance_v2.line_delivery_claims
                    SET state='sent',sent_at=COALESCE(sent_at,now())
                    WHERE job_key=%s RETURNING job_key
                """,(claim_key,))
                found=cur.fetchone() is not None
        if not found:
            return jsonify(error="claim_not_found"),404
        return jsonify(acknowledged=True,invocation_id=invocation_id),200
    except Exception:
        app.logger.exception("V2 LINE acknowledgement failure")
        return jsonify(error="ack_database_unavailable"),503


@app.post("/api/v2/line-delivery-wait")
@secure
def line_delivery_wait():
    """Single blocking status check for one Make execution.

    Poll on Render instead of expanding Make repeater branches. Only attempt
    a DB claim when the completed report is valid; Make sends just once.
    """
    import time
    import uuid
    data=request.get_json(silent=True)
    if not isinstance(data,dict):
        return jsonify(error="json_body_required"),400
    shift=data.get("shift")
    work_date=data.get("work_date")
    invocation_id=data.get("invocation_id")
    if shift not in ("D","N") or not isinstance(work_date,str):
        return jsonify(error="shift_and_work_date_required"),400
    try:
        from datetime import date as _date
        day=_date.fromisoformat(work_date)
        if not isinstance(invocation_id,str) or str(uuid.UUID(invocation_id))!=invocation_id:
            raise ValueError("invalid invocation ID")
    except ValueError:
        return jsonify(error="invalid_work_date_or_invocation"),400
    if abs((datetime.now(BKK).date()-day).days)>1:
        return jsonify(error="date_outside_allowed_range"),400
    legacy="V2:ALL:"+shift+":"+work_date
    expected=legacy+":"+invocation_id
    if data.get("job_id") not in (legacy,expected):
        return jsonify(error="job_id_mismatch"),400
    try:
        max_wait=int(data.get("wait_seconds",260))
    except (TypeError,ValueError):
        return jsonify(error="invalid_wait_seconds"),400
    if max_wait<0 or max_wait>265:
        return jsonify(error="wait_seconds_out_of_range"),400
    deadline=time.monotonic()+max_wait
    while True:
        # Skip expensive database queries while the in-memory collector is running.
        from group_runner import jobs
        current=[j for j in list(jobs.values()) if
                 j.get("trigger_type")=="scheduled" and
                 j.get("department")=="ALL" and
                 j.get("scheduled_key")==expected]
        if current and current[-1].get("status")=="failed":
            return jsonify(ready=False,claimed=False,reason="collector_failed"),200
        if not current or current[-1].get("status")!="running":
            response=line_delivery_claim.__wrapped__()
            body=(response[0] if isinstance(response,tuple) else response).get_json(silent=True) or {}
            if body.get("claimed") or body.get("already_claimed") or body.get("error"):
                return response
            if body.get("reason")!="not_ready":
                return response
        remaining=deadline-time.monotonic()
        if remaining<=0:
            return jsonify(ready=False,claimed=False,reason="wait_timeout",
                           shift=shift,work_date=work_date),200
        time.sleep(min(4,remaining))
