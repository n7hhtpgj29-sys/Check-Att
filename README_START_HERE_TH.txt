CC Attendance iPhone PWA Cloud FIX v3

แก้ Query บน Render:
- ใช้ Chromium แบบ headed เหมือนเวอร์ชัน PC ที่ Query ได้
- รัน Chromium ผ่าน Xvfb บน Linux/Render
- เพิ่ม browser anti-automation compatibility
- เพิ่ม log สำหรับตรวจสาเหตุ Query fail
- ตั้ง timezone Asia/Bangkok
- Render plan = free

ให้อัปโหลดไฟล์ทั้งหมดทับไฟล์เดิมใน GitHub repo แล้ว Commit
Render จะ Auto Deploy ให้เอง
หลัง Deploy เสร็จ เปิด /api/health ต้องเห็น version 5.1-iphone-pwa-cloud-headed และ headless:false
