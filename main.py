VERSION = "3.1.0"

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
from PIL import Image, ImageDraw, ImageFont

try:
    import pystray
    from pystray import MenuItem as TrayItem
    _HAS_TRAY = True
except ImportError:
    _HAS_TRAY = False

from network_scanner import get_all_adapters
from config_manager import load_config, save_config, add_rule, remove_rule_for_app, get_nicknames, set_nickname, get_rules, get_theme, set_theme
from router import launch_app as router_launch
from bindip_utils import is_installed, download_and_extract

_window_ref = None
_tray_icon = None


def _is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def _elevate():
    if _is_admin():
        return
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, subprocess.list2cmdline(sys.argv), None, 0
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
        return result
    except Exception:
        img = Image.new("RGBA", (32, 32), (139, 92, 246, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        result = "data:image/png;base64," + b64
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
        return shinfo.hIcon
    return None


def extract_icon_base64(exe_path, size=32):
    if not os.path.exists(exe_path):
        return get_default_icon_base64("?")
    hicon = None
    source = None
    try:
        large, small = win32gui.ExtractIconEx(exe_path, 0, 1)
        if large:
            hicon = large[0]
            source = "ExtractIconEx(large)"
        elif small:
            hicon = small[0]
            source = "ExtractIconEx(small)"
    except Exception:
        pass

    if not hicon:
        try:
            hicon = _get_shell_icon(exe_path)
            if hicon:
                source = "SHGetFileInfoW"
        except Exception:
            pass

    if not hicon:
        return get_default_icon_base64("\U0001F4C4")

    try:
        result = _hicon_to_data_uri(hicon, size)
        return result
    except Exception:
        try:
            win32gui.DestroyIcon(hicon)
        except Exception:
            pass
        return get_default_icon_base64("\U0001F4C4")


def _normalize_apps(apps_list):
    default_icon = get_default_icon_base64()
    result = []
    for entry in apps_list:
        if isinstance(entry, str):
            result.append({"path": entry, "name": os.path.basename(entry), "icon": default_icon})
        else:
            item = dict(entry)
            item.setdefault("name", os.path.basename(item.get("path", "")))
            icon = item.get("icon")
            if not icon or len(icon) < 50:
                item["icon"] = default_icon
            elif len(icon) < 1200:
                new_icon = extract_icon_base64(item["path"])
                item["icon"] = new_icon
            result.append(item)
    return result


SYSTEM_PROCESSES = {
    "svchost.exe", "csrss.exe", "System", "Idle", "services.exe",
    "lsass.exe", "winlogon.exe", "explorer.exe", "smss.exe",
    "wininit.exe", "spoolsv.exe", "dllhost.exe", "conhost.exe",
    "sihost.exe", "taskhostw.exe", "runtimebroker.exe",
}

COMMON_DIRS = [
    "Program Files",
    "Program Files (x86)",
    "AppData\\Local",
    "AppData\\Roaming",
]


def get_internet_apps():
    connections = set()
    try:
        for conn in psutil.net_connections():
            if conn.status == "ESTABLISHED" and conn.pid:
                connections.add(conn.pid)
    except Exception:
        pass

    found = []
    seen = set()
    for proc in psutil.process_iter(["name", "exe"]):
        try:
            info = proc.info
            name = info.get("name", "") or ""
            exe = info.get("exe", "") or ""
            if not exe.lower().endswith(".exe"):
                continue
            if name.lower() in SYSTEM_PROCESSES:
                continue
            if proc.pid not in connections:
                continue
            if not any(d.lower() in exe.lower() for d in COMMON_DIRS):
                continue
            if exe in seen:
                continue
            seen.add(exe)
            found.append({"path": exe, "name": os.path.basename(exe)})
            if len(found) >= 20:
                break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return found


STATS = {}
_stats_lock = threading.Lock()

_app_traffic = {}
_app_traffic_lock = threading.Lock()


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


def _app_traffic_monitor(api):
    prev_io = None
    while True:
        time.sleep(1)
        try:
            current_io = psutil.net_io_counters(pernic=True)
            if prev_io is None:
                prev_io = current_io
                continue

            total_dl = 0
            total_ul = 0
            for name, cur in current_io.items():
                if name in prev_io:
                    prev = prev_io[name]
                    total_dl += max(0, cur.bytes_recv - prev.bytes_recv)
                    total_ul += max(0, cur.bytes_sent - prev.bytes_sent)
            prev_io = current_io
            total_dl_mbps = total_dl / (1024 * 1024)
            total_ul_mbps = total_ul / (1024 * 1024)

            conns_by_pid = {}
            for conn in psutil.net_connections():
                if conn.pid and conn.status == "ESTABLISHED":
                    conns_by_pid[conn.pid] = conns_by_pid.get(conn.pid, 0) + 1

            api.refresh_known_apps()
            known = api._known_apps
            pid_app = {}
            for proc in psutil.process_iter(["pid", "exe"]):
                try:
                    exe = proc.info.get("exe", "") or ""
                    if exe in known:
                        pid_app[proc.info["pid"]] = exe
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            app_conns = {}
            for pid, c in conns_by_pid.items():
                if pid in pid_app:
                    app = pid_app[pid]
                    app_conns[app] = app_conns.get(app, 0) + c

            total_conns = sum(app_conns.values())
            result = {}
            for path in known:
                if total_conns > 0:
                    r = app_conns.get(path, 0) / total_conns
                    result[path] = {"down_mbps": total_dl_mbps * r, "up_mbps": total_ul_mbps * r}
                else:
                    result[path] = {"down_mbps": 0.0, "up_mbps": 0.0}

            with _app_traffic_lock:
                _app_traffic.clear()
                _app_traffic.update(result)
        except Exception:
            pass


class Api:

    def __init__(self):
        self.config = load_config()
        self.adapters = {}
        self.log_buffer = []
        self.routing_active = False
        self._tracked_pids = set()
        self._adapter_cache = None
        self._adapter_cache_time = 0
        self._known_apps = self._build_known_apps()
        self._known_apps_mtime = self._config_mtime()
        self._log("NetSplit v3.1.0 started")

    def _config_mtime(self):
        from config_manager import CONFIG_FILE
        try:
            return os.path.getmtime(CONFIG_FILE)
        except OSError:
            return 0

    def _build_known_apps(self):
        cfg = self.config
        return {
            entry if isinstance(entry, str) else entry.get("path", "")
            for entry in cfg.get("apps", [])
        } if cfg else set()

    def refresh_known_apps(self):
        mtime = self._config_mtime()
        if mtime != self._known_apps_mtime:
            self.config = load_config()
            self._known_apps = self._build_known_apps()
            self._known_apps_mtime = mtime

    def get_version(self):
        return VERSION

    def get_theme(self):
        return get_theme(self.config)

    def toggle_theme(self):
        current = get_theme(self.config)
        new_theme = "light" if current == "dark" else "dark"
        self.config = set_theme(self.config, new_theme)
        save_config(self.config)
        self._log(f"Theme changed to {'Light' if new_theme == 'light' else 'Dark'} Mode")
        return new_theme

    def _log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_buffer.append(f"[{timestamp}] {message}\n")
        if len(self.log_buffer) > 500:
            self.log_buffer = self.log_buffer[-250:]

    def get_logs(self):
        return "".join(self.log_buffer[-100:])

    def add_log(self, message):
        self._log(message)
        return True

    def clear_logs(self):
        self.log_buffer.clear()
        return True

    def get_adapters(self):
        now = time.time()
        if self._adapter_cache is not None and (now - self._adapter_cache_time) < 5:
            return self._adapter_cache
        try:
            self.adapters = refresh_adapter_data()
            self._adapter_cache = self.adapters
            self._adapter_cache_time = now
            return self.adapters
        except Exception as e:
            self._log(f"ERROR scanning adapters: {e}")
            return {}

    def refresh_adapters(self):
        self._adapter_cache = None
        self.adapters = refresh_adapter_data()
        self._adapter_cache = self.adapters
        self._adapter_cache_time = time.time()
        self.config = load_config()
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
        return apps

    def get_running_apps(self):
        return get_internet_apps()

    def add_app(self, app_path=None):
        if app_path:
            apps = self.config.setdefault("apps", [])
            existing = _normalize_apps(apps)
            for e in existing:
                if e["path"] == app_path:
                    return _normalize_apps(apps)
            icon = extract_icon_base64(app_path)
            entry = {"path": app_path, "name": os.path.basename(app_path), "icon": icon}
            apps.append(entry)
            save_config(self.config)
            self._known_apps.add(app_path)
            self._log(f"Auto-added: {os.path.basename(app_path)}")
            return _normalize_apps(apps)
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
            self._known_apps.add(app_path)
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
        self._known_apps.discard(app_path)
        self._log(f"Removed: {os.path.basename(app_path)}")
        return True

    def launch_app(self, app_path, adapter_name):
        self.routing_active = True
        app_name = os.path.basename(app_path)
        self._log(f"Launching {app_name} via {adapter_name}")
        def run():
            try:
                pid = router_launch(app_path, adapter_name, self.adapters, self._log)
                if pid:
                    self._tracked_pids.add(pid)
                self._log(f"{app_name} finished")
            except Exception as e:
                self._log(f"ERROR: {e}")
            finally:
                self.routing_active = False
        threading.Thread(target=run, daemon=True).start()
        return True

    def launch_all(self):
        rules = get_rules(self.config)
        count = 0
        self.routing_active = True
        for r in rules:
            app_path = r["app_path"]
            adapter_name = r["adapter_name"]
            self._log(f"Launching {os.path.basename(app_path)} via {adapter_name}")
            def make_launcher(p, a):
                def run():
                    try:
                        pid = router_launch(p, a, self.adapters, self._log)
                        if pid:
                            self._tracked_pids.add(pid)
                    except Exception as e:
                        self._log(f"Launch error for {os.path.basename(p)}: {e}")
                return run
            threading.Thread(target=make_launcher(app_path, adapter_name), daemon=True).start()
            count += 1
        self._log(f"Launched {count} apps from tray")
        return count

    def get_status(self):
        alive_pids = {p for p in self._tracked_pids if psutil.pid_exists(p)}
        self._tracked_pids = alive_pids
        active = self.routing_active or bool(alive_pids)
        if not active:
            self.routing_active = False
        return {"active": active}

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

    def get_app_traffic(self):
        with _app_traffic_lock:
            return dict(_app_traffic)

    def optimize_rules(self):
        rules = get_rules(self.config)
        assigned = {r["app_path"] for r in rules}
        apps_list = self.config.get("apps", [])
        unassigned = []
        for entry in apps_list:
            path = entry if isinstance(entry, str) else entry["path"]
            if path not in assigned:
                unassigned.append(entry)
        adapter_names = list(self.adapters.keys())
        if not adapter_names:
            self._log("No active adapters found. Cannot optimize.")
            return {"count": 0, "assignments": [], "error": "No active adapters found. Cannot optimize."}
        if not unassigned:
            self._log("All apps already assigned. Nothing to optimize.")
            return {"count": 0, "assignments": []}
        with _stats_lock:
            adapter_loads = {}
            for name, s in STATS.get("adapters", {}).items():
                adapter_loads[name] = s["down_mbps"] + s["up_mbps"]
        for name in adapter_names:
            if name not in adapter_loads:
                adapter_loads[name] = 0
        assignments = []
        for entry in unassigned:
            app_path = entry if isinstance(entry, str) else entry["path"]
            best = min(adapter_loads, key=adapter_loads.get)
            info = self.adapters.get(best, {})
            ip = info.get("ip", "")
            if ip:
                self.config = add_rule(self.config, app_path, best, ip)
                adapter_loads[best] += 1
                app_name = os.path.basename(app_path)
                assignments.append({"app": app_name, "adapter": best})
        if assignments:
            save_config(self.config)
            summary = ", ".join(f"{a['app']} -> {a['adapter']}" for a in assignments)
            self._log(f"Optimized {len(assignments)} apps: {summary}")
        return {"count": len(assignments), "assignments": assignments}

    def clear_all_rules(self):
        for r in get_rules(self.config):
            self.config = remove_rule_for_app(self.config, r["app_path"])
        save_config(self.config)
        self._log("All rules cleared")
        return True


def _hide_console():
    try:
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
    except Exception:
        pass


def _set_window_icon():
    import time
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
    if not os.path.isfile(icon_path):
        return
    for _ in range(60):
        hwnd = ctypes.windll.user32.FindWindowW(None, "NetSplit")
        if hwnd:
            break
        time.sleep(0.05)
    if not hwnd:
        return
    hicon = ctypes.windll.user32.LoadImageW(0, icon_path, 1, 32, 32, 0x00000010)
    if hicon:
        ctypes.windll.user32.SendMessageW(hwnd, 0x0080, 0, hicon)
        ctypes.windll.user32.SendMessageW(hwnd, 0x0080, 1, hicon)


if _HAS_TRAY:
    _tray_ready = threading.Event()

    def _create_tray_image():
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
        try:
            return Image.open(icon_path)
        except Exception:
            pass
        size = 64
        img = Image.new("RGBA", (size, size), (139, 92, 246, 255))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", 36)
        except Exception:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), "N", font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text(((size - tw) // 2, (size - th) // 2 - 2), "N", fill="white", font=font)
        return img

    def _start_tray(api):
        global _tray_icon
        try:
            def on_show():
                global _window_ref
                if _window_ref:
                    try:
                        _window_ref.show()
                    except Exception:
                        pass

            def on_launch_all():
                api.launch_all()

            def on_quit():
                global _tray_icon, _window_ref
                if _window_ref:
                    try:
                        _window_ref.destroy()
                    except Exception:
                        pass
                if _tray_icon:
                    _tray_icon.stop()
                os._exit(0)

            def on_left_click(icon, button):
                try:
                    if button == getattr(pystray, "Button", object()).LEFT:
                        on_show()
                except Exception:
                    pass

            menu = pystray.Menu(
                TrayItem("Show NetSplit", on_show, default=True),
                pystray.Menu.SEPARATOR,
                TrayItem("Launch All", on_launch_all),
                pystray.Menu.SEPARATOR,
                TrayItem("Quit", on_quit),
            )

            img = _create_tray_image()
            _tray_icon = pystray.Icon("netsplit", img, "NetSplit", menu)
            try:
                _tray_icon.on_left_click = on_left_click
                _tray_icon._on_left_click = on_left_click
            except Exception:
                pass
            _tray_ready.set()
            _tray_icon.run()
        except Exception as e:
            import traceback
            traceback.print_exc()


def main():
    _hide_console()
    _elevate()
    if not is_installed():
        try:
            download_and_extract()
        except Exception as e:
            print(f"Failed to install ForceBindIP: {e}")
            return

    api = Api()
    threading.Thread(target=_stats_monitor, daemon=True).start()
    threading.Thread(target=_app_traffic_monitor, args=(api,), daemon=True).start()

    global _window_ref

    def on_closing():
        global _tray_icon
        if _tray_icon:
            try:
                _tray_icon.stop()
            except Exception:
                pass
        return True

    _window_ref = webview.create_window(
        "NetSplit",
        "ui/index.html",
        width=1100,
        height=750,
        min_size=(900, 600),
        js_api=api,
        resizable=True
    )

    _window_ref.events.closing += on_closing
    try:
        _window_ref.events.shown += lambda: _set_window_icon()
    except Exception:
        pass
    threading.Thread(target=_set_window_icon, daemon=True).start()

    try:
        _window_ref.events.minimized += lambda: _window_ref.hide()
    except Exception:
        pass

    if _HAS_TRAY:
        threading.Thread(target=_start_tray, args=(api,), daemon=False).start()
        _tray_ready.wait(timeout=3)

    webview.start(debug=False)

    if _HAS_TRAY:
        while _tray_icon is not None:
            try:
                if not _tray_icon.visible:
                    break
            except Exception:
                break
            time.sleep(0.5)


if __name__ == "__main__":
    main()