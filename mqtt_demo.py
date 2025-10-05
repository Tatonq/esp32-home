# mqtt_demo.py - ตัวอย่างการใช้งาน MQTT module
from mqtt import MQTTManager
import time
import uasyncio as asyncio
import ujson

async def mqtt_demo():
    """ตัวอย่างการใช้งาน MQTT"""
    
    # สร้าง MQTT client
    mqtt = MQTTManager(
        server="mqtt.355746film.com",
        username=None,  # ใส่ username ถ้ามี
        password=None   # ใส่ password ถ้ามี
    )
    
    print("Device ID:", mqtt.device_id)
    print("Topics:")
    print(f"  Status: {mqtt.status_topic}")
    print(f"  Health: {mqtt.health_topic}")
    print(f"  Sysinfo: {mqtt.sysinfo_topic}")
    
    # เชื่อมต่อ MQTT
    if not mqtt.connect():
        print("Failed to connect to MQTT")
        return
    
    try:
        # ส่ง status ต่างๆ
        await asyncio.sleep(1)
        mqtt.publish_status("working", {"task": "initialization"})
        
        await asyncio.sleep(2)
        mqtt.publish_status("idle")
        
        # ส่ง sysinfo
        await asyncio.sleep(1)
        mqtt.publish_sysinfo()
        
        # ส่ง health updates
        for i in range(5):
            await asyncio.sleep(5)
            mqtt.keepalive()  # ส่ง health ping
            print(f"Health ping {i+1}/5")
        
        # ส่ง status เมื่อจบงาน
        mqtt.publish_status("completed", {"demo": "finished"})
        
    except KeyboardInterrupt:
        print("Demo interrupted")
    except Exception as e:
        print(f"Demo error: {e}")
    finally:
        # ตัดการเชื่อมต่อ
        mqtt.disconnect()

# รันถ้าเรียกไฟล์นี้โดยตรง
if __name__ == "__main__":
    asyncio.run(mqtt_demo())