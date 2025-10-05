# main.py
from machine import Pin
import uasyncio as asyncio
import time
from wifi import WiFiManager
import myos
from app.ota_updater import OTAUpdater
from mqtt import MQTTManager
import gc


GITHUB_REPO   = "Tatonq/esp32-home"
o = OTAUpdater(github_repo=GITHUB_REPO, main_dir="main", new_version_dir="next")

led = Pin(2, Pin.OUT)
wm = WiFiManager()  # แทน wifi.WiFiManager()
mqtt = MQTTManager(server="localhost")  # เพิ่ม MQTT client

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
    mqtt_connected = False
    health_timer = 0
    sysinfo_timer = 0
    
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
        
        # MQTT management
        if wm.sta.isconnected():
            # เชื่อมต่อ MQTT ถ้ายังไม่ได้เชื่อมต่อ
            if not mqtt_connected:
                print("[MQTT] Attempting to connect...")
                mqtt_connected = mqtt.connect()
                if mqtt_connected:
                    # ส่ง initial status และ sysinfo
                    mqtt.publish_status("online", {"source": "boot"})
                    mqtt.publish_sysinfo()
            
            # ส่ง health ping ทุก 30 วินาที
            if mqtt_connected and health_timer >= 30:
                if not mqtt.keepalive():
                    mqtt_connected = False  # connection lost
                health_timer = 0
            
            # ส่ง sysinfo ทุก 5 นาที (300 วินาที)
            if mqtt_connected and sysinfo_timer >= 300:
                mqtt.publish_sysinfo()
                sysinfo_timer = 0
        else:
            # ไม่มี WiFi - ตัดการเชื่อมต่อ MQTT
            if mqtt_connected:
                mqtt.disconnect()
                mqtt_connected = False

        # เพิ่ม timer counters
        health_timer += 10
        sysinfo_timer += 10

        await asyncio.sleep(10)  # เช็กทุก 10 วิ

async def main():
    await asyncio.gather(blink(), caretaker())

asyncio.run(main())
