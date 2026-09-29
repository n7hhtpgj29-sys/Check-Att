/* V12.1.3: four cached views; all dates/times explicitly Asia/Bangkok. */
const fourState={mode:'DAY',view:null,views:[],known:false,active:[],requestSeq:0,clockOffset:0,schedule:null,dirty:false,statusBusy:false,statusTimer:null,completed:new Set()};
function thaiTime(value,clockOnly=false){
 if(!value)return '—';
 let raw=String(value),old=raw.match(/^(\d{2})\/(\d{2})\/(\d{4}) (\d{2}:\d{2}:\d{2})$/);
 if(old)raw=`${old[3]}-${old[2]}-${old[1]}T${old[4]}+07:00`;
 if(/^\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d)?$/.test(raw))raw+='+07:00';
 const d=new Date(raw);if(!Number.isFinite(d.getTime()))return raw;
 return new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Bangkok',...(clockOnly?{}:{year:'numeric',month:'2-digit',day:'2-digit'}),hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(d);
}
function updateThaiClock(){const e=document.getElementById('clock');if(e)e.textContent=thaiTime(new Date(Date.now()+fourState.clockOffset).toISOString())+' • TH (UTC+7)';}
function fourLabel(m){return {DAY:'Today',LAST_DAY:'Last Day',LAST_NIGHT:'Last Night',TONIGHT:'Tonight'}[m]||m;}
function selectFourView(mode){fourState.mode=mode;$('shift').value=['DAY','LAST_DAY'].includes(mode)?'D':'N';$('loc').value='ALL';$('team').value='ALL';load().catch(e=>toast(e.message));}
function syncFourButtons(active=[]){
 fourState.active=active;
 for(const [id,m] of [['qlastday','LAST_DAY'],['qday','DAY'],['qlast','LAST_NIGHT'],['qtonight','TONIGHT']]){
  const b=$(id),v=fourState.views.find(x=>x.mode===m);if(!b)continue;
  b.disabled=false;b.classList.toggle('view-selected',m===fourState.mode);b.setAttribute('aria-pressed',m===fourState.mode?'true':'false');
  b.innerHTML=`<b>${m.includes('NIGHT')?'🌙':'☀'} ${fourLabel(m)}</b><small>${esc(v?.date_label||'Loading date…')}</small>`;
 }
 const busy=active.find(x=>x.department===dept()&&x.work_date===fourState.view?.work_date&&x.query_shift===fourState.view?.shift);
 $('qrun').disabled=!!busy||dept()==='ALL'||!fourState.known;
 $('qrun').textContent=busy?`🔄 ${busy.status.toUpperCase()} ${busy.done||0}/${busy.total||0}`:`🔄 Query ${fourLabel(fourState.mode)}`;
 $('qmissing').disabled=!!busy||dept()==='ALL'||!fourState.known;
}
async function loadFourDashboard(){
 const seq=++fourState.requestSeq,dep=dept(),mode=fourState.mode;
 const args=new URLSearchParams({department:dep,view:mode,location:$('loc').value,team:$('team').value,group:$('group').value});
 const resp=await fetch('/api/dashboard?'+args,{cache:'no-store'}),d=await resp.json();
 if(!resp.ok||!d.ok)throw new Error(d.error||'Unable to load attendance');
 if(seq!==fourState.requestSeq)return;
 fourState.view=d.view;fourState.views=d.views;fourState.known=d.roster_known;fourState.clockOffset=new Date(d.server_time).getTime()-Date.now();updateThaiClock();
 currentEmployees=d.employees||[];currentDepartments=d.departments||[];
 $('total').textContent=d.counts.TOTAL;$('present').textContent=d.counts.PRESENT;$('noscan').textContent=d.counts['NO SCAN TODAY'];$('error').textContent=d.counts['QUERY UNAVAILABLE'];
 $('last').textContent=d.last_query?'อัปเดตล่าสุด (ไทย): '+thaiTime(d.last_query):'ยังไม่ได้ Query วัน/กะนี้';
 $('deptlabel').textContent=dep;$('masterDept').textContent=dep;$('emasterDept').textContent=dep;
 $('viewTitle').textContent=`${dep} • ${d.view.label} • ${d.view.date_label}`;
 const blank=(d.counts['NOT CHECKED']||0)+(d.counts['NO DATA FOR SHIFT']||0)+(d.counts['NOT STARTED']||0);
 $('viewNote').textContent=!d.roster_known?'ไม่มีรายชื่อกะที่บันทึกไว้สำหรับ '+d.missing_rosters.join(', ')+' ในวันนี้ — ไม่ใช้ Excel ล่าสุดเดาย้อนหลัง และไม่ถือว่าขาดงาน':
  `ดูข้อมูลที่บันทึกไว้ • ยังไม่ตรวจ/ยังไม่เริ่มกะ/ไม่มีข้อมูล ${blank} คน • กด Query เพื่ออัปเดต ไม่ใช่กดแท็บแล้ว Query อัตโนมัติ`;
 $('viewNote').classList.toggle('unknown-roster',!d.roster_known);
 const ds=d.shift_counts.D||{},ns=d.shift_counts.N||{};
 $('daySummary').innerHTML=`<b>${ds.PRESENT||0}/${ds.TOTAL||0} Present</b> • No Scan ${ds['NO SCAN TODAY']||0}`;
 $('nightSummary').innerHTML=`<b>${ns.PRESENT||0}/${ns.TOTAL||0} Present</b> • No Scan ${ns['NO SCAN TODAY']||0}`;
 $('dayDate').textContent=d.view.date_label;$('nightDate').textContent=d.view.date_label;
 $('daySummary').closest('.card').style.display=d.view.shift==='D'?'':'none';$('nightSummary').closest('.card').style.display=d.view.shift==='N'?'':'none';
 $('daySummary').closest('.grid').style.gridTemplateColumns='1fr';
 compareRows(d.by_location.D,d.by_location.N,'locCompare','location_support');compareRows(d.by_team.D,d.by_team.N,'teamCompare','team_support');renderTables();
 $('dayTable').closest('.card').style.display=d.view.shift==='D'?'':'none';$('nightTable').closest('.card').style.display=d.view.shift==='N'?'':'none';
 let lv=$('loc').value,tv=$('team').value;
 $('loc').innerHTML='<option value="ALL">ALL LOCATION</option>'+d.locations.map(x=>`<option>${esc(x)}</option>`).join('');
 $('team').innerHTML='<option value="ALL">ALL TEAM</option>'+d.teams.map(x=>`<option>${esc(x)}</option>`).join('');
 $('loc').value=d.locations.includes(lv)?lv:'ALL';$('team').value=d.teams.includes(tv)?tv:'ALL';
 $('dept').innerHTML='<option value="ALL">🌐 ALL DEPARTMENTS</option>'+d.departments.map(x=>`<option value="${esc(x.code)}">🏢 ${esc(x.code)} (${x.employee_count})</option>`).join('');
 $('dept').value=d.departments.some(x=>x.code===dep)||dep==='ALL'?dep:(d.departments[0]?.code||'PE');
 $('deptoverview').classList.toggle('show',dept()==='ALL');
 $('deptchips').innerHTML=d.departments.map(x=>`<button class="deptchip" data-four-dept="${esc(x.code)}"><b>${esc(x.code)}</b>${x.employee_count} employees (current master)</button>`).join('');
 $('deptchips').querySelectorAll('[data-four-dept]').forEach(b=>b.onclick=()=>selectDept(b.dataset.fourDept));
 updateBackupInfo();syncFourButtons(fourState.active);
}
async function startFourQuery(payload={},silent=false){
 if(dept()==='ALL'){if(!silent)toast('เลือกหนึ่งแผนกก่อน Query');return;}
 const mode=payload.mode||fourState.mode,v=fourState.views.find(x=>x.mode===mode);
 try{
  const r=await fetch('/api/query',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({department:dept(),mode,source:'MANUAL',work_date:v?.work_date,missing_only:!!payload.missing_only})}),d=await r.json();
  if(!r.ok||!d.ok)throw new Error(d.error||'Unable to start query');
  lastQueryPayload={mode,department:dept()};localStorage.setItem(lastQueryKey(),JSON.stringify(lastQueryPayload));
  toast(d.duplicate?'กำลังติดตามงานเดิม ไม่ได้ Query ซ้ำ':'รับงานแล้ว • '+fourLabel(mode));refreshFourStatus();
 }catch(e){if(!silent)alert(e.message);}
}
async function refreshFourStatus(){
 if(fourState.statusBusy)return;fourState.statusBusy=true;clearTimeout(fourState.statusTimer);
 try{
  const r=await fetch('/api/query-status?department=ALL',{cache:'no-store'}),d=await r.json();if(!r.ok||!d.ok)throw new Error('Cannot read server status');
  const prior=fourState.view?.work_date;fourState.views=d.views||fourState.views;
  fourState.clockOffset=new Date(d.server_time).getTime()-Date.now();updateThaiClock();
  if(prior&&fourState.views.find(x=>x.mode===fourState.mode)?.work_date!==prior)await load();
  const active=d.active||[],running=d.running||active[0],recent=d.recent||[],j=running||recent[0];
  syncFourButtons(active);jobRunning=active.some(x=>x.department===dept());
  const head=$('querylive'),bar=$('livequerybar');bar.style.display='block';
  if(j){
   let trigger=j.source==='AUTO'?(j.trigger==='schedule'?'AUTO • Scheduled':j.trigger==='workflow_dispatch'?'AUTO • Manual trigger':'AUTO'):'MANUAL';
   const label=j.status==='done'?(j.error_count?'COMPLETED WITH ERRORS':'COMPLETED'):j.status.toUpperCase();
   head.textContent=`${running?'🔄':j.status==='error'?'🔴':'✅'} ${trigger} • ${j.department} • ${fourLabel(j.mode)} • ${label}`;
   $('livequerytitle').textContent=head.textContent;
   const timing=[j.scheduled_at?'ตั้งไว้ '+thaiTime(j.scheduled_at):'',j.started_at?'เริ่มจริง '+thaiTime(j.started_at):'รอเริ่ม',j.finished_at?'จบ '+thaiTime(j.finished_at):'',j.start_delay_minutes!==undefined?'เริ่มช้า '+j.start_delay_minutes+' นาที':''].filter(Boolean).join(' | ');
   $('livequerymeta').textContent=`${j.date_label||j.work_date} • ${j.done||0}/${j.total||0} • ${timing} • เวลาไทย`;
   $('livequeryfill').style.width=(j.total?Math.min(100,(j.done||0)*100/j.total):0)+'%';
   $('livequerymessage').textContent=j.message||'';
  }else{
   head.textContent='🟢 IDLE';$('livequerytitle').textContent='🟢 IDLE • No query running';$('livequerymeta').textContent='พร้อมตรวจตามเวลาไทย • Asia/Bangkok (UTC+7)';$('livequeryfill').style.width='0%';$('livequerymessage').textContent='';
  }
  $('livequeryqueue').textContent=(d.queued||[]).filter(x=>x.job_id!==running?.job_id).map(x=>`${x.department} • ${fourLabel(x.mode)} • ${x.work_date}`).join(' → ');
  $('schedulerContact').textContent=d.scheduler_contact?'Scheduler ติดต่อครั้งล่าสุด: '+thaiTime(d.scheduler_contact.at_time)+' • '+d.scheduler_contact.source:'ยังไม่พบ Scheduler ติดต่อมาในเวอร์ชันนี้';
  let changed=false;
  for(const j of recent){
   if(!fourState.completed.has(j.job_id+':'+j.status)){
    fourState.completed.add(j.job_id+':'+j.status);if(j.department===dept()||dept()==='ALL')changed=true;
   }
  }
  if(changed){await load();if($('smodal').classList.contains('open')&&!fourState.dirty)await loadFourSchedule();}
 }catch(e){$('livequerytitle').textContent='⚠️ ติดต่อสถานะ Server ไม่สำเร็จ — กำลังลองใหม่';$('querylive').textContent='⚠️ STATUS UNKNOWN';}
 finally{fourState.statusBusy=false;fourState.statusTimer=setTimeout(refreshFourStatus,document.hidden?15000:2500);}
}
function markFourDirty(){fourState.dirty=true;$('scheduleSaveState').textContent='⚠️ ยังไม่ได้บันทึก — เวลาบน Server ยังเป็นค่าเดิม';}
function renderFourRules(slots){
 $('thaiRules').innerHTML=slots.map(r=>`<div class="thai-rule" data-rule-id="${esc(r.id)}"><label class="rule-on"><input class="rule-enabled" type="checkbox" ${r.enabled?'checked':''}> ใช้</label><select class="rule-mode" aria-label="Query mode">${Object.keys({LAST_DAY:1,DAY:1,LAST_NIGHT:1,TONIGHT:1}).map(m=>`<option value="${m}" ${r.mode===m?'selected':''}>${fourLabel(m)}</option>`).join('')}</select><label class="rule-time"><span>เวลาไทย (24 ชม.)</span><input type="text" inputmode="numeric" maxlength="5" pattern="[0-2][0-9]:[0-5][0-9]" placeholder="HH:MM" class="rule-at" value="${esc(r.time)}" required></label><button type="button" class="rule-remove" title="ปิดใช้รอบนี้">ปิดรอบ</button></div>`).join('');
 $('thaiRules').querySelectorAll('input,select').forEach(e=>e.onchange=markFourDirty);
 $('thaiRules').querySelectorAll('.rule-at').forEach(e=>{e.onfocus=()=>e.select();e.oninput=()=>{const digits=e.value.replace(/\D/g,'').slice(0,4);e.value=digits.length>2?digits.slice(0,2)+':'+digits.slice(2):digits;markFourDirty();};});
 $('thaiRules').querySelectorAll('.rule-remove').forEach(b=>b.onclick=()=>{b.closest('.thai-rule').querySelector('.rule-enabled').checked=false;markFourDirty();});
}
async function loadFourSchedule(){
 $('scheduleDept').textContent=dept();$('saveSchedule').disabled=dept()==='ALL';
 if(dept()==='ALL'){$('scheduleMeta').textContent='เลือกแผนกก่อนตั้งเวลา';return;}
 const expected=dept();
 try{
  const r=await fetch('/api/auto-schedule?department='+encodeURIComponent(expected),{cache:'no-store'}),d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||'Unable to read schedule');
  if(dept()!==expected)return;
  fourState.schedule=d.schedule;fourState.dirty=false;renderFourRules(d.schedule.slots);
  $('autoEnabled').checked=d.schedule.enabled;document.querySelectorAll('#workdayChecks input').forEach(c=>c.checked=d.schedule.weekdays.includes(Number(c.value)));
  $('scheduleSaveState').textContent='✓ ค่าที่โหลดจาก Server • บันทึกล่าสุด '+thaiTime(d.schedule.updated_at);
  const pend=d.pending||[],next=d.next_run,last=d.last_run;
  $('scheduleMeta').textContent=[pend.length?'ถึงเวลา/รอ Scheduler: '+pend.map(x=>fourLabel(x.mode)+' '+thaiTime(x.scheduled_at)).join(', '):'',next?'รอบถัดไป: '+fourLabel(next.mode)+' • '+thaiTime(next.at)+' • วันที่เริ่มกะ '+next.work_date:'ไม่มีรอบถัดไปที่เปิดใช้',(d.skipped||[]).length?'ยังไม่เริ่มรอบ: '+d.skipped.map(x=>fourLabel(x.mode)+' • '+x.reason).join(', '):'',last?'รอบล่าสุด: '+last.status+' • ตั้งไว้ '+thaiTime(last.scheduled_at)+' • เริ่ม '+thaiTime(last.started_at)+' • จบ '+thaiTime(last.finished_at):'ยังไม่มีประวัติ Auto'].filter(Boolean).join('\n');
  $('schedulePersistence').className=d.persistent?'okbox':'warnbox';$('schedulePersistence').textContent=d.persistent?'✓ PostgreSQL • รายชื่อ แผนก กะรายวัน และเวลาตั้งอัตโนมัติ':'⚠ SQLite สำหรับทดสอบเท่านั้น ไม่ถาวรบน Render Free';
 }catch(e){$('scheduleMeta').textContent='Schedule error: '+e.message;}
}
async function saveFourSchedule(){
 if(!fourState.schedule||fourState.schedule.department!==dept())return;
 const rows=[...document.querySelectorAll('#thaiRules .thai-rule')].map(e=>({id:e.dataset.ruleId,enabled:e.querySelector('.rule-enabled').checked,mode:e.querySelector('.rule-mode').value,time:e.querySelector('.rule-at').value}));
 const payload={etag:fourState.schedule.etag,department:dept(),enabled:$('autoEnabled').checked,weekdays:[...document.querySelectorAll('#workdayChecks input:checked')].map(x=>Number(x.value)),slots:rows};
 $('saveSchedule').disabled=true;
 try{
  const r=await fetch('/api/auto-schedule',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}),d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||'Save failed');
  toast(dept()+' schedule saved • เวลาไทย');await loadFourSchedule();
 }catch(e){alert(e.message);}finally{$('saveSchedule').disabled=false;}
}
function initFourViews(){
 $('qrun').onclick=()=>startQuery({mode:fourState.mode});
 $('qlastday').onclick=()=>selectFourView('LAST_DAY');$('qday').onclick=()=>selectFourView('DAY');$('qlast').onclick=()=>selectFourView('LAST_NIGHT');$('qtonight').onclick=()=>selectFourView('TONIGHT');
 $('qmissing').onclick=()=>startQuery({mode:fourState.mode,missing_only:true});
 $('addScheduleRule').onclick=()=>{
  const slots=[...document.querySelectorAll('#thaiRules .thai-rule')].map(e=>({id:e.dataset.ruleId,enabled:e.querySelector('.rule-enabled').checked,mode:e.querySelector('.rule-mode').value,time:e.querySelector('.rule-at').value}));
  if(slots.length>=12)return toast('รองรับสูงสุด 12 รอบต่อแผนก');
  slots.push({id:'custom_'+Date.now(),mode:'DAY',time:'08:30',enabled:false});renderFourRules(slots);markFourDirty();
 };
 $('autoEnabled').onchange=markFourDirty;document.querySelectorAll('#workdayChecks input').forEach(e=>e.onchange=markFourDirty);
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshFourStatus();});
 updateThaiClock();syncFourButtons(fourState.active);
}
