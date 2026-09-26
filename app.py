from __future__ import annotations
import os,re,sqlite3,threading,time,uuid,json
from zoneinfo import ZoneInfo
from datetime import datetime,date,time as dtime,timedelta
from pathlib import Path
from flask import Flask,jsonify,render_template,request,send_from_directory
from openpyxl import load_workbook
from playwright.sync_api import sync_playwright
try:
 import psycopg
 from psycopg.rows import dict_row
except Exception:
 psycopg=None
 dict_row=None

BASE=Path(__file__).resolve().parent
DATA=BASE/'data'; DATA.mkdir(exist_ok=True)
DB=DATA/'attendance.db'
TARGET='https://webapp.calcomp.co.th/att/'
VERSION='12.1-always-visible-query-status'
BKK=ZoneInfo('Asia/Bangkok')
DATABASE_URL=os.getenv('DATABASE_URL','').strip()
AUTO_QUERY_TOKEN=os.getenv('AUTO_QUERY_TOKEN','').strip()
AUTO_GRACE_MINUTES=int(os.getenv('AUTO_GRACE_MINUTES','180'))
app=Flask(__name__)
app.config['MAX_CONTENT_LENGTH']=20*1024*1024
jobs={}; lock=threading.Lock(); query_run_lock=threading.Lock()
STARTED_AT=datetime.now().isoformat(timespec='seconds')

def log(msg): print(f'[ATT] {datetime.now().isoformat(timespec="seconds")} {msg}', flush=True)
def db():
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c

def clean(v): return '' if v is None else str(int(v) if isinstance(v,float) and v.is_integer() else v).strip()
def norm_dept(v): return re.sub(r'[^A-Z0-9_-]+','-',clean(v).upper()).strip('-_')[:24]

def init():
 with db() as c:
  c.execute('CREATE TABLE IF NOT EXISTS employees(employee_code TEXT PRIMARY KEY,full_name TEXT,department TEXT,position TEXT,active INTEGER DEFAULT 1,updated_at TEXT)')
  c.execute("CREATE TABLE IF NOT EXISTS attendance(employee_code TEXT PRIMARY KEY,name_from_web TEXT,latest_datetime TEXT,status TEXT,query_at TEXT,scan_in TEXT DEFAULT '',scan_out TEXT DEFAULT '',raw_count INTEGER DEFAULT 0,ot_minutes INTEGER DEFAULT 0,work_date TEXT DEFAULT '')")
  c.execute('CREATE TABLE IF NOT EXISTS departments(code TEXT PRIMARY KEY,name TEXT,active INTEGER DEFAULT 1,updated_at TEXT)')
  ec={x[1] for x in c.execute('PRAGMA table_info(employees)')}
  for n in ('location_support','team_support','group_code','shift'):
   if n not in ec:c.execute(f"ALTER TABLE employees ADD COLUMN {n} TEXT DEFAULT ''")
  ac={x[1] for x in c.execute('PRAGMA table_info(attendance)')}
  for n in ('scan_in','scan_out','work_date'):
   if n not in ac:c.execute(f"ALTER TABLE attendance ADD COLUMN {n} TEXT DEFAULT ''")
  if 'raw_count' not in ac:c.execute('ALTER TABLE attendance ADD COLUMN raw_count INTEGER DEFAULT 0')
  if 'ot_minutes' not in ac:c.execute('ALTER TABLE attendance ADD COLUMN ot_minutes INTEGER DEFAULT 0')
  now=datetime.now().isoformat(timespec='seconds')
  # v8 and earlier had a department column but did not use it. Preserve the existing PE master.
  c.execute("UPDATE employees SET department='PE' WHERE TRIM(COALESCE(department,''))='' ")
  c.execute("INSERT OR IGNORE INTO departments(code,name,active,updated_at) VALUES('PE','PE',1,?)",(now,))
  for row in c.execute("SELECT DISTINCT department FROM employees WHERE TRIM(COALESCE(department,''))<>''"):
   d=norm_dept(row[0])
   if d:c.execute('INSERT OR IGNORE INTO departments(code,name,active,updated_at) VALUES(?,?,1,?)',(d,d,now))
init()

# ---------------------------
# V11 persistent auto-schedule store
# ---------------------------
DEFAULT_AUTO_SCHEDULE={
 'enabled':1,
 'weekdays':'0,1,2,3,4,5,6', # Monday=0 ... Sunday=6
 'day1_time':'08:15',
 'day2_time':'18:00',
 'night1_time':'20:15',
 'night_final_time':'06:00',
}
AUTO_SLOTS=(
 ('day1','day1_time','DAY','TODAY DAY'),
 ('day2','day2_time','DAY','TODAY DAY'),
 ('night1','night1_time','TONIGHT','TONIGHT'),
 ('night_final','night_final_time','LAST_NIGHT','NIGHT FINAL'),
)

def bkk_now(): return datetime.now(BKK)
def schedule_store_kind(): return 'postgres' if DATABASE_URL and psycopg else 'sqlite'

def _pg_conn():
 if not (DATABASE_URL and psycopg): return None
 return psycopg.connect(DATABASE_URL,row_factory=dict_row,connect_timeout=10)

def init_auto_store():
 if schedule_store_kind()=='postgres':
  with _pg_conn() as c:
   with c.cursor() as cur:
    cur.execute("""CREATE TABLE IF NOT EXISTS auto_schedules(
      department TEXT PRIMARY KEY,
      enabled BOOLEAN NOT NULL DEFAULT TRUE,
      weekdays TEXT NOT NULL DEFAULT '0,1,2,3,4,5,6',
      day1_time TEXT NOT NULL DEFAULT '08:15',
      day2_time TEXT NOT NULL DEFAULT '18:00',
      night1_time TEXT NOT NULL DEFAULT '20:15',
      night_final_time TEXT NOT NULL DEFAULT '06:00',
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
    cur.execute("""CREATE TABLE IF NOT EXISTS auto_query_runs(
      department TEXT NOT NULL,
      slot_key TEXT NOT NULL,
      slot_date DATE NOT NULL,
      mode TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'claimed',
      job_id TEXT DEFAULT '',
      started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      finished_at TIMESTAMPTZ,
      message TEXT DEFAULT '',
      PRIMARY KEY(department,slot_key,slot_date))""")
  return
 with db() as c:
  c.execute("""CREATE TABLE IF NOT EXISTS auto_schedules(
    department TEXT PRIMARY KEY,enabled INTEGER NOT NULL DEFAULT 1,
    weekdays TEXT NOT NULL DEFAULT '0,1,2,3,4,5,6',
    day1_time TEXT NOT NULL DEFAULT '08:15',day2_time TEXT NOT NULL DEFAULT '18:00',
    night1_time TEXT NOT NULL DEFAULT '20:15',night_final_time TEXT NOT NULL DEFAULT '06:00',
    updated_at TEXT NOT NULL DEFAULT '')""")
  c.execute("""CREATE TABLE IF NOT EXISTS auto_query_runs(
    department TEXT NOT NULL,slot_key TEXT NOT NULL,slot_date TEXT NOT NULL,mode TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'claimed',job_id TEXT DEFAULT '',started_at TEXT NOT NULL DEFAULT '',
    finished_at TEXT DEFAULT '',message TEXT DEFAULT '',PRIMARY KEY(department,slot_key,slot_date))""")

def ensure_auto_schedule(dept):
 d=norm_dept(dept)
 if not d:return
 now=bkk_now().isoformat(timespec='seconds')
 if schedule_store_kind()=='postgres':
  with _pg_conn() as c:
   with c.cursor() as cur:
    cur.execute("""INSERT INTO auto_schedules(department,enabled,weekdays,day1_time,day2_time,night1_time,night_final_time,updated_at)
      VALUES(%s,TRUE,%s,%s,%s,%s,%s,NOW()) ON CONFLICT(department) DO NOTHING""",
      (d,DEFAULT_AUTO_SCHEDULE['weekdays'],DEFAULT_AUTO_SCHEDULE['day1_time'],DEFAULT_AUTO_SCHEDULE['day2_time'],DEFAULT_AUTO_SCHEDULE['night1_time'],DEFAULT_AUTO_SCHEDULE['night_final_time']))
  return
 with db() as c:
  c.execute("""INSERT OR IGNORE INTO auto_schedules(department,enabled,weekdays,day1_time,day2_time,night1_time,night_final_time,updated_at)
    VALUES(?,?,?,?,?,?,?,?)""",(d,1,DEFAULT_AUTO_SCHEDULE['weekdays'],DEFAULT_AUTO_SCHEDULE['day1_time'],DEFAULT_AUTO_SCHEDULE['day2_time'],DEFAULT_AUTO_SCHEDULE['night1_time'],DEFAULT_AUTO_SCHEDULE['night_final_time'],now))

def get_auto_schedule(dept):
 d=norm_dept(dept);ensure_auto_schedule(d)
 if schedule_store_kind()=='postgres':
  with _pg_conn() as c:
   with c.cursor() as cur:
    cur.execute('SELECT department,enabled,weekdays,day1_time,day2_time,night1_time,night_final_time,updated_at FROM auto_schedules WHERE department=%s',(d,))
    r=cur.fetchone()
 else:
  with db() as c:r=c.execute('SELECT department,enabled,weekdays,day1_time,day2_time,night1_time,night_final_time,updated_at FROM auto_schedules WHERE department=?',(d,)).fetchone()
 if not r:return None
 x=dict(r);x['enabled']=bool(x.get('enabled'));x['weekdays']=[int(z) for z in str(x.get('weekdays') or '').split(',') if str(z).strip().isdigit()]
 return x

def _valid_hhmm(v):
 try:
  datetime.strptime(clean(v),'%H:%M');return True
 except:return False

def save_auto_schedule(dept,payload):
 d=norm_dept(dept)
 if not d:return None
 times={k:clean(payload.get(k)) for k in ('day1_time','day2_time','night1_time','night_final_time')}
 for k,v in times.items():
  if not _valid_hhmm(v):raise ValueError(f'Invalid time for {k}: {v}. Use HH:MM')
 weekdays=payload.get('weekdays',list(range(7)))
 try:weekdays=sorted({int(x) for x in weekdays if 0<=int(x)<=6})
 except:raise ValueError('weekdays must be 0..6')
 if not weekdays:raise ValueError('Select at least one workday')
 enabled=bool(payload.get('enabled',True));wd=','.join(map(str,weekdays));now=bkk_now().isoformat(timespec='seconds')
 if schedule_store_kind()=='postgres':
  with _pg_conn() as c:
   with c.cursor() as cur:
    cur.execute("""INSERT INTO auto_schedules(department,enabled,weekdays,day1_time,day2_time,night1_time,night_final_time,updated_at)
      VALUES(%s,%s,%s,%s,%s,%s,%s,NOW()) ON CONFLICT(department) DO UPDATE SET enabled=EXCLUDED.enabled,weekdays=EXCLUDED.weekdays,day1_time=EXCLUDED.day1_time,day2_time=EXCLUDED.day2_time,night1_time=EXCLUDED.night1_time,night_final_time=EXCLUDED.night_final_time,updated_at=NOW()""",
      (d,enabled,wd,times['day1_time'],times['day2_time'],times['night1_time'],times['night_final_time']))
 else:
  with db() as c:c.execute("""INSERT INTO auto_schedules(department,enabled,weekdays,day1_time,day2_time,night1_time,night_final_time,updated_at)
    VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(department) DO UPDATE SET enabled=excluded.enabled,weekdays=excluded.weekdays,day1_time=excluded.day1_time,day2_time=excluded.day2_time,night1_time=excluded.night1_time,night_final_time=excluded.night_final_time,updated_at=excluded.updated_at""",
    (d,1 if enabled else 0,wd,times['day1_time'],times['day2_time'],times['night1_time'],times['night_final_time'],now))
 return get_auto_schedule(d)

def last_auto_run(dept):
 d=norm_dept(dept)
 if schedule_store_kind()=='postgres':
  with _pg_conn() as c:
   with c.cursor() as cur:
    cur.execute('SELECT department,slot_key,slot_date,mode,status,job_id,started_at,finished_at,message FROM auto_query_runs WHERE department=%s ORDER BY started_at DESC LIMIT 1',(d,));r=cur.fetchone()
 else:
  with db() as c:r=c.execute('SELECT department,slot_key,slot_date,mode,status,job_id,started_at,finished_at,message FROM auto_query_runs WHERE department=? ORDER BY started_at DESC LIMIT 1',(d,)).fetchone()
 if not r:return None
 x=dict(r)
 for k in ('slot_date','started_at','finished_at'):
  if x.get(k) is not None:x[k]=str(x[k])
 return x

def next_auto_run(sched,from_dt=None):
 if not sched or not sched.get('enabled'):return None
 now=from_dt or bkk_now();allowed=set(sched.get('weekdays') or [])
 cand=[]
 for off in range(0,8):
  d=(now+timedelta(days=off)).date()
  if d.weekday() not in allowed:continue
  for slot,key,mode,label in AUTO_SLOTS:
   hhmm=sched.get(key)
   if not _valid_hhmm(hhmm):continue
   tt=datetime.strptime(hhmm,'%H:%M').time();dt=datetime.combine(d,tt,tzinfo=BKK)
   if dt>now:cand.append((dt,slot,mode,label))
 if not cand:return None
 dt,slot,mode,label=min(cand,key=lambda x:x[0]);return {'at':dt.isoformat(timespec='minutes'),'slot_key':slot,'mode':mode,'label':label}

def _run_state(dept,slot_key,slot_date):
 if schedule_store_kind()=='postgres':
  with _pg_conn() as c:
   with c.cursor() as cur:
    cur.execute('SELECT * FROM auto_query_runs WHERE department=%s AND slot_key=%s AND slot_date=%s',(dept,slot_key,slot_date));r=cur.fetchone()
 else:
  with db() as c:r=c.execute('SELECT * FROM auto_query_runs WHERE department=? AND slot_key=? AND slot_date=?',(dept,slot_key,slot_date)).fetchone()
 return dict(r) if r else None

def claim_auto_run(dept,slot_key,slot_date,mode):
 now=bkk_now();r=_run_state(dept,slot_key,slot_date)
 if r:
  status=clean(r.get('status')).lower()
  if status=='done':return False
  if status in ('claimed','running'):
   try:
    st=datetime.fromisoformat(str(r.get('started_at')))
    if st.tzinfo is None:st=st.replace(tzinfo=BKK)
    if (now-st).total_seconds()<3600:return False
   except:pass
 if schedule_store_kind()=='postgres':
  with _pg_conn() as c:
   with c.cursor() as cur:
    cur.execute("""INSERT INTO auto_query_runs(department,slot_key,slot_date,mode,status,job_id,started_at,finished_at,message)
      VALUES(%s,%s,%s,%s,'claimed','',NOW(),NULL,'') ON CONFLICT(department,slot_key,slot_date) DO UPDATE SET mode=EXCLUDED.mode,status='claimed',job_id='',started_at=NOW(),finished_at=NULL,message=''""",(dept,slot_key,slot_date,mode))
 else:
  with db() as c:c.execute("""INSERT INTO auto_query_runs(department,slot_key,slot_date,mode,status,job_id,started_at,finished_at,message)
    VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(department,slot_key,slot_date) DO UPDATE SET mode=excluded.mode,status='claimed',job_id='',started_at=excluded.started_at,finished_at='',message=''""",(dept,slot_key,slot_date,mode,'claimed','',now.isoformat(timespec='seconds'),'',''))
 return True

def complete_auto_run(dept,slot_key,slot_date,status,job_id='',message=''):
 status='done' if clean(status).lower()=='done' else 'error';now=bkk_now().isoformat(timespec='seconds')
 if schedule_store_kind()=='postgres':
  with _pg_conn() as c:
   with c.cursor() as cur:cur.execute('UPDATE auto_query_runs SET status=%s,job_id=%s,finished_at=NOW(),message=%s WHERE department=%s AND slot_key=%s AND slot_date=%s',(status,clean(job_id),clean(message)[:500],dept,slot_key,slot_date))
 else:
  with db() as c:c.execute('UPDATE auto_query_runs SET status=?,job_id=?,finished_at=?,message=? WHERE department=? AND slot_key=? AND slot_date=?',(status,clean(job_id),now,clean(message)[:500],dept,slot_key,slot_date))

def auto_token_ok(req):
 if not AUTO_QUERY_TOKEN:return False
 return req.headers.get('X-Auto-Query-Token','')==AUTO_QUERY_TOKEN

init_auto_store()
with db() as _c:
 for _r in _c.execute("SELECT code FROM departments WHERE active=1"):ensure_auto_schedule(_r[0])

def ensure_department(code,name=None):
 d=norm_dept(code)
 if not d:return ''
 now=datetime.now().isoformat(timespec='seconds')
 with db() as c:
  c.execute('INSERT INTO departments(code,name,active,updated_at) VALUES(?,?,1,?) ON CONFLICT(code) DO UPDATE SET name=COALESCE(NULLIF(excluded.name,\'\'),departments.name),active=1,updated_at=excluded.updated_at',(d,clean(name) or d,now))
 try: ensure_auto_schedule(d)
 except Exception as e: log(f'AUTO SCHEDULE INIT ERROR dept={d} {type(e).__name__}: {e}')
 return d

def normpos(v):
 s=clean(v); return {'op':'OP','staff':'Staff','engineer':'Engineer','supervisor':'Supervisor','manager':'Manager','vp':'VP'}.get(s.lower(),s.title() or 'Unknown')

def parse_dt(s):
 for f in ('%d/%m/%Y %H:%M:%S','%d/%m/%Y %H:%M'):
  try:return datetime.strptime(re.sub(r'\s+',' ',clean(s)),f)
  except:pass
 return None

def getrows(page):
 out=[]; rs=page.locator('table tbody tr'); rs=rs if rs.count() else page.locator('table tr')
 for i in range(rs.count()):
  cs=rs.nth(i).locator('td')
  if cs.count()>=4:out.append([clean(x) for x in cs.all_inner_texts()])
 return out

def workday_for_shift(shift, now=None, requested_work_date=None):
 if requested_work_date:
  try:return datetime.strptime(requested_work_date,'%Y-%m-%d').date()
  except:pass
 now=now or datetime.now()
 if clean(shift).upper()=='N' and now.time()<dtime(18,0): return now.date()-timedelta(days=1)
 return now.date()

def schedule(group,shift):
 g=clean(group).upper(); sh=clean(shift).upper()
 if sh=='N': return (dtime(19,40),dtime(4,40)) if g=='OP' else (dtime(20,0),dtime(5,40))
 return (dtime(7,40),dtime(16,40)) if g=='OP' else (dtime(8,0),dtime(17,40))

def choose(rs,emp,group='',shift='D',requested_work_date=None):
 valid=[]; name=''
 for r in rs:
  if len(r)<4 or clean(r[1]).upper()!=emp.upper():continue
  d=parse_dt(r[3]); name=name or clean(r[2])
  if d and d.year>=2020 and d.date()<=date.today()+timedelta(days=1):valid.append(d)
 if not valid:return None,'QUERY UNAVAILABLE',name,[],[],0,''
 wd=workday_for_shift(shift,requested_work_date=requested_work_date); sh=clean(shift).upper(); g=clean(group).upper(); start_t,end_t=schedule(g,sh)
 if sh=='N':
  window_start=datetime.combine(wd,dtime(16,0)); window_end=datetime.combine(wd+timedelta(days=1),dtime(12,0))
  rec=sorted(d for d in valid if window_start<=d<=window_end)
  ins=[d for d in rec if d.date()==wd and d.time()>=dtime(16,0)]
  outs=[d for d in rec if d.date()==wd+timedelta(days=1) and d.time()<=dtime(12,0)]
  scan_in=min(ins) if ins else None; scan_out=max(outs) if outs else None
  normal_end=datetime.combine(wd+timedelta(days=1),end_t)
 else:
  rec=sorted(d for d in valid if d.date()==wd)
  ins=[d for d in rec if d.time()<dtime(12,0)]
  outs=[d for d in rec if d.time()>=dtime(14,0)]
  scan_in=min(ins) if ins else None; scan_out=max(outs) if outs else None
  normal_end=datetime.combine(wd,end_t)
 if scan_in:
  if sh!='N' and g!='OP' and scan_in.time()<dtime(6,30): normal_end=datetime.combine(wd,dtime(14,40))
  gross=max(0,int((scan_out-normal_end).total_seconds()//60)) if scan_out else 0
  net=max(0,gross-30); ot=net if net>=60 else 0
  return max(rec),'PRESENT',name,[scan_in],[scan_out] if scan_out else [],ot,wd.strftime('%d/%m/%Y')
 return max(valid),'NO SCAN TODAY',name,[],[],0,wd.strftime('%d/%m/%Y')

def query_once(page,emp,group='',shift='D',timeout=12,requested_work_date=None):
 page.goto(TARGET,wait_until='domcontentloaded',timeout=30000)
 inp=page.locator('input').first; inp.wait_for(state='visible',timeout=10000); inp.fill(emp)
 btn=page.get_by_role('button',name=re.compile(r'^\s*GO\s*$',re.I)); btn=btn if btn.count() else page.locator('button,input[type=submit]').first
 try:btn.click(no_wait_after=True,timeout=5000)
 except:pass
 end=time.time()+timeout; rs=[]
 while time.time()<end:
  try:
   rs=getrows(page)
   if any(len(r)>=4 and clean(r[1]).upper()==emp.upper() for r in rs):break
  except:pass
  page.wait_for_timeout(300)
 sel,status,name,ins,outs,ot_minutes,work_date=choose(rs,emp,group,shift,requested_work_date)
 if not sel:
  try:
   body=re.sub(r'\s+',' ',page.locator('body').inner_text())[:300]
   log(f'NO ROWS emp={emp} url={page.url} title={page.title()} rows={len(rs)} body={body}')
  except Exception as e: log(f'NO ROWS emp={emp} debug_error={type(e).__name__}: {e}')
  return {'latest_datetime':'','status':'QUERY UNAVAILABLE','name_from_web':'','scan_in':'','scan_out':'','raw_count':0,'ot_minutes':0,'work_date':''}
 return {'latest_datetime':sel.strftime('%d/%m/%Y %H:%M:%S'),'status':status,'name_from_web':name,'scan_in':ins[0].strftime('%d/%m/%Y %H:%M:%S') if ins else '','scan_out':outs[0].strftime('%d/%m/%Y %H:%M:%S') if outs else '','raw_count':len(ins)+len(outs),'ot_minutes':ot_minutes,'work_date':work_date}

def setjob(j,**kw):
 with lock:
  if j in jobs: jobs[j].update(kw)

def job_signature(department,mode,work_date,missing_only):
 return (norm_dept(department),clean(mode).upper(),clean(work_date),bool(missing_only))

def find_duplicate_job(department,mode,work_date,missing_only):
 sig=job_signature(department,mode,work_date,missing_only)
 with lock:
  for jid,j in jobs.items():
   if j.get('status') not in ('queued','running'): continue
   jsig=job_signature(j.get('department'),j.get('mode'),j.get('work_date'),j.get('missing_only'))
   if jsig==sig:
    return jid,dict(j)
 return '',None

def job_public(jid,j):
 x=dict(j);x['job_id']=jid
 return x

def runquery(j,query_shift='ALL',requested_work_date=None,missing_only=False,department='PE'):
 department=norm_dept(department)
 if query_run_lock.locked():
  setjob(j,status='queued',current='',message=f'{department} • Waiting for current department query to finish...')
 query_run_lock.acquire()
 try:
  with db() as c:
   sql='SELECT e.* FROM employees e LEFT JOIN attendance a ON a.employee_code=e.employee_code WHERE e.active=1 AND e.department=?'; args=[department]
   if query_shift in ('D','N'): sql+=' AND e.shift=?'; args.append(query_shift)
   if missing_only:
    target_wd=''
    if requested_work_date:
     try:target_wd=datetime.strptime(requested_work_date,'%Y-%m-%d').strftime('%d/%m/%Y')
     except:target_wd=''
    sql+=" AND (a.employee_code IS NULL OR a.status IS NULL OR a.status!='PRESENT' OR COALESCE(a.work_date,'')!=?)";args.append(target_wd)
   sql+=' ORDER BY e.shift,e.location_support,e.team_support,e.employee_code'
   emps=[dict(x) for x in c.execute(sql,args)]
  setjob(j,status='running',total=len(emps),done=0,started_at=bkk_now().isoformat(timespec='seconds'),message=f'Checking {department} attendance...');results={};failed=[]
  if not emps:
   setjob(j,status='done',total=0,done=0,current='',finished_at=bkk_now().isoformat(timespec='seconds'),message=f'No active employees in {department} for this shift');return
  with sync_playwright() as p:
   headless=os.getenv('PLAYWRIGHT_HEADLESS','0')!='0'
   log(f'launch chromium headless={headless} display={os.getenv("DISPLAY","")} department={department} target={TARGET}')
   browser=p.chromium.launch(headless=headless,args=['--no-sandbox','--disable-dev-shm-usage','--disable-blink-features=AutomationControlled'])
   ctx=browser.new_context(ignore_https_errors=True,viewport={'width':1280,'height':900},locale='en-US',timezone_id='Asia/Bangkok',user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36')
   ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});");page=ctx.new_page()
   for i,e in enumerate(emps,1):
    emp=e['employee_code'];setjob(j,current=emp,done=i-1,message=f'{department} • Query {emp}')
    try:r=query_once(page,emp,e.get('group_code',''),e.get('shift','D'),requested_work_date=requested_work_date)
    except Exception as ex:
     log(f'QUERY ERROR dept={department} emp={emp} {type(ex).__name__}: {ex}')
     r={'latest_datetime':'','status':'QUERY UNAVAILABLE','name_from_web':'','scan_in':'','scan_out':'','raw_count':0,'ot_minutes':0,'work_date':''}
    results[emp]=r
    if r['status']=='QUERY UNAVAILABLE':failed.append(emp)
    setjob(j,done=i);time.sleep(.6)
   if failed:
    for k,emp in enumerate(failed,1):
     setjob(j,current=emp,message=f'{department} • Retry {k}/{len(failed)}: {emp}')
     try:
      page.wait_for_timeout(1500);ee=next((x for x in emps if x['employee_code']==emp),{});results[emp]=query_once(page,emp,ee.get('group_code',''),ee.get('shift','D'),15,requested_work_date)
     except Exception as ex:log(f'RETRY ERROR dept={department} emp={emp} {type(ex).__name__}: {ex}')
   ctx.close();browser.close()
  now=datetime.now().strftime('%d/%m/%Y %H:%M:%S')
  with db() as c:
   for emp,r in results.items():
    c.execute('INSERT INTO attendance(employee_code,name_from_web,latest_datetime,status,query_at,scan_in,scan_out,raw_count,ot_minutes,work_date) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(employee_code) DO UPDATE SET name_from_web=excluded.name_from_web,latest_datetime=excluded.latest_datetime,status=excluded.status,query_at=excluded.query_at,scan_in=excluded.scan_in,scan_out=excluded.scan_out,raw_count=excluded.raw_count,ot_minutes=excluded.ot_minutes,work_date=excluded.work_date',(emp,r['name_from_web'],r['latest_datetime'],r['status'],now,r.get('scan_in',''),r.get('scan_out',''),r.get('raw_count',0),r.get('ot_minutes',0),r.get('work_date','')))
  newly_present=sum(1 for r in results.values() if r.get('status')=='PRESENT')
  msg=f'{department} • Rechecked {len(emps)} employee(s) • {newly_present} present' if missing_only else f'{department} attendance updated'
  setjob(j,status='done',current='',done=len(emps),total=len(emps),finished_at=bkk_now().isoformat(timespec='seconds'),message=msg)
 except Exception as e:
  log(f'JOB ERROR dept={department} {type(e).__name__}: {e}');setjob(j,status='error',current='',finished_at=bkk_now().isoformat(timespec='seconds'),message=f'{type(e).__name__}: {e}')
 finally:
  try:query_run_lock.release()
  except RuntimeError:pass

@app.get('/manifest.webmanifest')
def manifest(): return send_from_directory(BASE/'static','manifest.webmanifest',mimetype='application/manifest+json')
@app.get('/sw.js')
def sw(): return send_from_directory(BASE/'static','sw.js',mimetype='application/javascript')
@app.get('/api/health')
def health(): return jsonify(ok=True,version=VERSION,target=TARGET,headless=os.getenv('PLAYWRIGHT_HEADLESS','0')!='0',tz=os.getenv('TZ',''),started_at=STARTED_AT,query_busy=query_run_lock.locked(),schedule_store=schedule_store_kind(),persistent_schedule=(schedule_store_kind()=='postgres'),auto_query_token_configured=bool(AUTO_QUERY_TOKEN))
@app.get('/')
def home(): return render_template('index.html')

@app.get('/api/departments')
def departments_list():
 with db() as c:
  rows=[dict(x) for x in c.execute("SELECT d.code,d.name,d.active,COUNT(CASE WHEN e.active=1 THEN 1 END) employee_count FROM departments d LEFT JOIN employees e ON e.department=d.code WHERE d.active=1 GROUP BY d.code,d.name,d.active ORDER BY d.code")]
 return jsonify(ok=True,departments=rows)

@app.post('/api/departments')
def department_save():
 x=request.get_json(silent=True) or {};code=ensure_department(x.get('code'),x.get('name'))
 if not code:return jsonify(ok=False,error='Department code required'),400
 return jsonify(ok=True,code=code)

@app.get('/api/dashboard')
def dash():
 dept=norm_dept(request.args.get('department','')) or 'PE';loc=request.args.get('location','ALL');team=request.args.get('team','ALL');sh=request.args.get('shift','ALL');grp=request.args.get('group','ALL')
 wh=['e.active=1'];args=[]
 if dept!='ALL':wh.append('e.department=?');args.append(dept)
 if loc!='ALL':wh.append('e.location_support=?');args.append(loc)
 if team!='ALL':wh.append('e.team_support=?');args.append(team)
 if sh!='ALL':wh.append('e.shift=?');args.append(sh)
 if grp!='ALL':wh.append('e.group_code=?');args.append(grp)
 with db() as c:
  data=[dict(x) for x in c.execute(f"SELECT e.*,a.latest_datetime,a.scan_in,a.scan_out,a.status,a.query_at,a.ot_minutes,a.work_date FROM employees e LEFT JOIN attendance a ON a.employee_code=e.employee_code WHERE {' AND '.join(wh)} ORDER BY e.department,e.shift,e.location_support,e.team_support,e.employee_code",args)]
  base="active=1";base_args=[]
  if dept!='ALL':base+=' AND department=?';base_args.append(dept)
  locs=[x[0] for x in c.execute(f"SELECT DISTINCT location_support FROM employees WHERE {base} AND COALESCE(location_support,'')<>'' ORDER BY location_support",base_args)]
  teams=[x[0] for x in c.execute(f"SELECT DISTINCT team_support FROM employees WHERE {base} AND COALESCE(team_support,'')<>'' ORDER BY team_support",base_args)]
  deps=[dict(x) for x in c.execute("SELECT d.code,d.name,d.active,COUNT(CASE WHEN e.active=1 THEN 1 END) employee_count FROM departments d LEFT JOIN employees e ON e.department=d.code WHERE d.active=1 GROUP BY d.code,d.name,d.active ORDER BY d.code")]
 def stat(rows):
  out={'TOTAL':len(rows),'PRESENT':0,'NO SCAN TODAY':0,'QUERY UNAVAILABLE':0,'NOT CHECKED':0}
  for x in rows:
   st=x.get('status') or 'NOT CHECKED';st=st if st in out else 'NOT CHECKED';out[st]+=1
  return out
 def breakdown(rows,key):
  out={}
  for x in rows:
   k=clean(x.get(key)) or '(Not set)';v=out.setdefault(k,{'total':0,'present':0,'no_scan':0,'error':0,'not_checked':0});v['total']+=1
   st=x.get('status') or 'NOT CHECKED'
   if st=='PRESENT':v['present']+=1
   elif st=='NO SCAN TODAY':v['no_scan']+=1
   elif st=='QUERY UNAVAILABLE':v['error']+=1
   else:v['not_checked']+=1
  return out
 day=[x for x in data if clean(x.get('shift')).upper()=='D'];night=[x for x in data if clean(x.get('shift')).upper()=='N']
 bydept=breakdown(data,'department')
 return jsonify(ok=True,department=dept,departments=deps,employees=data,counts=stat(data),locations=locs,teams=teams,shift_counts={'D':stat(day),'N':stat(night)},by_department=bydept,by_location={'ALL':breakdown(data,'location_support'),'D':breakdown(day,'location_support'),'N':breakdown(night,'location_support')},by_team={'ALL':breakdown(data,'team_support'),'D':breakdown(day,'team_support'),'N':breakdown(night,'team_support')},last_query=max([x.get('query_at') or '' for x in data],default=''),current_night_work_date=workday_for_shift('N').strftime('%d/%m/%Y'),current_day_work_date=date.today().strftime('%d/%m/%Y'))

@app.post('/api/upload-master')
def upload():
 f=request.files.get('file');dept=norm_dept(request.form.get('department',''))
 if not dept or dept=='ALL':return jsonify(ok=False,error='Select one department before uploading Employee Master'),400
 if not f or not f.filename.lower().endswith('.xlsx'):return jsonify(ok=False,error='กรุณาเลือกไฟล์ .xlsx'),400
 ensure_department(dept)
 path=DATA/f'master_{uuid.uuid4().hex[:8]}.xlsx';f.save(path)
 try:
  wb=load_workbook(path,read_only=True,data_only=True);ws=wb[wb.sheetnames[0]]
  def hnorm(v):
   z=clean(v).lower().replace('\n',' ').replace('\r',' ');return re.sub(r'[^a-z0-9ก-๙]+','_',z).strip('_')
  hs=[hnorm(c.value) for c in ws[1]]
  aliases={'employee_code':['employee_code','employee_no','emp_no','empno','รหัสพนักงาน'],'full_name':['full_name','name','employee_name','ชื่อ','ชื่อพนักงาน'],'location_support':['location_support','location','support_location'],'team_support':['team_support','team','support_team'],'group_code':['group','group_code','group_support'],'shift':['shift','shift_code']}
  idx={}
  for k,names in aliases.items():
   for a in names:
    if hnorm(a) in hs:idx[k]=hs.index(hnorm(a));break
  req=['employee_code','full_name','location_support','team_support','group_code','shift'];missing=[k for k in req if k not in idx]
  if missing:raise ValueError('Excel ต้องมีคอลัมน์: employee_code, full_name, location_support, team_support, group, shift')
  incoming={}
  for r in ws.iter_rows(min_row=2,values_only=True):
   emp=re.sub(r'<[^>]+>','',clean(r[idx['employee_code']])).strip().upper()
   if emp:incoming[emp]=(clean(r[idx['full_name']]),clean(r[idx['location_support']]),clean(r[idx['team_support']]),clean(r[idx['group_code']]).upper(),clean(r[idx['shift']]).upper())
  wb.close();now=datetime.now().isoformat(timespec='seconds')
  with db() as c:
   current={x[0] for x in c.execute('SELECT employee_code FROM employees WHERE active=1 AND department=?',(dept,))}
   sql="INSERT INTO employees(employee_code,full_name,department,position,active,updated_at,location_support,team_support,group_code,shift) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(employee_code) DO UPDATE SET full_name=excluded.full_name,department=excluded.department,active=1,updated_at=excluded.updated_at,location_support=excluded.location_support,team_support=excluded.team_support,group_code=excluded.group_code,shift=excluded.shift"
   for emp,(name,loc,team,grp,sh) in incoming.items():c.execute(sql,(emp,name,dept,'',1,now,loc,team,grp,sh))
   for x in current-set(incoming):c.execute('UPDATE employees SET active=0,updated_at=? WHERE employee_code=? AND department=?',(now,x,dept))
  return jsonify(ok=True,department=dept,total=len(incoming),added=len(set(incoming)-current),removed=len(current-set(incoming)))
 except Exception as e:return jsonify(ok=False,error=str(e)),400
 finally:
  try:path.unlink(missing_ok=True)
  except:pass

# Department-scoped browser backup/restore. This prevents one department from overwriting another.
@app.get('/api/state/export')
def state_export():
 dept=norm_dept(request.args.get('department',''))
 if not dept or dept=='ALL':return jsonify(ok=False,error='Specific department required'),400
 with db() as c:
  employees=[dict(x) for x in c.execute('SELECT employee_code,full_name,department,location_support,team_support,group_code,shift,active,updated_at FROM employees WHERE department=? ORDER BY active DESC,shift,location_support,employee_code',(dept,))]
  codes=[x['employee_code'] for x in employees]
  attendance=[]
  if codes:
   q=','.join('?'*len(codes));attendance=[dict(x) for x in c.execute(f'SELECT employee_code,name_from_web,latest_datetime,status,query_at,scan_in,scan_out,raw_count,ot_minutes,work_date FROM attendance WHERE employee_code IN ({q}) ORDER BY employee_code',codes)]
 return jsonify(ok=True,version=2,department=dept,exported_at=datetime.now().isoformat(timespec='seconds'),employees=employees,attendance=attendance)

@app.post('/api/state/restore')
def state_restore():
 x=request.get_json(silent=True) or {};dept=norm_dept(x.get('department'));rows=x.get('employees');att=x.get('attendance') or []
 if not dept or dept=='ALL':return jsonify(ok=False,error='Specific department required'),400
 if not isinstance(rows,list) or not rows:return jsonify(ok=False,error='employees must be a non-empty array'),400
 ensure_department(dept);now=datetime.now().isoformat(timespec='seconds');incoming={}
 for r in rows:
  if not isinstance(r,dict):continue
  emp=re.sub(r'<[^>]+>','',clean(r.get('employee_code'))).strip().upper()
  if emp:incoming[emp]=(clean(r.get('full_name')),clean(r.get('location_support')),clean(r.get('team_support')),clean(r.get('group_code')).upper(),clean(r.get('shift')).upper(),1 if r.get('active',True) else 0)
 if not incoming:return jsonify(ok=False,error='No valid employee records'),400
 with db() as c:
  old=[z[0] for z in c.execute('SELECT employee_code FROM employees WHERE department=?',(dept,))]
  for emp in old:c.execute('DELETE FROM attendance WHERE employee_code=?',(emp,))
  c.execute('DELETE FROM employees WHERE department=?',(dept,))
  for emp,(name,loc,team,grp,sh,active) in incoming.items():c.execute('INSERT INTO employees(employee_code,full_name,department,position,active,updated_at,location_support,team_support,group_code,shift) VALUES(?,?,?,?,?,?,?,?,?,?)',(emp,name,dept,'',active,now,loc,team,grp,sh))
  for r in att:
   if not isinstance(r,dict):continue
   emp=clean(r.get('employee_code')).upper()
   if emp not in incoming:continue
   c.execute('INSERT INTO attendance(employee_code,name_from_web,latest_datetime,status,query_at,scan_in,scan_out,raw_count,ot_minutes,work_date) VALUES(?,?,?,?,?,?,?,?,?,?)',(emp,clean(r.get('name_from_web')),clean(r.get('latest_datetime')),clean(r.get('status')),clean(r.get('query_at')),clean(r.get('scan_in')),clean(r.get('scan_out')),int(r.get('raw_count') or 0),int(r.get('ot_minutes') or 0),clean(r.get('work_date'))))
 return jsonify(ok=True,department=dept,total=len(incoming),attendance=len(att))

@app.get('/api/master/export')
def master_export():
 dept=norm_dept(request.args.get('department',''))
 if not dept or dept=='ALL':return jsonify(ok=False,error='Specific department required'),400
 with db() as c:rows=[dict(x) for x in c.execute('SELECT employee_code,full_name,department,location_support,team_support,group_code,shift,active,updated_at FROM employees WHERE department=? ORDER BY active DESC,shift,location_support,employee_code',(dept,))]
 return jsonify(ok=True,version=2,department=dept,exported_at=datetime.now().isoformat(timespec='seconds'),employees=rows)

@app.post('/api/master/replace')
def master_replace():
 x=request.get_json(silent=True) or {};dept=norm_dept(x.get('department'));rows=x.get('employees')
 if not dept or dept=='ALL':return jsonify(ok=False,error='Specific department required'),400
 if not isinstance(rows,list):return jsonify(ok=False,error='employees must be an array'),400
 ensure_department(dept);incoming={}
 for r in rows:
  if not isinstance(r,dict):continue
  emp=re.sub(r'<[^>]+>','',clean(r.get('employee_code'))).strip().upper()
  if emp:incoming[emp]={'employee_code':emp,'full_name':clean(r.get('full_name')),'location_support':clean(r.get('location_support')),'team_support':clean(r.get('team_support')),'group_code':clean(r.get('group_code')).upper(),'shift':clean(r.get('shift')).upper(),'active':1 if r.get('active',True) else 0}
 if not incoming:return jsonify(ok=False,error='No valid employee records'),400
 now=datetime.now().isoformat(timespec='seconds')
 with db() as c:
  c.execute('UPDATE employees SET active=0,updated_at=? WHERE department=?',(now,dept))
  sql="INSERT INTO employees(employee_code,full_name,department,position,active,updated_at,location_support,team_support,group_code,shift) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(employee_code) DO UPDATE SET full_name=excluded.full_name,department=excluded.department,active=excluded.active,updated_at=excluded.updated_at,location_support=excluded.location_support,team_support=excluded.team_support,group_code=excluded.group_code,shift=excluded.shift"
  for r in incoming.values():c.execute(sql,(r['employee_code'],r['full_name'],dept,'',r['active'],now,r['location_support'],r['team_support'],r['group_code'],r['shift']))
 return jsonify(ok=True,department=dept,total=len(incoming),active=sum(r['active'] for r in incoming.values()))

@app.get('/api/employees')
def employee_list():
 dept=norm_dept(request.args.get('department','')) or 'PE'
 with db() as c:
  if dept=='ALL':rows=[dict(x) for x in c.execute('SELECT * FROM employees ORDER BY active DESC,department,location_support,employee_code')]
  else:rows=[dict(x) for x in c.execute('SELECT * FROM employees WHERE department=? ORDER BY active DESC,location_support,employee_code',(dept,))]
 return jsonify(ok=True,department=dept,employees=rows)

@app.post('/api/employees')
def employee_save():
 x=request.get_json(force=True);emp=clean(x.get('employee_code')).upper();dept=norm_dept(x.get('department'))
 if not emp:return jsonify(ok=False,error='Employee No. required'),400
 if not dept or dept=='ALL':return jsonify(ok=False,error='Specific department required'),400
 ensure_department(dept);now=datetime.now().isoformat(timespec='seconds')
 with db() as c:c.execute('INSERT INTO employees(employee_code,full_name,department,position,active,updated_at,location_support,team_support,group_code,shift) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(employee_code) DO UPDATE SET full_name=excluded.full_name,department=excluded.department,active=excluded.active,updated_at=excluded.updated_at,location_support=excluded.location_support,team_support=excluded.team_support,group_code=excluded.group_code,shift=excluded.shift',(emp,clean(x.get('full_name')),dept,'',1 if x.get('active',True) else 0,now,clean(x.get('location_support')),clean(x.get('team_support')),clean(x.get('group_code')).upper(),clean(x.get('shift')).upper()))
 return jsonify(ok=True,department=dept)

@app.get('/api/auto-schedule')
def auto_schedule_get():
 dept=norm_dept(request.args.get('department',''))
 if not dept or dept=='ALL':return jsonify(ok=False,error='Specific department required'),400
 try:
  sched=get_auto_schedule(dept);last=last_auto_run(dept);nxt=next_auto_run(sched)
  return jsonify(ok=True,department=dept,schedule=sched,last_run=last,next_run=nxt,store=schedule_store_kind(),persistent=(schedule_store_kind()=='postgres'),token_configured=bool(AUTO_QUERY_TOKEN))
 except Exception as e:
  log(f'AUTO SCHEDULE GET ERROR dept={dept} {type(e).__name__}: {e}');return jsonify(ok=False,error=str(e)),500

@app.post('/api/auto-schedule')
def auto_schedule_save_api():
 x=request.get_json(silent=True) or {};dept=norm_dept(x.get('department'))
 if not dept or dept=='ALL':return jsonify(ok=False,error='Specific department required'),400
 try:
  ensure_department(dept);sched=save_auto_schedule(dept,x);return jsonify(ok=True,department=dept,schedule=sched,next_run=next_auto_run(sched),store=schedule_store_kind(),persistent=(schedule_store_kind()=='postgres'))
 except Exception as e:return jsonify(ok=False,error=str(e)),400

@app.post('/api/auto-query/tick')
def auto_query_tick():
 if not auto_token_ok(request):return jsonify(ok=False,error='Auto Query token missing or invalid'),401
 now=bkk_now();tasks=[]
 try:
  with db() as c:deps=[norm_dept(x[0]) for x in c.execute("SELECT code FROM departments WHERE active=1 ORDER BY code")]
  for dept in deps:
   sched=get_auto_schedule(dept)
   if not sched or not sched.get('enabled') or now.weekday() not in set(sched.get('weekdays') or []):continue
   for slot_key,time_key,mode,label in AUTO_SLOTS:
    hhmm=sched.get(time_key)
    if not _valid_hhmm(hhmm):continue
    due=datetime.combine(now.date(),datetime.strptime(hhmm,'%H:%M').time(),tzinfo=BKK)
    age=(now-due).total_seconds()/60
    if 0<=age<=AUTO_GRACE_MINUTES and claim_auto_run(dept,slot_key,now.date().isoformat(),mode):
     tasks.append({'department':dept,'slot_key':slot_key,'slot_date':now.date().isoformat(),'mode':mode,'label':label,'scheduled_at':due.isoformat(timespec='minutes'),'late_minutes':int(age)})
  return jsonify(ok=True,now=now.isoformat(timespec='minutes'),tasks=tasks,grace_minutes=AUTO_GRACE_MINUTES)
 except Exception as e:
  log(f'AUTO TICK ERROR {type(e).__name__}: {e}');return jsonify(ok=False,error=str(e)),500

@app.post('/api/auto-query/complete')
def auto_query_complete():
 if not auto_token_ok(request):return jsonify(ok=False,error='Auto Query token missing or invalid'),401
 x=request.get_json(silent=True) or {};dept=norm_dept(x.get('department'));slot=clean(x.get('slot_key'));slot_date=clean(x.get('slot_date'))
 if not dept or not slot or not slot_date:return jsonify(ok=False,error='department, slot_key and slot_date required'),400
 complete_auto_run(dept,slot,slot_date,x.get('status'),x.get('job_id'),x.get('message'));return jsonify(ok=True)

@app.post('/api/query')
def start():
 x=request.get_json(silent=True) or {};mode=clean(x.get('mode')).upper() or 'DAY';dept=norm_dept(x.get('department'));today=date.today()
 if not dept or dept=='ALL':return jsonify(ok=False,error='Select one department before Query'),400
 if mode=='DAY':query_shift='D';wd=today
 elif mode=='LAST_NIGHT':query_shift='N';wd=today-timedelta(days=1)
 elif mode=='TONIGHT':query_shift='N';wd=today
 else:return jsonify(ok=False,error='Historical/custom-date query is disabled. Use TODAY DAY, LAST NIGHT, or TONIGHT.'),400
 missing_only=bool(x.get('missing_only',False));source=clean(x.get('source')).upper()
 if source not in ('AUTO','MANUAL'):source='MANUAL'
 dup_id,dup=find_duplicate_job(dept,mode,wd.isoformat(),missing_only)
 if dup_id:
  return jsonify(ok=True,job_id=dup_id,department=dept,duplicate=True,status=dup.get('status'),source=dup.get('source','MANUAL'))
 j=uuid.uuid4().hex[:10]
 with lock:
  jobs[j]={'status':'queued','total':0,'done':0,'current':'','message':f'Preparing {dept} missing employees...' if missing_only else f'Preparing {dept}...','department':dept,'query_shift':query_shift,'mode':mode,'work_date':wd.isoformat(),'missing_only':missing_only,'source':source,'created_at':bkk_now().isoformat(timespec='seconds')}
 threading.Thread(target=runquery,args=(j,query_shift,wd.isoformat(),missing_only,dept),daemon=True).start()
 return jsonify(ok=True,job_id=j,department=dept,duplicate=False,status='queued',source=source)

@app.get('/api/query-status')
def query_status():
 dept=norm_dept(request.args.get('department',''))
 with lock:
  rows=[job_public(jid,j) for jid,j in jobs.items()]
 if dept and dept!='ALL':rows=[x for x in rows if x.get('department')==dept]
 def sortkey(x):return x.get('created_at') or x.get('started_at') or ''
 active=[x for x in rows if x.get('status') in ('queued','running')]
 active.sort(key=sortkey)
 recent=[x for x in rows if x.get('status') in ('done','error')]
 recent.sort(key=lambda x:x.get('finished_at') or sortkey(x),reverse=True)
 for i,x in enumerate(active,1):x['queue_position']=i
 running=next((x for x in active if x.get('status')=='running'),None)
 return jsonify(ok=True,server_time=bkk_now().isoformat(timespec='seconds'),query_busy=query_run_lock.locked(),running=running,active=active,queued=[x for x in active if x.get('status')=='queued'],recent=recent[:8])

@app.get('/api/job/<j>')
def job(j):
 with lock:x=jobs.get(j)
 return jsonify(ok=bool(x),**(x or {'error':'Job not found'}))

if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.getenv('PORT','5000')),debug=False,threaded=True)
