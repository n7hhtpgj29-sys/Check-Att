CC Attendance V12.1.1 — Persistent Department & Employee Master
============================================================
ต่อจาก V12.1 ที่ใช้อยู่ ไม่เปลี่ยน GitHub Auto Query Scheduler

สำคัญที่สุด
1. สำรองข้อมูลเดิมก่อน Deploy / Restart / เปลี่ยน Environment
2. ต้องเชื่อม PostgreSQL หนึ่งครั้ง จึงแก้ข้อมูลหายบน Render Free ได้จริง
3. ไม่ต้องแก้ .github/workflows/attendance-auto-query.yml ของ V12.1
4. ไม่ต้องตั้ง Render Cron หรือ cron-job.org สำหรับชุดนี้
5. ยังไม่ได้ Deploy หรือเชื่อมฐานข้อมูลจริงในบัญชีของคุณ

ทำไมข้อมูลหาย
- รุ่นเดิม db() ใช้ SQLite สำหรับ Department, Employees และ Attendance
- DATABASE_URL ในรุ่นเดิมช่วยเก็บเฉพาะ Auto Schedule ไม่ใช่รายชื่อ
- Render Free ไม่เก็บไฟล์ SQLite ข้าม Restart / Redeploy / Spin down
- เมื่อฐานข้อมูลว่าง init() สร้าง PE เป็นแผนกเริ่มต้น จึงเหลือ PE ว่าง
- เบราว์เซอร์รุ่นเดิม Restore Backup เก่าอัตโนมัติ จึงอาจนำรายชื่อเก่ามาแทนข้อมูลใหม่

ชุดนี้แก้อะไร
- Department + Employee Master + Attendance + Auto Schedule + Auto run history ใช้ PostgreSQL กลาง
- ตารางใหม่อยู่ใน schema cc_attendance ไม่ใช่ public หรือ attendance_app ของ V12.3
- เมื่อ DATABASE_URL ใช้ไม่ได้ จะไม่เปลี่ยนไปใช้ SQLite ว่างเงียบ ๆ
- ปิด Automatic Restore จาก LocalStorage: กู้ข้อมูลเมื่อผู้ใช้ Preview และยืนยันเท่านั้น
- Import Backup เพิ่มเฉพาะข้อมูลที่ยังไม่มี ไม่ลบและไม่ทับชื่อที่ Maintain ใหม่แล้ว
- นำเข้า Excel แบบ Merge: พนักงานที่ไม่อยู่ในไฟล์ยังไม่ถูกลบ/ปิด Active
- พบ employee_code เดียวกันในแผนกอื่นจะแจ้ง conflict ไม่ย้ายแผนกเงียบ ๆ
  ข้อจำกัดที่คงไว้จาก V12.1: หนึ่ง employee_code อยู่ในหนึ่ง Department เท่านั้น
- เก็บ Backup V9-V12.1 ในเบราว์เซอร์เดิมไว้ ไม่ล้าง ไม่ Restore อัตโนมัติ
- มี BACKUP ALL DEPARTMENTS และ IMPORT / RECOVER DATA ที่ด้านบน Dashboard
- Query ของแผนกที่ยังไม่มีพนักงานจะไม่กินรอบ Auto ระหว่างย้ายข้อมูล
- คงเวลา, รูปแบบ Query, Workflow และ Token ของ GitHub เดิม

A. ก่อนอัปเดต — เก็บข้อมูลที่ยังเหลืออยู่
------------------------------------
เปิดเว็บเก่าด้วยเบราว์เซอร์/เครื่องที่ใช้ Maintain เดิม
เลือก PE -> Employee Master -> Export JSON เก็บไฟล์
ทำเช่นเดียวกันกับ PEM และ AME ที่ยังเลือกได้ เก็บ Excel ต้นฉบับและรูปเวลา Schedule ด้วย
ถ้าแผนกหายจากตัวเลือกแล้ว อย่าลบ PWA / อย่าล้าง Safari หรือ Chrome
ชุดใหม่ค้น Backup ของแผนกที่หายจาก LocalStorage ได้โดยไม่ต้อง Add แผนกก่อน

ทางเลือกสำหรับ IT: tools/BACKUP_BEFORE_UPGRADE.js
- อ่านโค้ดก่อนใช้งาน แล้วเรียกบนหน้า Attendance เดิมใน DevTools Console
- อ่าน GET API ของเว็บเดิมและ Backup ใน LocalStorage แล้วดาวน์โหลด rescue JSON
- ไม่ลบ ไม่ POST Restore ไม่ส่งข้อมูลไปเว็บอื่น และไม่อ่าน Token/รหัสลับ
- ถ้าเบราว์เซอร์บล็อกการวางโค้ด ให้ใช้ Export JSON ผ่านเมนูปกติแทน
- ไฟล์ rescue รวมหลายสำเนา ใช้ IMPORT / RECOVER DATA เลือก Preview ทีละสำเนา
  ให้ Import สำเนา Server ล่าสุดก่อน แล้วค่อยเติมข้อมูลที่ยังขาดจาก Browser เก่า

ถ้าข้อมูลหายจาก Server แล้ว และไม่มี Browser Backup / JSON / Excel เหลือ
ต้องนำต้นฉบับเข้ามาใหม่ โค้ดไม่สามารถสร้างข้อมูลที่สูญหายขึ้นมาเอง
ห้ามอัปโหลด JSON/SQLite/Excel รายชื่อจริงหรือ DATABASE_URL ขึ้น GitHub

B. สร้างฐานข้อมูล PostgreSQL แบบ Free หนึ่งครั้ง
--------------------------------------------
ใช้ Supabase Free หรือ PostgreSQL ที่ IT จัดเตรียมให้
สำหรับ Supabase: Create Project -> Free -> รอพร้อม -> Connect -> Session pooler
ใช้ connection string พอร์ต 5432 ตามหน้า Connect จริง ไม่ใช้ API URL/anon key
ใส่ database password ให้ถูกต้อง; อักขระพิเศษในรหัสผ่านต้อง URL-encode
เปิด SSL (sslmode=require); หาก URL มี ? แล้วให้ต่อด้วย &sslmode=require
อย่าใส่ credential ลง Source code และอย่าส่งภาพที่เห็นค่าเต็มมาในแชต

Free plan มีโควตาและเงื่อนไข ไม่ใช่บริการรับประกัน 24/7
Supabase ระบุโควตาฐานข้อมูล Free 500 MB ต่อ Project และอาจพัก Project ที่ไม่ใช้งาน
ติดตาม Usage และ Export Backup แยกไว้ ไม่เพิ่ม Paid add-on โดยไม่ตั้งใจ
ให้ IT/MIS อนุมัติการเก็บข้อมูลพนักงานบน Cloud ก่อนนำเข้าข้อมูลจริง

C. ตั้ง Render เดิม — ไม่ต้องสร้าง Server ใหม่
-----------------------------------------
Render -> cc-attendance-iphone-pwa -> Environment -> Edit
เพิ่ม:
DATABASE_URL = connection string จาก Supabase Session pooler
REQUIRE_POSTGRES = true

คงค่าที่มีอยู่: AUTO_QUERY_TOKEN, TZ=Asia/Bangkok, PLAYWRIGHT_HEADLESS=0
คง GitHub Secret ATTENDANCE_AUTO_TOKEN เดิม
หลังสำรองข้อมูลแล้ว เลือก Save only เพื่อใช้ค่าพร้อม Deploy โค้ดใหม่
อย่า Save and deploy ด้วยโค้ดเก่าก่อน Export ข้อมูล

D. อัปโหลด V12.1.1
-----------------
แตก ZIP แล้วอัปโหลดไฟล์ข้างในไปที่ root ของ repo Check-Att
อย่าอัปโหลด ZIP เป็นไฟล์เดียว หรือซ้อนเป็นโฟลเดอร์โครงการอีกชั้น
ไฟล์หลักที่เปลี่ยน/เพิ่ม:
app.py
persistent_store.py             (ใหม่ — ต้องมี)
data_recovery.py                (ใหม่ — ต้องมี)
templates/index.html
static/data_recovery.js         (ใหม่ — ต้องมี)
static/sw.js
.gitignore และ .dockerignore

Dockerfile, start.sh และ requirements.txt คงรูปแบบ V12.1
ไฟล์ .github/workflows/attendance-auto-query.yml ใน ZIP เหมือน V12.1 แบบ byte-for-byte
ไม่ต้องเปิด Edit Workflow และไม่ต้องเปลี่ยนชื่อเป็น V12.3 Manual Diagnostics
หากเคยปิด Workflow เดิมไว้ ต้องเปิดใช้งาน Schedule เดิมกลับก่อนรอ Auto
Commit แล้วรอ Render Auto Deploy จน Live

E. ตรวจการเก็บข้อมูล ก่อนเริ่ม Maintain
------------------------------------
เปิด /api/health ต่อท้าย URL Attendance เดิม ต้องได้:
version: 12.1.1-persistent-master
data_store: postgres
persistent_data: true
persistent_master: true
persistent_departments: true
persistent_schedule: true

ถ้าเป็น sqlite-local / false: ยังไม่ได้แก้ข้อมูลหายบน Cloud
ถ้า Deploy ไม่ผ่านเพราะ DATABASE_URL: ตรวจ connection/password/project status
ห้ามแก้โดยปิด REQUIRE_POSTGRES เพื่อฝืนใช้ฐานข้อมูลว่าง
เมื่อต่อ PostgreSQL ครั้งแรก ฐานข้อมูลใหม่อาจมีเพียง PE ว่าง จนกว่าจะ Import หนึ่งครั้ง

F. นำรายชื่อเก่าเข้าฐานข้อมูลกลางหนึ่งครั้ง
---------------------------------------
Dashboard -> IMPORT / RECOVER DATA
เลือก JSON ที่สำรองไว้ หรือเลือก Backup ของ PE / PEM / AME ที่พบในเบราว์เซอร์เดิม
Preview แสดงจำนวนแผนก/คนที่จะเพิ่ม คนที่มีแล้วและ conflict
กด IMPORT MISSING DATA แล้วตรวจจำนวนพนักงาน
การ Import ซ้ำไม่ลบคนเดิม และไม่เขียนทับข้อมูลที่ Maintain บน Server
ถ้าชื่อเก่าแตกต่างจากชื่อใหม่ที่มีแล้ว ระบบเก็บข้อมูล Server ไว้
ถ้าไม่พบ Browser Backup ให้ Import JSON หรือ Upload Employee Master Excel ต้นฉบับ

ตรวจเวลา Settings -> Auto Schedule ของแต่ละแผนกอีกครั้งหลังย้ายครั้งแรก
Schedule ของแผนกใหม่จาก Backup จะถูกนำเข้าเมื่อยังไม่มีค่าอยู่
Schedule ของแผนกที่มีอยู่แล้วจะไม่ถูก Backup เก่าทับ (รวม PE เริ่มต้น)
ตั้ง/Save เวลา PE อีกครั้งหากไม่ตรงกับค่าที่ต้องการ
ประวัติรอบ done ของ SQLite เก่าไม่ถูกนำเข้า จึงอาจมีการตรวจซ้ำหนึ่งครั้งในช่วง grace ระหว่างการย้าย
หลังย้ายแล้ว Auto run history ใหม่จะคงอยู่ใน PostgreSQL ข้ามการ Deploy

G. ใช้งานประจำวัน
----------------
การเพิ่มแผนกหรือแก้รายชื่อสำเร็จ = บันทึกฐานข้อมูลกลางแล้ว
ไม่ต้องกด Backup ใน iPhone ทุกครั้งเพื่อรักษาข้อมูล
ยังควรกด BACKUP ALL DEPARTMENTS เก็บไฟล์ JSON แยกเป็นระยะ
ใช้ Edit -> Active/Inactive เมื่อจะปิดพนักงานอย่างตั้งใจ
Upload Excel รุ่นนี้ไม่ Deactivate คนที่ไม่ได้อยู่ในไฟล์โดยอัตโนมัติ
ใช้มือถือเครื่องอื่น/อีก Browser จะอ่าน Department และรายชื่อเดียวกันจาก Server

ทดสอบหลังย้ายครบ: จดจำนวนคน PE/PEM/AME -> ตรวจ persistent_data=true -> Restart/Deploy เดิม
เมื่อ Live เปิดเว็บใหม่ ต้องได้จำนวนและข้อมูลเดิม ไม่ต้อง Restore จากมือถือ
ห้าม Rollback กลับ app.py V12.1 เดิมเพียงไฟล์เดียว เพราะโค้ดเดิมจะกลับไปอ่าน SQLite

ข้อจำกัดที่ไม่ได้เปลี่ยนในชุดนี้
- GitHub Schedule ยังอาจ Delay; ไม่ได้แก้ความตรงเวลาของตัวตั้งเวลา
- กะ/ช่องรอบที่ done แล้วในวันเดียวกันยังใช้กฎกันรันซ้ำเดิม
- ยังไม่เพิ่ม Login หรือ Role รายแผนก; การควบคุมการเข้าถึงเว็บยังเหมือน V12.1
  ผู้เข้าถึงเว็บได้อาจแก้ข้อมูลได้ ต้องให้ IT จำกัดการเข้าถึงก่อนใช้งานจริงหลายแผนก
- ไม่รับประกันกู้ข้อมูลที่ไม่มีสำเนาเหลืออยู่
- PostgreSQL ต้องให้บริการอยู่ และต้องใช้ DATABASE_URL ของ Project เดิมทุกครั้ง
- โค้ดนี้ไม่เชื่อม/โอนข้อมูลเข้า Supabase ของคุณจนกว่าคุณจะตั้งค่าและ Import เอง

การตรวจสอบชุดนี้
- 32 offline tests: Store, restart/reopen, add-only import, rollback, cross-department protection,
  old-client restore, workflow byte equality และการไม่กินรอบของแผนกว่าง
- ใช้ SQLite จริงและ Flask test double เพื่อเรียก route bodies (ไม่ใช่ Flask integration test)
- ตรวจ DOM/การกู้ข้อมูลบน Chromium จำลอง 390px โดย API เป็น local test double
- ตรวจ Python compile และ JavaScript syntax
- ยังไม่ได้ทดสอบกับ PostgreSQL/Supabase/Render/MIS จริงในบัญชีของคุณ
  ต้องตรวจ health + import + restart ตามขั้นตอน E-G ก่อนถือว่าใช้งานสำเร็จ

เอกสารอ้างอิง (ตรวจ 28 กันยายน 2026)
https://render.com/docs/free
https://render.com/docs/configure-environment-variables
https://supabase.com/pricing
https://supabase.com/docs/guides/database/connecting-to-postgres
