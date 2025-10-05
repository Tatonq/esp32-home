# mqtt.py - MQTT client module for ESP32
import ujson
import time
import machine
from umqtt.simple import MQTTClient
import ubinascii
import gc

class MQTTManager:
    """
    MQTT Manager สำหรับ ESP32
    รองรับการส่ง status, health, และ sysinfo
    """
    
    def __init__(self, server="localhost", port=1883, username=None, password=None, keepalive=60):
        self.server = server
        self.port = port
        self.username = username
        self.password = password
        self.keepalive = keepalive
        self.client = None
        self.connected = False
        
        # สร้าง unique client ID และ device serial
        self.device_id = ubinascii.hexlify(machine.unique_id()).decode()
        self.client_id = f"esp32_{self.device_id}"
        
        # Topic prefixes
        self.topic_prefix = f"esp/{self.device_id}"
        self.status_topic = f"{self.topic_prefix}/status"
        self.health_topic = f"{self.topic_prefix}/health"
        self.sysinfo_topic = f"{self.topic_prefix}/sysinfo"
        
        print(f"[MQTT] Device ID: {self.device_id}")
        print(f"[MQTT] Client ID: {self.client_id}")
    
    def connect(self):
        """เชื่อมต่อ MQTT broker"""
        try:
            self.client = MQTTClient(
                client_id=self.client_id,
                server=self.server,
                port=self.port,
                user=self.username,
                password=self.password,
                keepalive=self.keepalive
            )
            
            self.client.connect()
            self.connected = True
            print(f"[MQTT] Connected to {self.server}:{self.port}")
            
            # ส่ง initial health status
            self.publish_health("online")
            return True
            
        except Exception as e:
            print(f"[MQTT] Connection failed: {e}")
            self.connected = False
            return False
    
    def disconnect(self):
        """ตัดการเชื่อมต่อ MQTT"""
        if self.client and self.connected:
            try:
                # ส่ง offline status ก่อนตัดการเชื่อมต่อ
                self.publish_health("offline")
                self.client.disconnect()
                print("[MQTT] Disconnected")
            except Exception as e:
                print(f"[MQTT] Disconnect error: {e}")
            finally:
                self.connected = False
                self.client = None
    
    def is_connected(self):
        """เช็คสถานะการเชื่อมต่อ"""
        return self.connected and self.client is not None
    
    def publish(self, topic, message, retain=False):
        """ส่งข้อความไป MQTT topic"""
        if not self.is_connected():
            print("[MQTT] Not connected, cannot publish")
            return False
        
        try:
            if isinstance(message, dict):
                message = ujson.dumps(message)
            elif not isinstance(message, (str, bytes)):
                message = str(message)
                
            self.client.publish(topic, message, retain=retain)
            print(f"[MQTT] Published to {topic}: {message}")
            return True
            
        except Exception as e:
            print(f"[MQTT] Publish error: {e}")
            self.connected = False
            return False
    
    def publish_status(self, status, data=None):
        """
        ส่งสถานะการทำงานของอุปกรณ์
        status: "working", "idle", "error", "maintenance", etc.
        data: ข้อมูลเพิ่มเติม (optional)
        """
        payload = {
            "status": status,
            "timestamp": time.time(),
            "device_id": self.device_id
        }
        
        if data:
            payload["data"] = data
            
        return self.publish(self.status_topic, payload, retain=True)
    
    def publish_health(self, state="online"):
        """
        ส่งสถานะ health ของอุปกรณ์
        state: "online", "offline", "rebooting", etc.
        """
        payload = {
            "state": state,
            "timestamp": time.time(),
            "device_id": self.device_id,
            "uptime": time.ticks_ms() // 1000  # uptime in seconds
        }
        
        return self.publish(self.health_topic, payload, retain=True)
    
    def publish_sysinfo(self, sysinfo_data=None):
        """
        ส่งข้อมูลระบบ
        sysinfo_data: dict ข้อมูลระบบ หรือ None เพื่อใช้ myos.collect_info_dict()
        """
        try:
            if sysinfo_data is None:
                # ใช้ myos module ถ้ามี
                try:
                    import myos
                    sysinfo_data = myos.collect_info_dict()
                except ImportError:
                    # fallback ถ้าไม่มี myos
                    sysinfo_data = self._get_basic_sysinfo()
            
            payload = {
                "device_id": self.device_id,
                "timestamp": time.time(),
                "sysinfo": sysinfo_data
            }
            
            return self.publish(self.sysinfo_topic, payload, retain=True)
            
        except Exception as e:
            print(f"[MQTT] Sysinfo publish error: {e}")
            return False
    
    def _get_basic_sysinfo(self):
        """ข้อมูลระบบพื้นฐานถ้าไม่มี myos module"""
        try:
            import os
            import esp32
            
            return {
                "platform": "ESP32",
                "device_id": self.device_id,
                "freq": machine.freq(),
                "temp": esp32.raw_temperature(),
                "flash_size": esp32.flash_size(),
                "uptime_ms": time.ticks_ms(),
                "free_memory": gc.mem_free(),
                "allocated_memory": gc.mem_alloc()
            }
        except Exception as e:
            return {
                "device_id": self.device_id,
                "error": f"Cannot collect sysinfo: {e}"
            }
    
    def keepalive(self):
        """รักษาการเชื่อมต่อ MQTT และส่ง health ping"""
        if not self.is_connected():
            return False
        
        try:
            # ส่ง health ping
            self.publish_health("online")
            
            # Check messages (รองรับ callback ในอนาคต)
            self.client.check_msg()
            return True
            
        except Exception as e:
            print(f"[MQTT] Keepalive error: {e}")
            self.connected = False
            return False
    
    def reconnect(self):
        """พยายามเชื่อมต่อใหม่"""
        if self.connected:
            return True
            
        print("[MQTT] Attempting to reconnect...")
        return self.connect()

    def publish_version(self, version, source="ota"):
        """ส่งข้อมูลเวอร์ชั่นปัจจุบัน"""
        if not self.client:
            return False
        
        topic = f"esp/{self.device_id}/version"
        data = {
            "device_id": self.device_id,
            "timestamp": time.time(),
            "version": version,
            "source": source  # "ota", "boot", "manual"
        }
        
        try:
            payload = json.dumps(data)
            self.client.publish(topic, payload)
            print(f"[MQTT] Published version: {version}")
            return True
        except Exception as e:
            print(f"[MQTT] Publish version error: {e}")
            return False

# สร้าง global instance (optional)
# mqtt_client = None

def get_mqtt_client(server="localhost", username=None, password=None):
    """Factory function สำหรับสร้าง MQTT client"""
    return MQTTManager(server=server, username=username, password=password)