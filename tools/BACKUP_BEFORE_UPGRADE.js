/* Optional read-only rescue tool for the OLD v9-v12.2 app.
   Open the old Attendance app on the SAME browser used for maintenance.
   Run this file's contents in browser DevTools Console after reviewing it.
   It reads same-origin APIs and localStorage, downloads JSON, and sends no data elsewhere.
   It does NOT modify server employees/schedules or clear browser storage.
*/
(async()=>{
 const copies=[];
 async function get(url){const r=await fetch(url,{cache:'no-store'});const d=await r.json();if(!r.ok||!d.ok)throw new Error(url);return d}
 try{
  const d=await get('/api/departments');
  for(const x of d.departments||[]){
   const dept=x.code;
   try{
    const state=await get('/api/state/export?department='+encodeURIComponent(dept));
    let schedules=[];
    try{const s=await get('/api/auto-schedule?department='+encodeURIComponent(dept));if(s.schedule)schedules=[{department:dept,...s.schedule}]}catch{}
    copies.push({label:'Server • '+dept,pack:{...state,department:dept,departments:[{code:dept,name:x.name||dept}],schedules}});
   }catch(e){console.warn('Could not export server department',dept)}
  }
 }catch(e){console.warn('Server unreachable; browser copies will still be exported')}
 for(let i=0;i<localStorage.length;i++){
  const key=localStorage.key(i);if(!/^ccAttendance(?:State|Master)V9:/.test(key||''))continue;
  try{const p=JSON.parse(localStorage.getItem(key));if(p?.employees?.length)copies.push({label:'Browser • '+key,pack:{...p,department:p.department||key.split(':')[1]}})}catch{}
 }
 if(!copies.length){alert('No recoverable copies found. Keep the original Excel files. Nothing has been changed.');return}
 const pack={format:'cc-attendance-rescue',exported_at:new Date().toISOString(),copies};
 const a=document.createElement('a');const url=URL.createObjectURL(new Blob([JSON.stringify(pack,null,2)],{type:'application/json'}));a.href=url;a.download='CC_Attendance_BEFORE_UPGRADE_'+new Date().toISOString().replace(/[:.]/g,'-')+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),60000);
 console.log('Exported rescue copies:',copies.map(x=>({copy:x.label,employees:x.pack.employees?.length||0})));
})();
