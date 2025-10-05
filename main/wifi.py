import time, json, os
import network
import ubinascii
from machine import WDT, Timer

CONFIG_DIR = "/config"
CONFIG_PATH = CONFIG_DIR + "/wifi.json"

class WiFiManager:
    def __init__(self, config_path=CONFIG_PATH):
        self.config_path = config_path
        self.sta = network.WLAN(network.STA_IF)
        self.ap  = network.WLAN(network.AP_IF)
        self._last_try_ms = 0
        self._wdt = None
        self._timer = None
        self._tz_offset = 0  # seconds

    # ---------- Config ----------
    def _ensure_config_dir(self):
        try:
            os.mkdir(CONFIG_DIR)
        except OSError:
            pass

    def load_config(self):
        try:
            with open(self.config_path, "r") as f:
                return json.load(f)
        except Exception:
            return {}

    def save_config(self, ssid, password, hostname=None):
        self._ensure_config_dir()
        data = {"ssid": ssid, "password": password}
        if hostname:
            data["hostname"] = hostname
        with open(self.config_path, "w") as f:
            json.dump(data, f)

    # ---------- Info ----------
    def mac(self):
        self.sta.active(True)
        mac = self.sta.config("mac")
        return ubinascii.hexlify(mac, ":").decode().upper()

    def ip_info(self):
        if self.sta.isconnected():
            ip, mask, gw, dns = self.sta.ifconfig()
            return {"ip": ip, "mask": mask, "gw": gw, "dns": dns}
        return {}

    # ---------- STA ----------
    def connect(self, ssid, password, timeout=10, hostname=None, wait=False):
        # stop AP if running
        if self.ap.active():
            self.ap.active(False)

        self.sta.active(True)

        # hostname (บางพอร์ตไม่รองรับ)
        try:
            if hostname:
                self.sta.config(dhcp_hostname=hostname)
        except Exception:
            pass

        if not self.sta.isconnected():
            try:
                self.sta.connect(ssid, password)
            except Exception as e:
                print("[WiFi] connect start error:", e)
                return False

        if not wait:
            return self.sta.isconnected()

        t0 = time.ticks_ms()
        try:
            while not self.sta.isconnected() and time.ticks_diff(time.ticks_ms(), t0) < timeout * 1000:
                time.sleep_ms(100)
        except KeyboardInterrupt:
            print("[WiFi] connect wait cancelled")
            return False

        return self.sta.isconnected()

    def wait_connected(self, timeout=20):
        t0 = time.ticks_ms()
        while not self.sta.isconnected() and time.ticks_diff(time.ticks_ms(), t0) < timeout * 1000:
            time.sleep_ms(200)
        return self.sta.isconnected()

    def disconnect(self):
        try:
            self.sta.disconnect()
        except Exception:
            pass
        self.sta.active(False)

    # ---------- AP (fallback/config mode) ----------
    def start_ap(self, ssid=None, password="12345678", channel=6, hidden=False):
        if not ssid:
            mac = self.mac().replace(":", "")
            ssid = "ESP32-" + mac[-4:]
        self.ap.active(True)
        try:
            authmode = network.AUTH_WPA_WPA2_PSK if password else network.AUTH_OPEN
        except AttributeError:
            authmode = 3 if password else 0  # บางพอร์ตไม่มีคอนสแตนต์
        self.ap.config(essid=ssid, password=password, channel=channel, authmode=authmode, hidden=hidden)
        return ssid

    def stop_ap(self):
        self.ap.active(False)

     # ---------- Scan ----------
    def scan(self, retries=3, backoff_ms=250, aggressive=False):
        """
        สแกนเครือข่ายรอบตัวให้ทนทานขึ้น
        - aggressive=True : ปิด AP ชั่วคราว ระหว่างสแกน (ช่วยบอร์ด/เฟิร์มแวร์ที่สแกนพร้อม AP ไม่ได้)
        """
        nets = []
        ap_was_on = self.ap.active()
        try:
            if aggressive and ap_was_on:
                # ปิด AP ชั่วคราว เพื่อกันชนกับฮาร์ดแวร์/เฟิร์มแวร์บางรุ่น
                self.ap.active(False)
                time.sleep_ms(100)

            self.sta.active(True)
            try:
                # บางพอร์ตจำเป็นต้อง disconnect ก่อน scan ไม่งั้น EBUSY/ลิสต์ว่าง
                self.sta.disconnect()
            except Exception:
                pass
            time.sleep_ms(50)

            last_err = None
            for i in range(retries):
                try:
                    nets = self.sta.scan()  # blocking ~2s
                    break
                except OSError as e:
                    # ส่วนมากจะเป็น EBUSY: ไป toggle STA แล้วลองใหม่
                    last_err = e
                    try:
                        self.sta.active(False)
                        time.sleep_ms(50)
                        self.sta.active(True)
                        time.sleep_ms(backoff_ms)
                    except Exception:
                        time.sleep_ms(backoff_ms)

            # แปลงผลลัพธ์
            result = []
            for ssid, bssid, ch, rssi, auth, hidden in (nets or []):
                try:
                    ssid = ssid.decode()
                except Exception:
                    pass
                result.append({
                    "ssid": ssid,
                    "channel": ch,
                    "rssi": rssi,
                    "secure": auth != 0,
                    "hidden": bool(hidden),
                })
            result.sort(key=lambda x: x["rssi"], reverse=True)
            return result

        finally:
            # เปิด AP กลับถ้าเราปิดไป
            if aggressive and ap_was_on and not self.ap.active():
                try:
                    self.ap.active(True)
                except Exception:
                    pass

    # ---------- Auto connect ----------
    def auto_connect(self, timeout=8, start_ap_if_fail=True, ap_password="12345678", hostname=None, wait=False):
        cfg = self.load_config()
        ssid = cfg.get("ssid")
        pwd  = cfg.get("password")
        host = hostname or cfg.get("hostname")

        if ssid and pwd:
            ok = self.connect(ssid, pwd, timeout=timeout, hostname=host, wait=wait)
            if ok:
                return True

        if start_ap_if_fail and not self.ap.active():
            ap_ssid = self.start_ap(password=ap_password)
            print("[WiFi] Failed to connect. AP started:", ap_ssid)
        return self.sta.isconnected()

    # ---------- Keepalive ----------
    def keepalive(self, retry_interval_sec=12):
        now = time.ticks_ms()
        if self.sta.active() and not self.sta.isconnected():
            if time.ticks_diff(now, self._last_try_ms) > retry_interval_sec * 1000:
                self._last_try_ms = now
                cfg = self.load_config()
                if cfg.get("ssid") and cfg.get("password"):
                    try:
                        print("[WiFi] Reconnecting ...")
                        self.sta.connect(cfg["ssid"], cfg["password"])
                    except Exception as e:
                        print("[WiFi] reconnect error:", e)

    # ---------- NTP ----------
    def ntp_sync(self, host="pool.ntp.org", tz_offset_hours=0, retries=3, delay_sec=2):
        try:
            import ntptime
        except Exception as e:
            print("[NTP] ntptime not available:", e)
            return False

        ntptime.host = host
        for i in range(retries):
            try:
                ntptime.settime()  # set RTC to UTC
                self._tz_offset = int(tz_offset_hours) * 3600
                print("[NTP] synced via", host, "tz_offset(s)=", self._tz_offset)
                return True
            except Exception as e:
                print("[NTP] retry", i+1, "err:", e)
                time.sleep(delay_sec)
        return False

    def localtime(self):
        t = time.time() + self._tz_offset
        return time.localtime(t)

    # ---------- Watchdog + Timer ----------
    def start_watchdog(self, timeout_ms=15000, feed_every_ms=3000, timer_id=None):
        if self._wdt is None:
            self._wdt = WDT(timeout=timeout_ms)

        if self._timer is not None:
            try:
                self._timer.deinit()
            except Exception:
                pass
            self._timer = None

        # ลำดับความพยายามเลือก Timer id
        if timer_id is not None:
            candidates = [timer_id]
        else:
            candidates = [0, 1, 2, 3, -1]  # เริ่มจาก 0 ก่อน (พอร์ตส่วนมากรองรับ)

        last_err = None
        for tid in candidates:
            try:
                t = Timer(tid)
                def _cb(_):
                    try:
                        self.keepalive(retry_interval_sec=10)
                        if (self.sta.active() and self.sta.isconnected()) or self.ap.active():
                            self._wdt.feed()
                    except Exception:
                        pass
                t.init(period=feed_every_ms, mode=Timer.PERIODIC, callback=_cb)
                self._timer = t
                print("[WDT] started:", timeout_ms, "ms; feed", feed_every_ms, "ms; timer_id=", tid)
                return True
            except Exception as e:
                last_err = e
                continue

        print("[WDT] cannot start Timer; last error:", last_err)
        print("[WDT] Watchdog disabled (no valid Timer).")
        return False

    def stop_watchdog(self):
        if self._timer:
            try:
                self._timer.deinit()
            except Exception:
                pass
            self._timer = None
        self._wdt = None
        print("[WDT] stopped")
# ==== เพิ่มข้างล่างนี้ในไฟล์ wifi.py ====
try:
    import uasyncio as asyncio
except Exception as _e:
    asyncio = None  # กันไว้กรณีเฟิร์มแวร์ไม่มี uasyncio

import ure  # สำหรับ url-decode

# HTML หน้า config แบบเรียบง่าย
HTML_INDEX = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>ESP32 WiFi Setup</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <style>
    body{font-family:system-ui,Segoe UI,Roboto,Arial;max-width:560px;margin:24px auto;padding:0 12px}
    h1{font-size:1.25rem} .card{border:1px solid #ddd;border-radius:12px;padding:16px;margin-top:12px}
    input,button{width:100%;padding:10px;margin:6px 0;border:1px solid #ccc;border-radius:10px}
    .row{display:flex;gap:8px} .row>div{flex:1}
    ul{padding-left:16px} small{color:#666}
  </style>
</head>
<body>
  <h1>ESP32 WiFi Setup</h1>
  <div class="card">
    <form id="f">
      <label>SSID</label>
      <input id="ssid" name="ssid" placeholder="Wi-Fi SSID" required>
      <label>Password</label>
      <input id="password" name="password" type="password" placeholder="Wi-Fi password" required>
      <label>Hostname (optional)</label>
      <input id="hostname" name="hostname" placeholder="esp32-device">
      <button type="submit">Save & Connect</button>
    </form>
    <div id="msg"></div>
  </div>

  <div class="card">
    <div class="row">
      <div><button id="btn-scan" type="button">Scan networks</button></div>
    </div>
    <ul id="nets"></ul>
    <small>คลิก SSID เพื่อกรอกอัตโนมัติ</small>
  </div>
  
  <button id="btn-ota">Check OTA</button>
    <script>
    document.getElementById('btn-ota').onclick = async ()=>{
      const r = await fetch('/ota/check', {method:'POST'});
      const j = await r.json();
      alert(JSON.stringify(j));
      if (j.ok) location.reload();
    };
    </script>

<script>
async function scan(){
  document.getElementById('nets').innerHTML = "<li>Scanning...</li>";
  try{
    const r = await fetch('/scan'); const j = await r.json();
    const ul = document.getElementById('nets'); ul.innerHTML = "";
    j.forEach(n=>{
      const li = document.createElement('li');
      li.style.cursor = 'pointer';
      li.textContent = `${n.ssid}  (RSSI ${n.rssi}) ${n.secure?'🔒':''}`;
      li.onclick = ()=>{ document.getElementById('ssid').value = n.ssid; };
      ul.appendChild(li);
    });
  }catch(e){
    document.getElementById('nets').innerHTML = "<li>Scan error</li>";
  }
}
document.getElementById('btn-scan').onclick = scan;

document.getElementById('f').onsubmit = async (ev)=>{
  ev.preventDefault();
  const fd = new FormData(document.getElementById('f'));
  const body = new URLSearchParams(fd).toString();
  const r = await fetch('/save', {method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body});
  const j = await r.json();
  const msg = document.getElementById('msg');
  msg.innerHTML = `<pre>${JSON.stringify(j,null,2)}</pre>`;
};
</script>
</body>
</html>
"""

# —— ใส่เมธอดเหล่านี้ “ภายในคลาส WiFiManager” จะสะดวกกว่า ——
# ถ้าอยากใส่นอกคลาสก็ได้ แต่ด้านล่างสมมุติว่าเราเพิ่มเข้าไปในคลาสเดิม:

def _wm_add_portal_methods_to(cls):
    # urldecode + parse form
    def _urldecode(self, s):
        s = s.replace("+", " ")
        return ure.sub("%([0-9A-Fa-f]{2})", lambda m: chr(int(m.group(1), 16)), s)

    def _parse_form(self, body):
        out = {}
        for kv in body.split("&"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                out[self._urldecode(k)] = self._urldecode(v)
        return out

    async def _send(self, w, raw):
        await w.awrite(raw)

    async def _send_html(self, w, html):
        hdr = "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nCache-Control: no-store\r\n\r\n"
        await w.awrite(hdr + html)

    async def _send_json(self, w, obj):
        s = json.dumps(obj)
        hdr = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nCache-Control: no-store\r\n\r\n"
        await w.awrite(hdr + s)

    async def _handle_client(self, r, w):
        try:
            data = await r.read(1024)
            req = data.decode("utf-8", "ignore")
            first = req.split("\r\n", 1)[0]
            parts = first.split(" ")
            method = parts[0] if len(parts) > 0 else "GET"
            path   = parts[1] if len(parts) > 1 else "/"

            if method == "GET" and path == "/":
                await self._send_html(w, HTML_INDEX)

            elif method == "GET" and path == "/scan":
                try:
                    # โหมดรุนแรง: ปิด AP ชั่วคราวถ้าจำเป็น แล้วสแกน
                    nets = self.scan(retries=3, aggressive=True)
                    await self._send_json(w, nets)
                except Exception as e:
                    await self._send_json(w, {"error": str(e), "nets": []})
            elif method == "GET" and path == "/sysinfo":
                import myos
                await self._send_json(w, myos.get_info())

            elif method == "POST" and path == "/save":
                body = req.split("\r\n\r\n", 1)[1] if "\r\n\r\n" in req else ""
                form = self._parse_form(body)
                ssid = form.get("ssid", "")
                pwd  = form.get("password", "")
                hostname = form.get("hostname") or None
                ok = False
                msg = "missing ssid/password"
                if ssid and pwd:
                    self.save_config(ssid, pwd, hostname=hostname)
                    ok = self.connect(ssid, pwd, timeout=10, hostname=hostname, wait=True)
                    msg = "connected" if ok else "connect failed"
                await self._send_json(w, {"ok": ok, "message": msg, "ip": self.ip_info(), "ssid": ssid})
            elif method == "POST" and path == "/ota/check":
                from app.ota_updater import OTAUpdater
                headers = {
                    b"Accept": b"application/vnd.github+json",
                    b"X-GitHub-Api-Version": b"2022-11-28",
                }
                o = OTAUpdater(
                    github_repo="Tatonq/esp32-home",
                    main_dir="main", 
                    new_version_dir="next",
                    headers=headers
                )
                ok = False
                try:
                    ok = o.check_for_update_to_install_during_next_reboot()
                except Exception as e:
                    await self._send_json(w, {"ok": False, "error": str(e)})
                else:
                    await self._send_json(w, {"ok": ok, "message": "reboot to install" if ok else "no update"})
            else:
                await self._send(w, "HTTP/1.1 404 Not Found\r\n\r\n")
        except Exception as e:
            try:
                await self._send(w, "HTTP/1.1 500 Internal Server Error\r\n\r\n")
            except Exception:
                pass
        finally:
            try:
                await w.aclose()
            except Exception:
                pass

    async def start_config_portal(self, ap_password="12345678", port=80):
        """
        เปิด AP (ถ้ายังไม่เปิด) แล้วเริ่มเว็บเซิร์ฟเวอร์:
          - GET /      -> หน้า HTML กรอก SSID/PASSWORD/Hostname
          - GET /scan  -> JSON รายชื่อ Wi-Fi รอบข้าง
          - POST /save -> บันทึก + ลองเชื่อมต่อ
        """
        if asyncio is None:
            print("[Portal] uasyncio not available on this firmware")
            return None

        if not self.ap.active():
            ap_ssid = self.start_ap(password=ap_password)
            print("[Portal] AP started:", ap_ssid)

        srv = await asyncio.start_server(self._handle_client, "0.0.0.0", port)
        print("[Portal] HTTP on 0.0.0.0:%d" % port)
        return srv

    # bind methods to class
    cls._urldecode = _urldecode
    cls._parse_form = _parse_form
    cls._send = _send
    cls._send_html = _send_html
    cls._send_json = _send_json
    cls._handle_client = _handle_client
    cls.start_config_portal = start_config_portal
    return cls

# ติดตั้งเมธอดลงใน WiFiManager
WiFiManager = _wm_add_portal_methods_to(WiFiManager)
# ==== จบส่วนเพิ่ม ====
