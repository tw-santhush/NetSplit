import webview
import threading
import time
import os
import psutil
import sys
import subprocess
import ctypes
from ctypes import wintypes
import io
import base64
from datetime import datetime

import win32ui
import win32gui
import win32con
import win32api
from PIL import Image, ImageDraw, ImageFont

from network_scanner import get_all_adapters
from config_manager import load_config, save_config, add_rule, remove_rule_for_app, get_nicknames, set_nickname, get_rules
from router import launch_app as router_launch
from bindip_utils import is_installed, download_and_extract


def _is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def _elevate():
    if _is_admin():
        return
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, subprocess.list2cmdline(sys.argv), None, 1
    )
    sys.exit()


def refresh_adapter_data():
    try:
        return get_all_adapters()
    except Exception as e:
        return {}


def get_default_icon_base64(fallback_emoji="📄"):
    try:
        img = Image.new("RGBA", (32, 32), (139, 92, 246, 255))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("seguiemj.ttf", 20)
        except Exception:
            try:
                font = ImageFont.truetype("arial.ttf", 20)
            except Exception:
                font = ImageFont.load_default()
        draw.text((4, 4), fallback_emoji, fill="white", font=font)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        data = buf.getvalue()
        b64 = base64.b64encode(data).decode()
        result = "data:image/png;base64," + b64
        print(f"  [default_icon] generated: {len(b64)} chars, first 50: {b64[:50]}")
        return result
    except Exception as e:
        print(f"  [default_icon] emoji fallback failed: {e}, using solid square")
        img = Image.new("RGBA", (32, 32), (139, 92, 246, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        result = "data:image/png;base64," + b64
        print(f"  [default_icon] solid square: {len(b64)} chars")
        return result


def _hicon_to_data_uri(hicon, size=32):
    dc = win32ui.CreateDCFromHandle(win32gui.GetDC(0))
    mem_dc = dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(dc, size, size)
    mem_dc.SelectObject(bitmap)
    win32gui.DrawIconEx(mem_dc.GetSafeHdc(), 0, 0, hicon, size, size, 0, None, win32con.DI_NORMAL)

    bmp_info = bitmap.GetInfo()
    bmp_str = bitmap.GetBitmapBits(True)
    img = Image.frombuffer("RGBA", (bmp_info["bmWidth"], bmp_info["bmHeight"]), bmp_str, "raw", "BGRA", 0, 1)

    mem_dc.DeleteDC()
    dc.DeleteDC()
    win32gui.DestroyIcon(hicon)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = buf.getvalue()
    b64 = base64.b64encode(data).decode()
    return "data:image/png;base64," + b64


def _get_shell_icon(path):
    class SHFILEINFOW(ctypes.Structure):
        _fields_ = [
            ('hIcon', wintypes.HANDLE),
            ('iIcon', wintypes.INT),
            ('dwAttributes', wintypes.DWORD),
            ('szDisplayName', wintypes.WCHAR * 260),
            ('szTypeName', wintypes.WCHAR * 80),
        ]
    shinfo = SHFILEINFOW()
    ret = ctypes.windll.shell32.SHGetFileInfoW(path, 0, ctypes.byref(shinfo), ctypes.sizeof(shinfo), 0x100)
    if ret and shinfo.hIcon:
        print(f"  [extract_icon] SHGetFileInfoW returned HICON={shinfo.hIcon}")
        return shinfo.hIcon
    return None


def extract_icon_base64(exe_path, size=32):
    if not os.path.exists(exe_path):
        print(f"  [extract_icon] FILE NOT FOUND: {exe_path}")
        return get_default_icon_base64("❓")
    hicon = None
    source = None
    try:
        print(f"  [extract_icon] Attempting ExtractIconEx: {exe_path}")
        large, small = win32gui.ExtractIconEx(exe_path, 0, 1)
        print(f"  [extract_icon] ExtractIconEx returned: large={len(large) if large else 0}, small={len(small) if small else 0}")
        if large:
            hicon = large[0]
            source = "ExtractIconEx(large)"
        elif small:
            hicon = small[0]
            source = "ExtractIconEx(small)"
    except Exception as e:
        print(f"  [extract_icon] ExtractIconEx exception: {e}")

    if not hicon:
        print(f"  [extract_icon] Trying SHGetFileInfoW fallback...")
        try:
            hicon = _get_shell_icon(exe_path)
            if hicon:
                source = "SHGetFileInfoW"
        except Exception as e:
            print(f"  [extract_icon] SHGetFileInfoW exception: {e}")

    if not hicon:
        print(f"  [extract_icon] All icon extraction methods failed")
        return get_default_icon_base64("📄")

    print(f"  [extract_icon] Got HICON from {source}: {hicon}")
    try:
        result = _hicon_to_data_uri(hicon, size)
        print(f"  [extract_icon] SUCCESS: {exe_path} via {source}")
        return result
    except Exception as e:
        print(f"  [extract_icon] DrawIconEx/encode FAILED: {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()
        try:
            win32gui.DestroyIcon(hicon)
        except Exception:
            pass
        return get_default_icon_base64("📄")


def _normalize_apps(apps_list):
    default_icon = get_default_icon_base64()
    result = []
    for entry in apps_list:
        if isinstance(entry, str):
            result.append({"path": entry, "name": os.path.basename(entry), "icon": default_icon})
        else:
            entry.setdefault("name", os.path.basename(entry.get("path", "")))
            icon = entry.get("icon")
            if not icon or len(icon) < 50:
                if icon:
                    print(f"  [_normalize_apps] Replacing short/invalid icon ({len(icon) if icon else 0} chars) for {entry.get('path')}")
                entry["icon"] = default_icon
            elif len(icon) < 1200:
                print(f"  [_normalize_apps] Icon too small ({len(icon)} chars), re-extracting for {entry.get('path')}")
                new_icon = extract_icon_base64(entry["path"])
                entry["icon"] = new_icon
            result.append(entry)
    return result


STATS = {}
_stats_lock = threading.Lock()


def _stats_monitor():
    prev = {}
    while True:
        time.sleep(1)
        try:
            current = psutil.net_io_counters(pernic=True)
        except Exception:
            continue
        adapter_speeds = {}
        total_down = 0.0
        total_up = 0.0
        for name, cur in current.items():
            if name in prev:
                prev_nic = prev[name]
                dl_bytes = max(0, cur.bytes_recv - prev_nic.bytes_recv)
                ul_bytes = max(0, cur.bytes_sent - prev_nic.bytes_sent)
                dl_mbps = dl_bytes / (1024 * 1024)
                ul_mbps = ul_bytes / (1024 * 1024)
                adapter_speeds[name] = {"down_mbps": dl_mbps, "up_mbps": ul_mbps}
                total_down += dl_mbps
                total_up += ul_mbps
            else:
                adapter_speeds[name] = {"down_mbps": 0.0, "up_mbps": 0.0}
        prev = current
        with _stats_lock:
            STATS["adapters"] = adapter_speeds
            STATS["total_down_mbps"] = total_down
            STATS["total_up_mbps"] = total_up


class Api:

    def __init__(self):
        self.config = load_config()
        self.adapters = {}
        self.log_buffer = []
        self.routing_active = False
        self._log("NetSplit v2.0.0 started")

    def _log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_buffer.append(f"[{timestamp}] {message}\n")
        if len(self.log_buffer) > 500:
            self.log_buffer = self.log_buffer[-250:]

    def get_logs(self):
        return "".join(self.log_buffer[-100:])

    def clear_logs(self):
        self.log_buffer.clear()
        return True

    def get_adapters(self):
        try:
            self.adapters = refresh_adapter_data()
            return self.adapters
        except Exception as e:
            self._log(f"ERROR scanning adapters: {e}")
            return {}

    def refresh_adapters(self):
        self._log("Refreshing adapters...")
        self.config = load_config()
        self.adapters = refresh_adapter_data()
        return {
            "adapters": self.adapters,
            "nicknames": get_nicknames(self.config),
            "rules": get_rules(self.config),
            "apps": _normalize_apps(self.config.get("apps", []))
        }

    def get_apps(self):
        apps = _normalize_apps(self.config.get("apps", []))
        for i, app in enumerate(apps):
            if not app.get("icon"):
                apps[i]["icon"] = extract_icon_base64(app["path"])
        self.config["apps"] = apps
        save_config(self.config)
        return apps

    def add_app(self):
        result = webview.windows[0].create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=False,
            file_types=["Executable files (*.exe)"]
        )
        if result and len(result) > 0:
            app_path = result[0]
            apps = self.config.setdefault("apps", [])
            existing = _normalize_apps(apps)
            for e in existing:
                if e["path"] == app_path:
                    self._log(f"Already added: {os.path.basename(app_path)}")
                    return _normalize_apps(apps)
            icon = extract_icon_base64(app_path)
            apps.append({"path": app_path, "name": os.path.basename(app_path), "icon": icon})
            save_config(self.config)
            self._log(f"Added: {os.path.basename(app_path)}")
            return _normalize_apps(apps)
        return None

    def get_rules(self):
        return {"rules": get_rules(self.config), "nicknames": get_nicknames(self.config)}

    def add_rule(self, app_path, adapter_name, adapter_ip):
        self.config = add_rule(self.config, app_path, adapter_name, adapter_ip)
        save_config(self.config)
        self._log(f"Assigned '{os.path.basename(app_path)}' -> {adapter_name} ({adapter_ip})")
        return True

    def remove_rule(self, app_path):
        self.config = remove_rule_for_app(self.config, app_path)
        save_config(self.config)
        self._log(f"Removed rule for '{os.path.basename(app_path)}'")
        return True

    def remove_app(self, app_path):
        self.config = remove_rule_for_app(self.config, app_path)
        apps = self.config.get("apps", [])
        apps[:] = [e for e in apps if (isinstance(e, str) and e != app_path) or (isinstance(e, dict) and e.get("path") != app_path)]
        save_config(self.config)
        self._log(f"Removed: {os.path.basename(app_path)}")
        return True

    def launch_app(self, app_path, adapter_name):
        self.routing_active = True
        self._log(f"Launching {os.path.basename(app_path)} via {adapter_name}")
        def run():
            try:
                router_launch(app_path, adapter_name, self.adapters, self._log)
                self._log(f"{os.path.basename(app_path)} finished")
            except Exception as e:
                self._log(f"ERROR: {e}")
            finally:
                self.routing_active = False
        threading.Thread(target=run, daemon=True).start()
        return True

    def get_status(self):
        return {"active": self.routing_active}

    def rename_adapter(self, adapter_id, new_nickname):
        self.config = set_nickname(self.config, adapter_id, new_nickname)
        save_config(self.config)
        self._log(f"Nickname for '{adapter_id}' set to '{new_nickname or '(none)'}'")
        return True

    def get_stats(self):
        with _stats_lock:
            stats_copy = {
                "adapters": dict(STATS.get("adapters", {})),
                "total_down_mbps": STATS.get("total_down_mbps", 0.0),
                "total_up_mbps": STATS.get("total_up_mbps", 0.0),
            }
        rules = get_rules(self.config)
        apps_stats = {}
        for r in rules:
            aname = r["adapter_name"]
            if aname in stats_copy["adapters"]:
                apps_stats[r["app_path"]] = dict(stats_copy["adapters"][aname])
            else:
                apps_stats[r["app_path"]] = {"down_mbps": 0.0, "up_mbps": 0.0}
        stats_copy["apps"] = apps_stats
        return stats_copy


def main():
    _elevate()
    if not is_installed():
        try:
            download_and_extract()
        except Exception as e:
            print(f"Failed to install ForceBindIP: {e}")
            return

    api = Api()
    threading.Thread(target=_stats_monitor, daemon=True).start()
    window = webview.create_window(
        "NetSplit",
        "ui/index.html",
        width=1100,
        height=750,
        min_size=(900, 600),
        js_api=api,
        resizable=True
    )
    webview.start(debug=True)


if __name__ == "__main__":
    main()