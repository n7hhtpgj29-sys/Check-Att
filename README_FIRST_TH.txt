CC Attendance V12.1.3 — Thai Time / Four Views
================================================
ต่อจาก V12.1.2: คง PostgreSQL เดิม, Latest Excel Master, เพิ่ม/ลดคน เปลี่ยนกะ ย้ายแผนก
ใช้ GitHub Actions เดิมเป็น scheduler ไม่ต้องซื้อ Render Cron หรือสมัครบริการเพิ่ม

ต้องทำ 4 อย่าง
1) ในเว็บเดิม กด BACKUP ALL DEPARTMENTS เก็บ JSON ส่วนตัวก่อนอัปเดต
2) แตก ZIP อัปโหลดไฟล์ข้างในทั้งหมดทับ Check-Att (อย่าอัปโหลดทั้งโฟลเดอร์ซ้อน)
3) อัปเดต .github/workflows/attendance-auto-query.yml ด้วยไฟล์ใน ZIP นี้ด้วย
   ชื่อ Actions ต้องเป็น Attendance Auto Query V12.1.3; คง Secret เดิม
4) รอ Render Live แล้ว Refresh/เปิด PWA ใหม่

ห้ามลบ Supabase Project, ห้ามสร้างฐานใหม่, ห้ามล้างรายชื่อเพื่ออัปเดตรุ่นนี้
คง DATABASE_URL เดิม, REQUIRE_POSTGRES=true, AUTO_QUERY_TOKEN, TZ=Asia/Bangkok
ใน GitHub คง ATTENDANCE_AUTO_TOKEN ค่าเดียวกับ AUTO_QUERY_TOKEN
ไม่ได้เปลี่ยนราคา/แพ็กเกจ ไม่ได้ Deploy หรือแก้ข้อมูลจริงในบัญชีผู้ใช้ให้

ไฟล์ใหม่/ไฟล์สำคัญ
app.py, persistent_store.py, master_sync.py, data_recovery.py,
shift_history.py, thai_schedule.py, shift_backup.py,
static/shift_views.js, static/shift_views.css, templates/index.html, static/sw.js,
.github/workflows/attendance-auto-query.yml
อัปโหลดทั้งชุดเพื่อไม่ให้ขาดไฟล์ import

ตรวจ /api/health
version = 12.1.3-thai-time-four-views
tz = Asia/Bangkok
utc_offset = +07:00
persistent_data = true
persistent_schedule = true
server_time ลงท้าย +07:00

การใช้งานหน้าเว็บ
เลือกแผนก -> แตะ Last Day / Today / Last Night / Tonight เพื่อดูข้อมูลที่บันทึกไว้
ใต้แท็บมีวันที่เริ่มกะจริง; Night แสดงวันเริ่ม -> วันถัดไป
แตะแท็บไม่ได้เริ่ม Query ทันที ใช้ปุ่ม Query <ชื่อช่วง> หรือ Recheck missing
Today's date อิงวันไทย ไม่อิง Timezone มือถือ
Last Day = กลางวันเมื่อวาน; Today = กลางวันวันนี้
Last Night = กลางคืนเริ่มเมื่อวานถึงเช้าวันนี้; Tonight = คืนวันนี้ถึงเช้าพรุ่งนี้
ข้อมูลแต่ละวัน/กะแยกกัน Query เมื่อวานไม่ทับผลวันนี้
หลังเที่ยงคืน Tonight เดิมกลายเป็น Last Night ของวันใหม่

รักษาประวัติการเปลี่ยนกะ
บันทึกสำเนารายชื่อแยก Department + วันที่เริ่มกะ + D/N
บันทึกผลแยก Department + วันที่เริ่มกะ + D/N + Employee code
อัปโหลด Excel ล่าสุดมีผลกับรายชื่อปัจจุบันของวันที่ไทยทันที ไม่ใช่การตั้งกะล่วงหน้า
รายชื่อที่บันทึกของวันก่อนจะไม่เปลี่ยนตามไฟล์ใหม่หรือการย้ายแผนกวันนี้
สำเนาวันปัจจุบันอัปเดตตาม Master; ระบบเก็บสำเนาเมื่อเริ่มแอป/เปิด Dashboard/ตรวจ scheduler/เปลี่ยน Master
ถ้า Server ไม่เคยทำงานในวันหนึ่งและไม่มีสำเนาวันนั้น จะไม่เดารายชื่อย้อนหลัง
ข้อมูลย้อนหลังเริ่มสะสมตั้งแต่ติดตั้ง V12.1.3; Last Day/Last Night ก่อนติดตั้งอาจไม่มีข้อมูล
จะแสดง "ไม่มีรายชื่อกะที่บันทึกไว้" และไม่สรุปว่าขาดงาน
ข้อมูล cache วันปัจจุบันเดิมย้ายได้เฉพาะรายการที่พิสูจน์ได้ว่า Master ไม่ถูกแก้หลัง Query
รายการที่พิสูจน์ไม่ได้จะรอ Query ใหม่ ไม่ลบ Master หรือฐานเดิม
ไม่มีการร้องขอ MIS ย้อนหลังที่เว็บไซต์ไม่รองรับ: อ่านเฉพาะแถวที่ MIS ส่งกลับตามวิธีเดิม
ถ้าไม่มีแถวตรงวัน/กะเก่า จะเป็น NO DATA FOR SHIFT ไม่ใช่ NO SCAN

Maintain เวลา
เลือกแผนก -> Settings / Auto Schedule
เวลาไทยทั้งหมด รูปแบบ 24 ชั่วโมง HH:MM; 4:40 PM = 16:40, 4:40 AM = 04:40
ช่องกรอกเป็นข้อความ 24 ชั่วโมง ไม่เปลี่ยนเป็น AM/PM ตามประเทศของเบราว์เซอร์
Mon–Sun หมายถึงวันที่เริ่ม Query ไม่ใช่วันที่เริ่มกะ
ตัวอย่างตรวจคืนวันเสาร์ที่ 06:00 วันอาทิตย์ ต้องเปิดวันอาทิตย์ด้วย
เปิด ON ทั้งแผนก และเลือกใช้เฉพาะรอบที่ต้องการ
แต่ละรอบเลือก Today / Last Day / Last Night / Tonight กับเวลาได้เอง
Today ใส่ได้สองรอบหรือมากกว่า; รองรับรวมสูงสุด 12 รอบต่อแผนก
ปุ่มเพิ่มรอบเริ่มเป็น OFF ให้เปิดเมื่อพร้อม; ปิดรอบเก่าจะไม่ลบประวัติ
เวลาที่ถูก Save ในรุ่นเดิมทั้ง 4 ช่องจะย้ายมาใช้ ไม่รีเซ็ตเป็นค่า Default
เพิ่ม Last Day 07:00 เป็น OFF ในการย้ายรุ่น ไม่เริ่ม Query เพิ่มเอง

ตัวอย่างเมื่อยังไม่มีเวลาปรับเอง
Today         08:15  ดูเข้ากะเช้า
Today         18:00  ดูออกกะ/OT วันนี้
Tonight       20:15  ดูเข้ากะคืนนี้
Last Night    06:00  ดูออกกะเมื่อคืน
Last Day      OFF   เปิดเพิ่มเมื่อต้องการตรวจทวนกลางวันเมื่อวาน
18:00 ต้อง Today, ไม่ใช่ Last Day; 06:00 ต้อง Last Night, ไม่ใช่ Tonight

หลังเปลี่ยนเวลา ต้องกด SAVE DEPARTMENT SCHEDULE
เห็น "ยังไม่ได้บันทึก" = Server ยังใช้ค่าเก่า ไม่ใช่กด Backup แทน Save
ระบบโหลดค่าจาก Server กลับมา พร้อมเวลา Save ล่าสุด
ถ้ามีคนแก้ Schedule หลังเราเปิด Settings จะไม่ทับเงียบ ๆ ต้องเปิดใหม่แล้วแก้
บันทึกเวลาเดิมซ้ำไม่สร้างรอบใหม่
แก้เวลาหรือ mode ในรอบที่ทำเสร็จแล้วจะเป็น revision ใหม่ สามารถทำรอบใหม่วันเดียวกันได้เมื่อถึงเวลา
ถ้าตั้งเวลาใหม่เป็นอดีตภายใน grace 180 นาที อาจเริ่มใน tick ถัดไปทันที
กดปิด/เปิด ON โดยเวลาไม่เปลี่ยน ไม่รันซ้ำรอบที่ done แล้ว
Next run จะไม่นับรอบที่ทำเสร็จแล้ว; แสดง pending/ข้ามเพราะกะว่างแยกกัน

อ่านแถบสถานะ
ตั้งไว้ -> เริ่มจริง -> จบ -> เริ่มช้า X นาที (ทั้งหมดเวลาไทย)
AUTO • Scheduled = GitHub เริ่มเองจาก event schedule
AUTO • Manual trigger = คุณกด Run workflow; ไม่ใช่หลักฐานว่า scheduler เริ่มเอง
MANUAL = กด Query ในหน้า Attendance
Scheduler ติดต่อครั้งล่าสุด แยกจากเวลา Query ล่าสุด
IDLE = ไม่มี Query รัน; STATUS UNKNOWN = ติดต่อสถานะ Server ไม่ได้ ไม่อ้างว่า Idle
งานข้ามเที่ยงคืนผูกวันเริ่มกะจาก scheduled_at ไม่ใช้วันที่ที่ GitHub เพิ่งเรียก
ถ้า Restart ระหว่าง Query งานที่ไม่จบจะแจ้ง error ไม่ค้างว่า Running
journal สถานะเก็บล่าสุด 200 งาน; ประวัติรายชื่อ/Attendance รายวันไม่ถูกลบจากการ Deploy

GitHub workflow — ต้องอัปเดตครั้งนี้
.gitHub ไม่ใช่ชื่อที่ถูก ต้อง .github/workflows/attendance-auto-query.yml ตัวพิมพ์เล็ก
อัปเดตไฟล์เดิม ไม่สร้างอีกไฟล์เพื่อให้ schedule ซ้ำกัน
คง cron ทุก 5 นาที และ concurrency group เดิม
เพิ่มการส่ง token ในการเริ่ม AUTO พร้อม slot_key/slot_date และชนิด trigger
Server อ่าน work_date จากงานที่อ้างอิง จึงตรวจวันถูกแม้ GitHub delay ข้ามวัน
เปิด Python log แบบ unbuffered เพื่อให้เวลากับ progress อ่านง่าย
คง Secret / URL / ค่าใช้จ่ายบริการเดิม; ไม่มีคำสั่งสร้างบริการ paid
ระหว่างอัปเดตอย่าสั่ง Query ซ้ำ และรอ workflow รอบก่อนจบก่อนเปลี่ยนโค้ด
GitHub รองรับการเริ่มล่าช้าและอาจข้ามบางรอบเมื่อโหลดสูง; ไม่รับประกันเริ่มทุก 5 นาทีเป๊ะ
แถบใหม่ทำให้แยกเหตุช้าได้ ไม่ใช่การรับประกันให้เริ่มตรงวินาที

ตรวจหลัง Deploy
- ดูชื่อรุ่น + /api/health
- เปิด Settings แต่ละแผนก ตรวจเวลาเดิมและวัน ON/OFF
- เลือกช่วง ดูวันที่แล้ว Query; Last Day ที่ไม่มี snapshot จะถูกบล็อกแทนการเดา
- สร้างรอบทดสอบล่วงหน้า 5–10 นาที Save แล้วไม่กด Run workflow
- ดู GitHub event schedule และแถบ AUTO • Scheduled
- เปลี่ยนกะผ่าน Excel Preview ตามปกติ; วันก่อนที่บันทึกไว้ต้องยังอยู่
- Backup ก่อนทดลองและเก็บไฟล์พนักงานเป็นส่วนตัว

Backup/สิทธิ์/ข้อจำกัด
BACKUP ALL DEPARTMENTS รวม snapshots, results, schedule profiles/rules และ journal/timed-run สำหรับ audit
Import / Recover เดิมเป็น add-missing-only ไม่ทับข้อมูลใหม่ และไม่เริ่มงานใน journal ใหม่จาก backup
หากโปรไฟล์ Schedule ของแผนกมีอยู่แล้ว จะไม่ทับอัตโนมัติ ให้ Maintain เวลาหลังตรวจ Preview
ประวัติอัปโหลด 20 รอบเดิมยังอยู่ โดย Backup ก่อนอัปโหลดรวม archive ที่มีในขณะนั้น
ฐานข้อมูล Free มีโควตา: ให้ IT จัดการระยะเก็บข้อมูลและสำรอง ไม่ได้สร้างการลบประวัติอัตโนมัติ
ใช้ 1 Render instance / 1 Gunicorn worker ตาม Dockerfile เดิม; ไม่รองรับขยายหลาย worker โดยไม่ปรับคิวเพิ่ม
คงสิทธิ์/ทางเข้าเดิม ไม่ได้เพิ่มบัญชีรายแผนกหรือแก้ auth ทั้งระบบ ให้ IT จำกัดการเข้าถึงข้อมูลพนักงาน
ห้ามใส่ DATABASE_URL/รหัสผ่าน/Backup/Excel พนักงานขึ้น GitHub

การทดสอบชุดนี้
125 pytest tests: SQLite จริง + route test double + parser/master tests
Chromium: 390x844 / 1366x900, mocked fetch เชื่อม route test double + SQLite
จำลอง browser timezone America/Los_Angeles แล้วยังแสดง 29/09/2026 08:30 เวลาไทย
ทดสอบ 4 tabs, Save/Unsaved, แถบ AUTO, เวลาช้า, ปุ่มกันซ้ำ, mobile overflow
ไม่ใช่การทดสอบ Flask deployment/จริง PostgreSQL/Supabase/Render/MIS/iPhone Safari
ระบบภายนอกยังไม่ถูกแก้ไขหรือ Deploy โดยการสร้างไฟล์นี้

แหล่งอ้างอิงแพลตฟอร์ม
https://docs.python.org/3/library/zoneinfo.html
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
https://render.com/docs/free
