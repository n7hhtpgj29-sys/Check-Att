/* Latest Excel Master v12.1.2. No framework; no secrets/local PII cache created here. */
(()=>{
 'use strict';
 const $id=id=>document.getElementById(id);
 const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const labels={add:'เพิ่มคนใหม่',update:'แก้ข้อมูล',reactivate:'เปิดใช้งานกลับ',transfer:'ย้ายแผนก',deactivate:'ปิดใช้งาน / เอาออก',unchanged:'ข้อมูลเหมือนเดิม'};
 const fieldLabels={department:'แผนก',full_name:'ชื่อ',location_support:'Location',team_support:'Team',group_code:'Group',shift:'กะ',active:'Active'};
 let selectedFile=null,target='',preview=null,applying=false,adminKey='',seq=0;
 const overlay=document.createElement('div');overlay.className='ms-overlay';overlay.id='masterSyncModal';
 overlay.innerHTML=`<section class="ms-panel" role="dialog" aria-modal="true" aria-labelledby="msTitle">
 <div class="ms-head"><div><div class="ms-eyebrow">EMPLOYEE MASTER · V12.1.2</div><h2 id="msTitle">อัปโหลดรายชื่อล่าสุด</h2><div class="ms-note" id="msSubtitle">ตรวจสอบก่อนบันทึก • ไม่ต้องล้างฐานข้อมูล</div></div><button class="ms-close" id="msClose" aria-label="ปิด">×</button></div>
 <div class="ms-body" id="msBody"></div><div class="ms-foot"><small id="msFootNote">ยังไม่มีการแก้รายชื่อ</small><div class="ms-actions"><button id="msCancel">ยกเลิก</button><button id="msApply" class="ms-primary" disabled>ยืนยันอัปโหลดทับ</button></div></div></section>`;
 document.body.append(overlay);
 function show(){document.body.style.overflow='hidden';overlay.classList.add('ms-open');$id('msClose').focus();}
 function close(){if(applying)return;seq++;document.body.style.overflow='';overlay.classList.remove('ms-open');preview=null;selectedFile=null;}
 $id('msClose').onclick=close;$id('msCancel').onclick=close;
 overlay.addEventListener('keydown',e=>{
  if(e.key==='Escape'){e.preventDefault();close();}
  if(e.key==='Tab'){
   const items=[...overlay.querySelectorAll('button:not(:disabled),input:not(:disabled),select,summary')].filter(x=>x.getClientRects().length);
   if(items.length&&e.shiftKey&&document.activeElement===items[0]){e.preventDefault();items.at(-1).focus();}
   else if(items.length&&!e.shiftKey&&document.activeElement===items.at(-1)){e.preventDefault();items[0].focus();}
  }
 });
 async function api(url,{form,json,method}={}){
  const headers={'Accept':'application/json'};
  if(adminKey)headers['X-Master-Admin-Key']=adminKey;
  let body=form;
  if(json!==undefined){headers['Content-Type']='application/json';body=JSON.stringify(json);}
  const r=await fetch(url,{method:method||(body?'POST':'GET'),headers,body,cache:'no-store',credentials:'same-origin'});
  let data;try{data=await r.json();}catch{throw new Error('Server ตอบกลับไม่ครบ กรุณาลองอีกครั้ง');}
  if(!r.ok||!data.ok){const e=new Error(data.error||('HTTP '+r.status));e.code=data.code;e.status=r.status;throw e;}
  return data;
 }
 function errorBox(message){let n=$id('msError');if(!n){n=document.createElement('div');n.id='msError';n.className='ms-error';$id('msBody').append(n);}n.textContent=message;n.scrollIntoView({block:'nearest'});}
 function authBox(retry){
  const n=document.createElement('div');n.className='ms-auth';n.innerHTML='<b>ระบบนี้ตั้งรหัส Master Admin ไว้</b><div><input id="msPassword" type="password" autocomplete="off" placeholder="รหัส Master Admin"><button id="msAuthRetry">ดำเนินการต่อ</button></div>';
  $id('msBody').append(n);$id('msAuthRetry').onclick=()=>{adminKey=$id('msPassword').value;n.remove();retry();};$id('msPassword').focus();
 }
 function setEnabled(){
  const d=preview;
  $id('msApply').disabled=applying||!d||!$id('msComplete')?.checked||$id('msDepartment')?.value.trim().toUpperCase()!==target||
   (d?.counts.deactivate>0&&!$id('msAckRemove')?.checked)||(d?.counts.transfer>0&&!$id('msAckTransfer')?.checked)||(d?.filename_mismatch&&!$id('msAckFilename')?.checked);
 }
 function render(d){
  preview=d;
  const countHtml=Object.entries(labels).map(([key,label])=>`<div class="ms-count"><strong>${d.counts[key]||0}</strong><span>${label}</span></div>`).join('');
  const groups=Object.entries(labels).filter(([key])=>key!=='unchanged'&&d.counts[key]).map(([key,label])=>`<details class="ms-detail" ${key==='transfer'?'open':''}><summary>${label} (${d.counts[key]})</summary><div class="ms-scroll">${d.changes.filter(x=>x.action===key).map(x=>`<div class="ms-person"><b>${escape(x.employee_code)} · ${escape(x.full_name)}</b><span>${escape(x.reason)}</span><small>${(x.field_changes||[]).map(y=>`${fieldLabels[y.field]||y.field}: ${y.before===''?'—':y.before} → ${y.after===''?'—':y.after}`).map(escape).join('\n')}</small></div>`).join('')}</div></details>`).join('');
  $id('msBody').innerHTML=`<div class="ms-file"><div><b>${escape(d.filename)}</b><small>${d.file_rows} รายการในไฟล์ · ใช้ชีตเดียวต่อครั้ง</small></div><label>ชีต <select id="msSheet">${d.sheets.map(s=>`<option ${s===d.sheet?'selected':''}>${escape(s)}</option>`).join('')}</select></label></div>
   ${d.warnings.map(w=>`<div class="ms-warning">⚠ ${escape(w)}</div>`).join('')}
   <div class="ms-target">แผนก ${escape(target)} · Active ${d.active_before} → ${d.active_after} คน<br><span class="ms-note">เปลี่ยนกะ ${d.counts.shift_change} คน · ไฟล์ล่าสุดต้องมีรายชื่อครบทั้งกะ Day และ Night</span></div>
   <div class="ms-counts">${countHtml}</div>${groups||'<p>ข้อมูลตรงกับไฟล์อยู่แล้ว</p>'}
   <div class="ms-confirm"><b>ตรวจสอบก่อนยืนยัน</b>
   <label><input type="checkbox" id="msComplete">ไฟล์นี้เป็นรายชื่อฉบับล่าสุดครบทั้งแผนก ${escape(target)} ไม่ใช่เฉพาะบางกะหรือบางทีม</label>
   ${d.counts.deactivate?`<label><input type="checkbox" id="msAckRemove">ยืนยันปิดใช้งาน ${d.counts.deactivate} คน: ไม่แสดงใน Dashboard / ไม่ Query รอบใหม่ แต่ไม่ลบประวัติทิ้ง</label>`:''}
   ${d.counts.transfer?`<label><input type="checkbox" id="msAckTransfer">ยืนยันย้าย ${d.counts.transfer} คนจากแผนกเดิมเข้า ${escape(target)} เฉพาะรหัสในไฟล์นี้</label>`:''}
   ${d.filename_mismatch?`<label><input type="checkbox" id="msAckFilename">ตรวจแล้ว: ชื่อไฟล์ดูเป็น ${escape(d.filename_department)} แต่ตั้งใจใช้กับ ${escape(target)} จริง</label>`:''}
   <span>พิมพ์ <b>${escape(target)}</b> เพื่อยืนยันแผนก</span><input type="text" id="msDepartment" autocomplete="off" autocapitalize="characters" placeholder="${escape(target)}" aria-label="พิมพ์ชื่อแผนกเพื่อยืนยัน">
   <div class="ms-note">ระบบเก็บ Backup ก่อนบันทึก 20 รอบล่าสุด · กะ/Group/แผนกที่เปลี่ยนจะรอ Query ใหม่ ไม่ใช้ผล PRESENT ของกะเดิม</div></div>`;
  $id('msSheet').onchange=()=>loadPreview($id('msSheet').value);
  $id('msBody').querySelectorAll('input').forEach(x=>x.oninput=setEnabled);
  $id('msApply').hidden=false;$id('msApply').textContent='ยืนยันอัปโหลดทับ';$id('msCancel').textContent='ยกเลิก';
  $id('msFootNote').textContent='Preview นี้มีอายุ 20 นาที • ยังไม่เปลี่ยนรายชื่อ';setEnabled();
 }
 async function loadPreview(sheet=''){
  const id=++seq;preview=null;$id('msApply').disabled=true;$id('msBody').textContent='กำลังอ่าน Excel และเทียบรายชื่อ…';
  try{
   const fd=new FormData();fd.append('file',selectedFile);fd.append('department',target);if(sheet)fd.append('sheet',sheet);
   const d=await api('/api/master-sync/preview',{form:fd});if(id!==seq)return;render(d);
  }catch(e){if(id!==seq)return;errorBox(e.message);if(e.code==='ADMIN_REQUIRED')authBox(()=>loadPreview(sheet));}
 }
 async function downloadBackup(auditId){
  const pack=await api('/api/master-sync/audit/'+auditId+'/backup');
  const url=URL.createObjectURL(new Blob([JSON.stringify(pack,null,2)],{type:'application/json'}));
  const a=document.createElement('a');a.href=url;a.download='CC_Attendance_before_import_'+auditId+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),3000);
 }
 $id('msApply').onclick=async()=>{
  if(!preview||applying)return;
  applying=true;setEnabled();$id('msClose').disabled=true;$id('msCancel').disabled=true;$id('msApply').textContent='กำลังบันทึก…';
  try{
   const d=await api('/api/master-sync/apply',{json:{preview_token:preview.preview_token,confirm_department:$id('msDepartment').value.trim(),
      ack_remove:!!$id('msAckRemove')?.checked,ack_transfer:!!$id('msAckTransfer')?.checked,ack_filename:!!$id('msAckFilename')?.checked}});
   preview=null;
   $id('msBody').innerHTML=`<div class="ms-success"><b>✓ บันทึกแผนก ${escape(d.department)} เรียบร้อย</b><br>Active ${d.active_before} → ${d.active_after} คน<br>เพิ่ม ${d.counts.add} · แก้ ${d.counts.update} · เปิดกลับ ${d.counts.reactivate} · ย้าย ${d.counts.transfer} · ปิด ${d.counts.deactivate}</div><p>แผนกอื่นคงเดิม ยกเว้นรหัสที่คุณยืนยันย้ายเข้ามา</p><p class="ms-note">อัปเดตกะหรือแผนกแล้วให้กด Query กะที่ต้องการ หรือรอ Auto Query รอบถัดไป</p><button id="msDownloadBackup">ดาวน์โหลด Backup ก่อนอัปโหลดครั้งนี้</button><p class="ms-note">Backup มีข้อมูลพนักงาน เก็บส่วนตัว ห้ามอัปโหลดขึ้น GitHub</p>`;
   $id('msDownloadBackup').onclick=()=>downloadBackup(d.audit_id).catch(e=>errorBox(e.message));
   $id('msFootNote').textContent='บันทึกลงฐานข้อมูลแล้ว';$id('msApply').hidden=true;$id('msCancel').textContent='ปิด';
   try{
    await load();
    if($id('emodal')?.classList.contains('open'))await openMaster();
    if(typeof backupState==='function')await backupState(true);
   }catch{errorBox('บันทึกสำเร็จแล้ว แต่โหลด Dashboard ไม่สำเร็จ กรุณา Refresh หน้าเว็บ');}
  }catch(e){
   errorBox(e.message+(e.code==='STALE_PREVIEW'||e.code==='PREVIEW_EXPIRED'?' — ปิดหน้าต่างแล้วเลือกไฟล์เดิมเพื่อ Preview ใหม่':e.code==='QUERY_BUSY'?' — เมื่อ Query เสร็จให้กดยืนยันอีกครั้ง':' — หากการเชื่อมต่อหลุด สามารถกดยืนยันซ้ำด้วย Preview เดิม ระบบป้องกันบันทึกซ้ำ'));
   if(['STALE_PREVIEW','PREVIEW_EXPIRED'].includes(e.code))preview=null;
  }finally{applying=false;$id('msClose').disabled=false;$id('msCancel').disabled=false;$id('msApply').textContent='ยืนยันอัปโหลดทับ';setEnabled();}
 };
 async function openFile(file,department){
  if(!department||department==='ALL'){alert('เลือกแผนกเดียวก่อนอัปโหลด');return;}
  if(applying)return;
  selectedFile=file;target=department;preview=null;$id('msTitle').textContent='อัปโหลดทับรายชื่อแผนก '+target;
  $id('msSubtitle').textContent='Excel ล่าสุด = รายชื่อหลักของแผนกที่เลือก';$id('msApply').hidden=false;$id('msCancel').textContent='ยกเลิก';show();await loadPreview();
 }
 async function openHistory(){
  if(applying)return;target=dept();if(target==='ALL'){alert('เลือกแผนกก่อนดูประวัติ');return;}
  preview=null;selectedFile=null;$id('msTitle').textContent='ประวัติอัปโหลด · '+target;$id('msSubtitle').textContent='Backup ก่อนอัปโหลด 20 รอบล่าสุดรวมทุกแผนก';
  $id('msApply').hidden=true;$id('msCancel').textContent='ปิด';$id('msBody').textContent='กำลังโหลด…';show();
  try{
   const d=await api('/api/master-sync/history?department='+encodeURIComponent(target));
   $id('msBody').innerHTML=d.imports.map(x=>`<div class="ms-history"><b>${escape(x.filename)}</b><div>${new Date(x.created_at).toLocaleString('th-TH')} · Active ${x.summary.active_before} → ${x.summary.active_after}</div><button data-audit="${escape(x.id)}">ดาวน์โหลด Backup ก่อนอัปโหลด</button></div>`).join('')||'<p>ยังไม่มีประวัติอัปโหลดของแผนกนี้</p>';
   $id('msBody').querySelectorAll('[data-audit]').forEach(b=>b.onclick=()=>downloadBackup(b.dataset.audit).catch(e=>errorBox(e.message)));
  }catch(e){errorBox(e.message);if(e.code==='ADMIN_REQUIRED')authBox(openHistory);}
 }
 const button=document.createElement('button');button.id='masterSyncHistory';button.className='ghost';button.textContent='ประวัติอัปโหลด';button.onclick=openHistory;
 $id('upload').insertAdjacentElement('afterend',button);
 const picker=document.createElement('input');picker.type='file';picker.accept='.xlsx';picker.hidden=true;picker.id='masterSyncFile';
 picker.onchange=()=>{const f=picker.files?.[0];if(f)openFile(f,dept());picker.value='';};document.body.append(picker);
 const mobileUpload=document.createElement('button');mobileUpload.id='masterSyncChoose';mobileUpload.className='ms-mobile-upload';mobileUpload.textContent='📄 อัปโหลด Excel ล่าสุด';
 mobileUpload.onclick=()=>{if(dept()==='ALL')return alert('เลือกแผนกเดียวก่อนอัปโหลด');picker.click();};
 button.insertAdjacentElement('beforebegin',mobileUpload);
 window.MasterSyncUI={openFile,openHistory};
})();
