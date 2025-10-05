# This file is executed on every boot (including wake-boot from deepsleep)
#import esp
#esp.osdebug(None)
#import webrepl
#webrepl.start()
# boot.py
import sys, time
from app.ota_updater import OTAUpdater

# ตั้งค่ารีโปที่จะดึง OTA
GITHUB_REPO   = "Tatonq/esp32-home"   # ตัวอย่างจากลิงก์
GITHUB_SRC_DIR= ""                    # ถ้าโค้ดอยู่รากให้ว่าง, ถ้าอยู่โฟลเดอร์ย่อยใส่เช่น "src"
MODULE        = ""                    # ปล่อยว่าง = เขียนทับรากไฟล์ระบบ (โค้ด ota นี้รองรับ)
MAIN_DIR      = "main"                # ต้องตรงกับฝั่งรีโป
NEXT_DIR      = "next"

# สร้างอ็อบเจ็กต์ OTA (แนบ header ถ้ามี token)
try:
    import ujson
    with open('/config/github.json', 'r') as f:
        github_config = ujson.load(f)
    github_token = github_config.get('github_token', '')
    GITHUB_REPO = github_config.get('github_repo', 'Tatonq/esp32-home')
except:
    github_token = ''
    print("[OTA] No GitHub config found, using default settings")

headers = {
    b"Accept": b"application/vnd.github+json",
    b"X-GitHub-Api-Version": b"2022-11-28",
}

if github_token:
    headers[b"Authorization"] = f"Bearer {github_token}".encode()
    print("[OTA] Using GitHub token authentication")
else:
    print("[OTA] Warning: No GitHub token - private repos will not work")
o = OTAUpdater(
    github_repo=GITHUB_REPO,
    github_src_dir=GITHUB_SRC_DIR,
    module=MODULE,
    main_dir=MAIN_DIR,
    new_version_dir=NEXT_DIR,
    headers=headers
)

# 1) เช็คว่ามีไฟล์ next/.version ไหม -> ถ้ามีก็ติดตั้งเลย (ไม่ต้องต่อ WiFi ถ้าไม่ต้องโหลดเพิ่ม)
#    หรือใช้วิธีเบา ๆ: ตรวจมีไฟล์ next แล้วค่อยติดตั้ง
try:
    # ถ้ามีไฟล์เวอร์ชันแล้ว -> ติดตั้ง
    did = o.install_update_if_available_after_boot(ssid="", password="")
    if did:
        print("[OTA] Update installed, rebooting...")
        import machine
        machine.reset()
except Exception as e:
    print("[OTA] boot install error:", e)

# 2) เข้า main ของเรา
import main  # เพิ่มบรรทัดนี้
