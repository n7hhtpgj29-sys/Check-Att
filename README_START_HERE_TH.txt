CC Attendance – iPhone PWA / Cloud Version
===========================================

ไฟล์ ZIP นี้เป็น SOURCE CODE สำหรับอัปโหลดขึ้น GitHub และ Deploy บน Render
ไม่ใช่ไฟล์ที่แตะแล้วติดตั้งบน iPhone โดยตรง

หลังแตก ZIP ต้องเห็นไฟล์เหล่านี้ทันที:
- app.py
- Dockerfile
- render.yaml
- requirements.txt
- start.sh
- templates/
- static/
- data/

ขั้นตอน:
1) แตก ZIP ในแอป Files ของ iPhone
2) เปิดโฟลเดอร์ที่แตกแล้ว และตรวจว่ามี app.py อยู่ระดับแรก
3) อัปโหลด 'ไฟล์และโฟลเดอร์ทั้งหมดข้างใน' ไปที่ root ของ GitHub repository
   อย่าอัปโหลด ZIP ทั้งก้อน และอย่าให้มีโฟลเดอร์ซ้อนอีกชั้น
4) ใน Render เลือก New > Blueprint แล้วเลือก GitHub repository
5) Render จะอ่าน render.yaml และ Deploy
6) เมื่อสถานะ Live จะได้ URL https://...onrender.com
7) เปิด URL ด้วย Safari > Share > Add to Home Screen

โครงสร้างการทำงาน:
iPhone PWA -> HTTPS Render Cloud -> Cal-Comp Attendance Web

หมายเหตุ:
- README รุ่น PC/EXE ถูกเอาออกจากชุดนี้แล้ว เพื่อไม่ให้สับสน
- Cloud version ไม่ต้องเปิด AttendanceDashboard.exe และไม่ใช้ 127.0.0.1:5000
