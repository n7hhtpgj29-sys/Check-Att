CAL-COMP Attendance iPhone PWA — Mobile Final v7 (Latest Only)

เวอร์ชันนี้ตัด Custom / Historical Date Query ออกจากมือถือแล้วตามการใช้งานจริง

ใช้งานหลัก:
- TODAY DAY = Query กะกลางวันของวันนี้
- LAST NIGHT = Query กะกลางคืนล่าสุดที่จบ/กำลังใช้สำหรับรายงาน
- TONIGHT = Query กะกลางคืนของคืนนี้
- RECHECK MISSING ONLY = Query ซ้ำเฉพาะพนักงานที่ยังไม่ Present จาก Query ล่าสุด

ไม่มีช่องเลือกวันที่ย้อนหลัง และ API จะปฏิเสธ Custom Date Query

Deploy: อัปโหลดไฟล์ทั้งหมดทับ Repo เดิมบน GitHub แล้ว Commit; Render Auto Deploy จะทำงานเอง
Health check: /api/health ต้องแสดง version 7.0-mobile-latest-only


V8 Mobile List Fix:
- Modal รายชื่อบน iPhone เปลี่ยนเป็น Card List
- Scroll ภายใน Modal ได้ครบทุกคน
- Modal อยู่เหนือ bottom navigation
- รองรับรายชื่อ 9, 20+ คนโดยไม่ตกขอบ
- Health version: 8.0-mobile-list-scroll-fix
