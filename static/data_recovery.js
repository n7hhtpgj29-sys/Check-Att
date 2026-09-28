/* V12.1.1: explicit, add-only recovery. No implicit restore and no cloud secrets. */
(() => {
  'use strict';
  const byId = id => document.getElementById(id);
  let selectedPack = null;
  const dialog = document.createElement('dialog');
  dialog.id = 'dataRecoveryDialog';
  dialog.style.cssText = 'width:min(680px,94vw);max-height:85dvh;padding:18px;border:1px solid #ccd4dc;border-radius:14px;overflow:auto;color:#17212b';
  dialog.innerHTML = `<div style="display:flex;justify-content:space-between;gap:10px;align-items:center"><b>IMPORT / RECOVER DATA</b><button type="button" id="closeRecovery">Close</button></div>
  <p>กู้เฉพาะแผนกหรือรายชื่อที่ยังไม่มีใน Server เท่านั้น ไม่ลบหรือเขียนทับข้อมูลที่ Maintain ไว้แล้ว</p>
  <p>Import JSON: <input id="recoveryFile" type="file" accept=".json,application/json" style="max-width:100%"></p>
  <b>Backups on this browser / Copies in uploaded rescue file</b>
  <div id="recoveryCopies" style="display:grid;gap:8px;margin:12px 0"></div>
  <pre id="recoveryPreview" style="white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f6f8;padding:12px"></pre>
  <button type="button" id="confirmRecovery" disabled>IMPORT MISSING DATA</button>`;
  document.body.appendChild(dialog);
  function download(pack, name) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(pack,null,2)],{type:'application/json'}));
    const a=document.createElement('a'); a.href=url; a.download=name; a.click();
    setTimeout(()=>URL.revokeObjectURL(url),10000);
  }
  async function api(path, pack) {
    const res = await fetch(path,{cache:'no-store',...(pack===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(pack)})});
    const body=await res.json();
    if (!res.ok || !body.ok) throw new Error(body.error || 'Request failed');
    return body;
  }
  function addCopy(label,pack) {
    const b=document.createElement('button'); b.type='button'; b.textContent=label;
    b.style.cssText='text-align:left;overflow-wrap:anywhere';
    b.onclick=()=>preview(pack); byId('recoveryCopies').appendChild(b);
  }
  function browserCopies() {
    const target=byId('recoveryCopies'); target.replaceChildren();
    const rows=[];
    for(let i=0;i<localStorage.length;i++) {
      const key=localStorage.key(i);
      if(!/^ccAttendance(?:State|Master)V(?:9|1211):/.test(key||''))continue;
      try {
        const p=JSON.parse(localStorage.getItem(key));
        if(!p||!Array.isArray(p.employees))continue;
        p.department=p.department||key.split(':')[1];
        rows.push({label:`${p.department} • ${p.employees.length} employees • ${key.includes('State')?'State':'Master'} • ${p.saved_at||'unknown date'}`,pack:p});
      } catch (_) { /* Leave unrecognized originals intact. */ }
    }
    for(const r of rows)addCopy(r.label,r.pack);
    if(!rows.length)target.textContent='No browser backups found. Import a JSON backup or use the original Employee Master Excel.';
  }
  async function preview(pack) {
    selectedPack=null; byId('confirmRecovery').disabled=true;
    const output=byId('recoveryPreview'); output.textContent='Checking…';
    try {
      const d=await api('/api/data/import-preview',pack);
      selectedPack=pack;
      output.textContent=`Departments in file: ${d.departments_in_file}\nNew departments: ${d.departments_to_add}\nEmployees in file: ${d.employees_in_file}\nNew employees: ${d.employees_to_add}\nExisting employees kept unchanged: ${d.employees_kept}\nCross-department conflicts (will not move): ${d.conflicts.length}`;
      if(d.conflicts.length)output.textContent+='\n'+d.conflicts.slice(0,20).map(x=>`${x.employee_code}: server ${x.server_department} / file ${x.file_department}`).join('\n');
      byId('confirmRecovery').disabled=false;
    } catch(e) { output.textContent='Preview failed: '+e.message; }
  }
  byId('recoverData').onclick=()=>{
    selectedPack=null; byId('confirmRecovery').disabled=true;
    byId('recoveryPreview').textContent='Select a backup to preview. Nothing is changed until you confirm.';
    browserCopies(); dialog.showModal();
  };
  byId('closeRecovery').onclick=()=>dialog.close();
  byId('recoveryFile').onchange=async e=>{
    const f=e.target.files[0];if(!f)return;
    try {
      if(f.size>20*1024*1024)throw new Error('Backup exceeds 20 MB');
      const pack=JSON.parse(await f.text());
      if(pack.format==='cc-attendance-rescue' && Array.isArray(pack.copies)) {
        byId('recoveryCopies').replaceChildren();
        for(const c of pack.copies)addCopy(c.label||'Rescue copy',c.pack);
        byId('recoveryPreview').textContent='Choose a copy above. Import server copies first, then older browser copies for missing records.';
      } else await preview(pack);
    } catch(e) { byId('recoveryPreview').textContent='Read failed: '+e.message; }
    e.target.value='';
  };
  byId('confirmRecovery').onclick=async()=>{
    if(!selectedPack || !confirm('เพิ่มเฉพาะข้อมูลที่ยังไม่มี โดยเก็บข้อมูลปัจจุบันทั้งหมดไว้ ยืนยัน?'))return;
    byId('confirmRecovery').disabled=true;
    try {
      const d=await api('/api/data/import',selectedPack);
      byId('recoveryPreview').textContent=`Imported: ${d.departments_added} departments / ${d.employees_added} employees / ${d.attendance_added} attendance rows. Existing data kept.\nCheck Auto Schedule of imported departments once before the next run.`;
      await load();
      if(selectedPack.department && [...byId('dept').options].some(o=>o.value===selectedPack.department)) {
        byId('dept').value=selectedPack.department; await onDeptChange();
      }
      toast('Recovery completed — existing data was not overwritten');
    }catch(e){byId('recoveryPreview').textContent='Import failed: '+e.message;}
    finally{byId('confirmRecovery').disabled=false;}
  };
  byId('backupAllData').onclick=async()=>{
    const b=byId('backupAllData'); b.disabled=true;
    try {
      const pack=await api('/api/data/export-all');
      download(pack,'CC_Attendance_BACKUP_ALL_'+new Date().toISOString().replace(/[:.]/g,'-')+'.json');
      toast('All departments backed up. Keep the JSON private; do not upload it to GitHub.');
    }catch(e){alert('Backup failed: '+e.message);}finally{b.disabled=false;}
  };
  async function storageStatus() {
    try {
      const h=await api('/api/health');
      byId('dataSafetyState').textContent=h.persistent_data ? '✓ DATA SAVED IN POSTGRESQL • Departments + Employees + Attendance + Schedules' : '⚠ LOCAL STORAGE ONLY — NOT SAFE FOR RENDER. Set DATABASE_URL.';
    }catch(e){byId('dataSafetyState').textContent='⚠ Storage check failed — '+e.message;}
  }
  storageStatus();
  window.addEventListener('online',storageStatus);
})();
