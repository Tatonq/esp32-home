# main.py
from machine import Pin
import uasyncio as asyncio
import time
from wifi import WiFiManager
import myos
from app.ota_updater import OTAUpdater
import gc


GITHUB_REPO   = "Tatonq/esp32-home"
o = OTAUpdater(github_repo=GITHUB_REPO, main_dir="main", new_version_dir="next")

led = Pin(2, Pin.OUT)
wm = WiFiManager()  # แทน wifi.WiFiManager()

updated = o.install_update_if_available()
if updated:
    import machine
    print("[OTA] Updated. Rebooting...")
    time.sleep(1)
    machine.reset()


async def blink():
    while True:
        if wm.sta.isconnected():
            led.on(); await asyncio.sleep(0.5)
            led.off(); await asyncio.sleep(0.5)
        else:
            led.on(); await asyncio.sleep(0.1)
            led.off(); await asyncio.sleep(0.1)

async def caretaker():
    ok = wm.auto_connect(wait=False, start_ap_if_fail=False, hostname="esp32-tatonq")
    if not ok:
        portal = await wm.start_config_portal(ap_password="12345678", port=80)
        if portal:
            print("[Portal] Config server started on port 80")

    # (ออปชัน) Watchdog
    wm.start_watchdog(timeout_ms=15000, feed_every_ms=3000, timer_id=0)

    synced = False
    print("[SYS] Initial system info:")
    myos.print_info()  # 🆕 แสดงข้อมูลระบบตอนเริ่มต้น

    while True:
        gc.collect()  # เพิ่ม
        wm.keepalive(retry_interval_sec=8)

        # sync เวลา เมื่อออนไลน์ครั้งแรก
        if wm.sta.isconnected() and not synced:
            wm.ntp_sync(host="pool.ntp.org", tz_offset_hours=7)
            print("Localtime:", wm.localtime())
            synced = True

            # ✅ แสดงข้อมูล client/เครื่องอีกครั้งเมื่อออนไลน์แล้ว
            print("\n[SYS] Connected info:")
            myos.print_info()

        await asyncio.sleep(10)  # เช็กทุก 10 วิ

async def main():
    await asyncio.gather(blink(), caretaker())

asyncio.run(main())
