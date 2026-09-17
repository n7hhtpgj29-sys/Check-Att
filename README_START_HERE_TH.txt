CC Attendance Mobile FINAL v6
=============================

เวอร์ชันนี้สำหรับ Deploy บน Render แล้วใช้งานเป็น PWA บน iPhone

จุดสำคัญ
- Query Cal-Comp ผ่าน Cloud ด้วย Chromium แบบ headed + Xvfb
- Recheck Missing Only ไม่ Query คนที่ Present แล้วซ้ำ
- Employee Master สำรองลง localStorage ของ iPhone อัตโนมัติ
- ถ้า Render Free restart และฐานข้อมูลหาย แอปจะ Restore Employee Master จาก iPhone อัตโนมัติ
- มี Backup / Restore / Export JSON / Import JSON ในหน้า Master
- Auto Recheck Missing ปิดไว้เป็นค่าเริ่มต้น เปิดได้จาก Settings
- ป้องกัน Query ซ้อนพร้อมกัน
- Region: Singapore / Timezone: Asia/Bangkok

วิธีอัปเดต
1) Upload ไฟล์ทั้งหมดใน ZIP นี้ทับไฟล์เดิมใน GitHub repository
2) Commit changes
3) Render จะ Auto Deploy
4) รอ Deploy เป็น Live
5) เปิด https://cc-attendance-iphone-pwa.onrender.com/api/health
   version ควรเป็น 6.0-mobile-final
6) เปิดหน้า PWA แล้วทดสอบ TODAY DAY

การติดตั้งบน iPhone
Safari > Share > Add to Home Screen

หมายเหตุ Render Free
- Server อาจ sleep เมื่อไม่มีการใช้งาน และไฟล์ SQLite ใน server ไม่ใช่ persistent disk
- v6 จึงสำรอง Employee Master ไว้ใน iPhone และ restore ให้อัตโนมัติเมื่อ server master ว่าง
- ควรกด Master > BACKUP TO IPHONE หลังแก้รายชื่อสำคัญ (ระบบจะ backup อัตโนมัติด้วย)
