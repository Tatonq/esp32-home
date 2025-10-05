# myos.py — Quick system introspection for MicroPython (ESP32/ESP32-S3)
# แสดงข้อมูลระบบ/OS/เน็ตเวิร์ก/ไฟล์ระบบ และพิมพ์เป็นบรรทัดสวย ๆ
try:
    import ujson as json
except Exception:
    import json

import os, sys, gc, time
import ubinascii
try:
    import machine
except Exception:
    machine = None

try:
    import network
except Exception:
    network = None


# ---------- helpers ----------
def _fmt_bytes(n):
    try:
        n = int(n)
    except Exception:
        return str(n)
    units = ["B", "KB", "MB", "GB"]
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n //= 1024
        i += 1
    return "{} {}".format(n, units[i])

def _uptime_tuple():
    ms = time.ticks_ms()
    s = ms // 1000
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return (int(d), int(h), int(m), int(s))

def _fs_info():
    try:
        st = os.statvfs("/")
        total = st[0] * st[2]
        free  = st[0] * st[3]
        used  = total - free
        return {"total": total, "used": used, "free": free}
    except Exception:
        return {}

def _wlan_info(kind="sta"):
    """kind: 'sta' | 'ap'"""
    if network is None:
        return {}
    iface = network.WLAN(network.STA_IF if kind == "sta" else network.AP_IF)
    try:
        active = iface.active()
    except Exception:
        active = False

    out = {"active": bool(active)}
    if not active:
        return out

    # MAC
    try:
        mac = iface.config("mac")
        out["mac"] = ubinascii.hexlify(mac, b":").decode().upper()
    except Exception:
        pass

    # IP
    try:
        ip, mask, gw, dns = iface.ifconfig()
        out.update({"ip": ip, "mask": mask, "gw": gw, "dns": dns})
    except Exception:
        pass

    # ESSID (AP) / hostname (STA)
    try:
        if kind == "ap":
            out["essid"] = iface.config("essid")
        else:
            # MicroPython บางเวอร์ชันรองรับ dhcp_hostname
            hn = None
            try:
                hn = iface.config("dhcp_hostname")
            except Exception:
                pass
            if hn:
                out["hostname"] = hn
    except Exception:
        pass

    # RSSI (ถ้าต่ออยู่)
    try:
        # บาง build ใช้ iface.status('rssi')
        rssi = None
        try:
            rssi = iface.status("rssi")
        except Exception:
            # บางตัวไม่มี method นี้
            rssi = None
        if isinstance(rssi, int):
            out["rssi"] = rssi
    except Exception:
        pass

    return out


# ---------- core collectors ----------
def collect_info_dict():
    lines = {}

    # Python / firmware
    try:
        lines["sys_version"] = sys.version
    except Exception:
        pass

    try:
        lines["mp_version"] = sys.implementation._machine if hasattr(sys.implementation, "_machine") else str(sys.implementation)
    except Exception:
        pass

    # uname
    try:
        lines["os_uname"] = " ".join([str(x) for x in os.uname()])
    except Exception:
        pass

    # machine info
    if machine:
        try:
            lines["unique_id"] = ubinascii.hexlify(machine.unique_id()).decode()
        except Exception:
            pass
        try:
            # ความถี่ CPU (ถ้ามี)
            freq = machine.freq()
            lines["cpu_freq_hz"] = freq if isinstance(freq, int) else str(freq)
        except Exception:
            pass
        try:
            # RTC localtime (อาจเป็น UTC ถ้ายังไม่ได้ตั้ง NTP)
            lines["rtc_localtime"] = "{}".format(time.localtime())
        except Exception:
            pass

    # memory
    try:
        gc.collect()
        free = gc.mem_free()
        alloc = gc.mem_alloc()
        lines["mem_free"] = _fmt_bytes(free)
        lines["mem_alloc"] = _fmt_bytes(alloc)
    except Exception:
        pass

    # filesystem
    fs = _fs_info()
    if fs:
        lines["fs_total"] = _fmt_bytes(fs.get("total", 0))
        lines["fs_used"]  = _fmt_bytes(fs.get("used", 0))
        lines["fs_free"]  = _fmt_bytes(fs.get("free", 0))

    # uptime
    try:
        d, h, m, s = _uptime_tuple()
        lines["uptime"] = "{}d {:02d}:{:02d}:{:02d}".format(d, h, m, s)
    except Exception:
        pass

    # network
    sta = _wlan_info("sta")
    ap  = _wlan_info("ap")
    if sta:
        lines["sta_active"] = sta.get("active")
        if "mac" in sta: lines["sta_mac"] = sta["mac"]
        if "ip" in sta:  lines["sta_ip"]  = sta["ip"]
        if "gw" in sta:  lines["sta_gw"]  = sta["gw"]
        if "dns" in sta: lines["sta_dns"] = sta["dns"]
        if "hostname" in sta: lines["sta_hostname"] = sta["hostname"]
        if "rssi" in sta: lines["sta_rssi"] = sta["rssi"]
    if ap:
        lines["ap_active"] = ap.get("active")
        if "mac" in ap:    lines["ap_mac"] = ap["mac"]
        if "ip" in ap:     lines["ap_ip"]  = ap["ip"]
        if "essid" in ap:  lines["ap_essid"] = ap["essid"]

    return lines


def collect_info_lines():
    """คืนค่าเป็น list ของบรรทัด (key: value) สำหรับ print ทีละบรรทัด"""
    d = collect_info_dict()
    # กำหนดลำดับคีย์หลักเพื่อให้อ่านง่าย
    order = [
        "sys_version", "mp_version", "os_uname",
        "unique_id", "cpu_freq_hz",
        "rtc_localtime", "uptime",
        "mem_free", "mem_alloc",
        "fs_total", "fs_used", "fs_free",
        "sta_active", "sta_hostname", "sta_mac", "sta_ip", "sta_gw", "sta_dns", "sta_rssi",
        "ap_active", "ap_essid", "ap_mac", "ap_ip",
    ]
    lines = []
    used = set()
    for k in order:
        if k in d:
            lines.append("{}: {}".format(k, d[k]))
            used.add(k)
    # ที่เหลือ (เผื่ออนาคต)
    for k, v in d.items():
        if k not in used:
            lines.append("{}: {}".format(k, v))
    return lines


# ---------- public APIs ----------
def print_info():
    """พิมพ์ข้อมูลทั้งหมดเป็นบรรทัด"""
    for line in collect_info_lines():
        print(line)

def json_info(indent=2):
    """คืนค่า JSON string ของข้อมูลทั้งหมด"""
    return json.dumps(collect_info_dict(), indent=indent)

def get_info():
    """คืนค่า dict (ใช้ต่อในโปรแกรมอื่น)"""
    return collect_info_dict()


# Quick self-test
if __name__ == "__main__":
    print_info()
