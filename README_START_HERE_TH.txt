CC Attendance Multi Department V11 — Maintainable Auto Query

CAL-COMP Attendance & Manpower — Multi Department v10 + Auto Query
======================================================

แนวคิดหลัก
- ใช้ Render Server / URL เดียวกัน
- แยกข้อมูลตาม Department เช่น PE / QA / MFG / IT
- แต่ละ Department มี Employee Master, Day/Night Query, Backup และ Recheck Missing ของตัวเอง
- Dashboard สามารถเลือก ALL DEPARTMENTS เพื่อดูภาพรวมได้ แต่การ Query ต้องเลือก Department เดียวก่อนเสมอ

การอัปเกรดจาก v8
1) อัปโหลดไฟล์ v9 ทับไฟล์เดิมใน GitHub แล้ว Commit
2) Render จะ Auto Deploy
3) เปิด /api/health ต้องเห็น version = 9.0-multi-department
4) Employee Master เดิมที่ department ว่าง จะถูกย้ายเป็น PE อัตโนมัติ
5) เพิ่ม Department ใหม่ด้วยปุ่ม + DEPARTMENT
6) เลือก Department แล้ว Upload Employee Master ของแผนกนั้น
   - ไฟล์ Excel ไม่ต้องมีคอลัมน์ department
   - ระบบจะผูกทั้งไฟล์กับ Department ที่เลือก
   - การ Upload PE จะไม่ปิด/ลบพนักงาน QA, MFG, IT

Sorting Table
- กดหัวคอลัมน์เพื่อเรียง Ascending / Descending
- Quick Sort: Default / No Scan First / Present First / Scan In Latest
- Sorting ทำเฉพาะข้อมูลที่กำลัง Filter อยู่

Backup บน iPhone
- Backup ถูกแยกตาม Department
- PE backup ไม่สามารถ overwrite QA master ได้
- ถ้า Render Free restart ให้เปิด Department นั้นจาก iPhone ที่มี backup เพื่อ restore เฉพาะแผนก

ข้อควรทราบ
- Render Free ใช้ SQLite แบบชั่วคราว ข้อมูลอาจหายเมื่อ service restart/deploy
- ถ้าจะใช้หลาย Department แบบ production จริง แนะนำย้ายฐานข้อมูลไป PostgreSQL/Persistent DB ใน version ถัดไป
- v9 ยังไม่ได้ใส่ Login/Role permission ดังนั้นผู้ที่เข้าถึง URL สามารถเลือก Department ได้ทั้งหมด

Health check
https://<your-render-url>/api/health
Expected: "version": "9.0-multi-department"


V11 Auto Query
- 08:15 Today Day
- 18:00 Today Day
- 20:15 Tonight
- 06:00 Last Night final check
- ทำงานผ่าน .github/workflows/attendance-auto-query.yml
- ไม่ต้องเปิด iPhone ค้างไว้
