import webview
import threading
import time
import os
import psutil
import sys
import subprocess
import ctypes
from datetime import datetime

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


class Api:

    def __init__(self):
        self.config = load_config()
        self.adapters = {}
        self.log_buffer = []
        self.routing_active = False
        self._prev_io = {}
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
            "rules": get_rules(self.config)
        }

    def get_apps(self):
        return self.config.get("apps", [])

    def add_app(self):
        result = webview.windows[0].create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=False,
            file_types=["Executable files (*.exe)"]
        )
        if result and len(result) > 0:
            app_path = result[0]
            apps = self.config.setdefault("apps", [])
            if app_path in apps:
                self._log(f"Already added: {os.path.basename(app_path)}")
                return None
            apps.append(app_path)
            save_config(self.config)
            self._log(f"Added: {os.path.basename(app_path)}")
            return apps
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
        if app_path in apps:
            apps.remove(app_path)
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
        try:
            current = psutil.net_io_counters(pernic=True)
        except Exception:
            current = {}
        stats = {}
        for app_path in self.config.get("apps", []):
            rules = get_rules(self.config)
            adapter_name = None
            for r in rules:
                if r["app_path"] == app_path:
                    adapter_name = r["adapter_name"]
                    break
            if adapter_name and adapter_name in current and adapter_name in self._prev_io:
                prev = self._prev_io[adapter_name]
                cur = current[adapter_name]
                dl = max(0, cur.bytes_recv - prev.bytes_recv)
                ul = max(0, cur.bytes_sent - prev.bytes_sent)
                stats[app_path] = {"down": dl, "up": ul}
            else:
                stats[app_path] = {"down": 0, "up": 0}
        self._prev_io = current
        return stats


def main():
    _elevate()
    if not is_installed():
        try:
            download_and_extract()
        except Exception as e:
            print(f"Failed to install ForceBindIP: {e}")
            return

    api = Api()
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