import os,sys,json,threading,tempfile,time
from pathlib import Path
from datetime import datetime
from http.server import HTTPServer,BaseHTTPRequestHandler
from urllib.parse import urlparse,parse_qs
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_persistence import fake_flask
sys.modules['flask']=fake_flask
os.environ['DATABASE_URL']='';os.environ['REQUIRE_POSTGRES']='false';os.environ['DATA_DIR']=tempfile.mkdtemp()
import app
from test_master_sync import seed
app.bkk_now=lambda:datetime.fromisoformat('2026-09-28T08:30:00+07:00')
for i in range(1,8):seed(app,f'TEST{i:03}',department='PE',shift='D',full_name=f'Test employee {i}',location_support='Factory 10')
app.bkk_now=lambda:datetime.fromisoformat('2026-09-29T08:30:00+07:00');app.history.capture_today()
for i in range(8,12):seed(app,f'TEST{i:03}',department='PE',shift='N',full_name=f'Test night {i}',location_support='Factory 10')
app.ensure_department('TE');app.history.capture_today()
for e in app.history.roster('PE','2026-09-29','D'):
 with app.db() as c:app.history.save_result(c,e,'2026-09-29','D',dict(status='PRESENT',name_from_web='',latest_datetime='29/09/2026 08:03:00',scan_in='29/09/2026 08:03:00',scan_out='',raw_count=1,ot_minutes=0,work_date='29/09/2026'))
def api_call(url,opts):
 u=urlparse(url);body=json.loads(opts.get('body') or '{}');fake_flask.request.headers=opts.get('headers') or {};fake_flask.request.host_url='https://attendance.test/'
 try:
  data,status=app.app.invoke(opts.get('method','GET'),u.path,body,{k:v[0] for k,v in parse_qs(u.query).items()})
  return {'status':status,'data':json.loads(json.dumps(data,default=str))}
 except Exception as e:print(u.path,repr(e));return {'status':500,'data':{'error':repr(e)}}
import re,base64
html=(ROOT/'templates/index.html').read_text()
html=re.sub(r'<script src="(/static/[^"?]+)(?:\?[^" ]*)?"></script>',lambda m:'<script>'+ (ROOT/m[1].lstrip('/')).read_text()+'</script>',html)
html=re.sub(r'<link rel="stylesheet" href="(/static/[^"?]+)(?:\?[^" ]*)?">',lambda m:'<style>'+ (ROOT/m[1].lstrip('/')).read_text()+'</style>',html)
bootstrap="""<script>
const fakeStorage={};Object.defineProperty(window,'localStorage',{value:{getItem:k=>fakeStorage[k]??null,setItem:(k,v)=>fakeStorage[k]=String(v),removeItem:k=>delete fakeStorage[k],get length(){return Object.keys(fakeStorage).length},key:i=>Object.keys(fakeStorage)[i]}});
window.fetch=async(url,options={})=>{const r=await window.testApi(String(url),options);return new Response(JSON.stringify(r.data),{status:r.status,headers:{'Content-Type':'application/json'}})};
</script>"""
html=html.replace('<head>','<head>'+bootstrap)
from playwright.sync_api import sync_playwright
out=Path(tempfile.mkdtemp(prefix='attendance-ui-qa-'));out.mkdir(exist_ok=True)
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path=os.getenv('CHROME_EXECUTABLE') or ('/usr/bin/chromium' if Path('/usr/bin/chromium').exists() else p.chromium.executable_path),headless=True,args=['--no-sandbox'])
 context=browser.new_context(viewport={'width':390,'height':844},device_scale_factor=1,timezone_id='America/Los_Angeles')
 page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 page.expose_function('testApi',api_call);page.set_content(html);page.wait_for_timeout(1500)
 print('errors',errors)
 print('title',page.locator('#viewTitle').inner_text());print('clock',page.locator('#clock').inner_text())
 assert '29/09/2026' in page.locator('#clock').inner_text()
 assert '08:30' in page.locator('#clock').inner_text()
 assert page.locator('#total').inner_text()=='7'
 page.screenshot(path=str(out/'mobile-dashboard.png'),full_page=True)
 page.locator('#qlastday').click();page.wait_for_timeout(400)
 assert 'Last Day' in page.locator('#viewTitle').inner_text() and '28/09/2026' in page.locator('#viewTitle').inner_text()
 assert page.locator('#present').inner_text()=='0'
 page.locator('#qtonight').click();page.wait_for_timeout(400)
 assert page.locator('#total').inner_text()=='4'
 page.locator('#scheduleBtn').click();page.wait_for_timeout(500)
 assert page.locator('#thaiRules .thai-rule').count()==5
 first=page.locator('#thaiRules .thai-rule').first
 first.locator('.rule-at').fill('16:40');first.locator('.rule-at').dispatch_event('change');assert 'ยังไม่ได้บันทึก' in page.locator('#scheduleSaveState').inner_text()
 page.locator('#saveSchedule').click();page.wait_for_timeout(700)
 assert 'ค่าที่โหลด' in page.locator('#scheduleSaveState').inner_text()
 page.screenshot(path=str(out/'mobile-schedule.png'),full_page=False)
 page.locator('#smodal .close').click()
 page.locator('#qday').click();page.wait_for_timeout(300)
 # Inject an AUTO example into status store only; no actual MIS queries.
 app.jobs['demo']=dict(status='running',department='PE',mode='DAY',query_shift='D',work_date='2026-09-29',date_label='29/09/2026',source='AUTO',trigger='schedule',total=7,done=3,current='TEST004',message='Checking test data',created_at='2026-09-29T08:30:00+07:00',scheduled_at='2026-09-29T08:15:00+07:00',started_at='2026-09-29T08:30:00+07:00',finished_at='')
 page.wait_for_timeout(2800)
 assert 'Scheduled' in page.locator('#livequerytitle').inner_text()
 assert '15' in page.locator('#livequerymeta').inner_text()
 assert page.locator('#qrun').is_disabled()
 page.locator('#livequerybar').scroll_into_view_if_needed();page.screenshot(path=str(out/'mobile-running.png'),full_page=False)
 # Viewing another tab doesn't launch another query.
 page.locator('#qlastday').click();page.wait_for_timeout(300);assert len(app.jobs)==1
 assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
 context.close()
 desktop=browser.new_page(viewport={'width':1366,'height':900});desktop.expose_function('testApi',api_call);desktop.set_content(html);desktop.wait_for_timeout(1000)
 desktop.screenshot(path=str(out/'desktop.png'),full_page=False)
 print('UI checks passed; errors=',errors);assert not errors
 browser.close()

