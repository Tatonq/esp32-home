# main.py
from machine import Pin
import uasyncio as asyncio
import time
import wifi

led = Pin(2, Pin.OUT)
wm = wifi.WiFiManager()

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
        await wm.start_config_portal(ap_password="12345678", port=80)  # เปิดพอร์ทัลให้ตั้งค่า

    # (ออปชัน) Watchdog
    wm.start_watchdog(timeout_ms=15000, feed_every_ms=3000, timer_id=0)

    # Sync เวลาเมื่อออนไลน์
    synced = False
    while True:
        wm.keepalive(retry_interval_sec=8)
        if wm.sta.isconnected() and not synced:
            wm.ntp_sync(host="pool.ntp.org", tz_offset_hours=7)
            print("Localtime:", wm.localtime())
            synced = True
        await asyncio.sleep(1)

async def main():
    await asyncio.gather(blink(), caretaker())

asyncio.run(main())
