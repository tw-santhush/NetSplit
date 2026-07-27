import customtkinter as ctk
from tkinter import filedialog, messagebox
import psutil
import socket
import subprocess
import os
import sys
import threading
import ctypes
import time
import json
import urllib.request
import zipfile
import shutil
import stat
from datetime import datetime
import win32com.client

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
TOOLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools")
FORCEBINDIP_URL = "https://r1ch.net/assets/forcebindip/ForceBindIP-1.32.zip"
FORCEBINDIP_EXE = os.path.join(TOOLS_DIR, "ForceBindIP.exe")
FORCEBINDIP_DLL = os.path.join(TOOLS_DIR, "BindIP.dll")
FORCEBINDIP64_EXE = os.path.join(TOOLS_DIR, "ForceBindIP64.exe")
FORCEBINDIP64_DLL = os.path.join(TOOLS_DIR, "BindIP64.dll")


def load_config(path=None):
    path = path or CONFIG_FILE
    if not os.path.isfile(path):
        return {"apps": [], "rules": [], "nicknames": {}}
    try:
        with open(path) as f:
            data = json.load(f)
        data.setdefault("apps", [])
        data.setdefault("rules", [])
        data.setdefault("nicknames", {})
        return data
    except (json.JSONDecodeError, IOError):
        return {"apps": [], "rules": [], "nicknames": {}}


def save_config(config, path=None):
    path = path or CONFIG_FILE
    with open(path, "w") as f:
        json.dump(config, f, indent=2)


def add_rule(config, app_path, adapter_name, adapter_ip):
    config["rules"] = [r for r in config["rules"] if r["app_path"] != app_path]
    config["rules"].append({
        "app_path": app_path,
        "adapter_name": adapter_name,
        "adapter_ip": adapter_ip
    })
    return config


def remove_rule_for_app(config, app_path):
    config["rules"] = [r for r in config["rules"] if r["app_path"] != app_path]
    return config


def get_rules(config):
    return config.get("rules", [])


def get_nicknames(config):
    return config.get("nicknames", {})


def set_nickname(config, system_name, nickname):
    config.setdefault("nicknames", {})
    if nickname:
        config["nicknames"][system_name] = nickname
    else:
        config["nicknames"].pop(system_name, None)
    return config


def _get_wmi_nics():
    try:
        c = win32com.client.Dispatch("WbemScripting.SWbemLocator")
        wmi = c.ConnectServer(".", "root\\cimv2")
        nics = {}
        for nic in wmi.ExecQuery("SELECT * FROM Win32_NetworkAdapter WHERE NetEnabled=True"):
            name = nic.NetConnectionID
            if name:
                nics[name] = nic
        return nics
    except Exception:
        return {}


def get_all_adapters():
    wmi_nics = _get_wmi_nics()
    adapters = {}
    for name, addrs in psutil.net_if_addrs().items():
        if name == "Loopback Pseudo-Interface 1":
            continue
        is_wireless = False
        if name in wmi_nics:
            wmi_nic = wmi_nics[name]
            desc = getattr(wmi_nic, 'Description', None) or ""
            aid = getattr(wmi_nic, 'AdapterTypeId', None)
            is_wireless = (aid == 9) or ('wireless' in desc.lower() or 'wi-fi' in name.lower() or 'wlan' in name.lower())
        ipv4 = None
        for addr in addrs:
            if addr.family == socket.AF_INET:
                ipv4 = addr.address
                break
        if ipv4:
            label = "Wi-Fi" if is_wireless else ("Ethernet" if name in wmi_nics else "Unknown")
            adapters[name] = {"ip": ipv4, "type": label}
    return adapters


def _netsh(args):
    cmd = " ".join(["netsh"] + args)
    return subprocess.run(cmd, capture_output=True, text=True, shell=True)


def _route(args):
    cmd = " ".join(["route"] + args)
    return subprocess.run(cmd, capture_output=True, text=True, shell=True)


def get_adapter_metrics():
    result = _netsh(["interface", "ipv4", "show", "interfaces"])
    if result.returncode != 0:
        raise RuntimeError(f"netsh failed: {result.stderr.strip()}")
    metrics = {}
    for line in result.stdout.splitlines():
        parts = line.strip().split()
        if len(parts) < 5 or not parts[0].isdigit():
            continue
        idx = int(parts[0])
        met = int(parts[1])
        name = " ".join(parts[4:])
        if name:
            metrics[name] = {"metric": met, "idx": idx}
    return metrics


def set_adapter_metric(idx, metric):
    result = _netsh(["interface", "ipv4", "set", "interface", str(idx), f"metric={metric}"])
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to set metric for interface index {idx}: {result.stderr.strip() or result.stdout.strip()}"
        )


def set_metric_auto(idx):
    result = _netsh(["interface", "ipv4", "set", "interface", str(idx), "metric=automatic"])
    if result.returncode != 0:
        raise RuntimeError(f"Failed to set automatic metric for interface index {idx}")


def get_adapter_index(adapter_name):
    result = _netsh(["interface", "ipv4", "show", "interfaces"])
    if result.returncode != 0:
        raise RuntimeError(f"netsh failed: {result.stderr.strip()}")
    for line in result.stdout.splitlines():
        parts = line.strip().split()
        if len(parts) < 5 or not parts[0].isdigit():
            continue
        name = " ".join(parts[4:])
        if name.lower() == adapter_name.lower():
            return parts[0]
    raise RuntimeError(f"Adapter '{adapter_name}' not found")


def get_adapter_gateway_and_idx(adapter_name):
    idx = get_adapter_index(adapter_name)
    adapters_ip = None
    for a in psutil.net_if_addrs().get(adapter_name, []):
        if a.family == socket.AF_INET:
            adapters_ip = a.address
            break
    if adapters_ip:
        result = subprocess.run(["route", "print", "-4"], capture_output=True, text=True, shell=True)
        for line in result.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) >= 5 and parts[0] == "0.0.0.0" and parts[1] == "0.0.0.0":
                if parts[3] == adapters_ip:
                    return {"gateway": parts[2], "idx": idx}
    result = subprocess.run(["ipconfig"], capture_output=True, text=True, shell=True)
    in_section = False
    gateway = None
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.endswith(":") and not stripped.startswith(" "):
            section_name = stripped.split("adapter")[-1].strip().rstrip(":") if "adapter" in stripped.lower() else stripped.rstrip(":")
            in_section = section_name.lower() == adapter_name.lower()
        elif in_section and stripped.startswith("Default Gateway"):
            parts = stripped.split(":")
            if len(parts) >= 2:
                gw = parts[-1].strip()
                if gw and gw != "(blank)":
                    gateway = gw
                    break
    if gateway:
        return {"gateway": gateway, "idx": idx}
    return None


def get_current_default_route():
    result = _netsh(["interface", "ipv4", "show", "route"])
    if result.returncode != 0:
        raise RuntimeError(f"netsh failed: {result.stderr.strip()}")
    gateway = None
    index = None
    for line in result.stdout.splitlines():
        parts = line.strip().split()
        if len(parts) < 6:
            continue
        if parts[3] == "0.0.0.0/0":
            index = parts[4]
            gateway = parts[5]
            break
    if not gateway:
        raise RuntimeError("No default route found")
    if_result = _netsh(["interface", "ipv4", "show", "interfaces"])
    name = None
    metric = None
    for line in if_result.stdout.splitlines():
        parts = line.strip().split()
        if len(parts) < 5 or not parts[0].isdigit():
            continue
        if parts[0] == index:
            metric = int(parts[1])
            name = " ".join(parts[4:])
            break
    return {"gateway": gateway, "interface": name, "metric": metric, "index": index}


def set_default_route(gateway_ip, idx, metric=1):
    result = _route(f"change 0.0.0.0 mask 0.0.0.0 {gateway_ip} if {idx} metric {metric}".split())
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to set default route: {result.stderr.strip() or result.stdout.strip()}"
        )


def restore_default_route(gateway_ip, idx, metric):
    set_default_route(gateway_ip, idx, metric)


def _ensure_tools_dir():
    os.makedirs(TOOLS_DIR, exist_ok=True)


def _remove_readonly(func, path, excinfo):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def is_installed():
    return os.path.isfile(FORCEBINDIP_EXE) and os.path.isfile(FORCEBINDIP_DLL)


import ssl


def download_and_extract(log_callback=None):
    _ensure_tools_dir()
    zip_path = os.path.join(TOOLS_DIR, "ForceBindIP-1.32.zip")
    if log_callback:
        log_callback("Downloading ForceBindIP...")
    try:
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(FORCEBINDIP_URL, context=ctx) as resp:
            with open(zip_path, "wb") as f:
                shutil.copyfileobj(resp, f)
    except Exception as e:
        raise RuntimeError(f"Failed to download ForceBindIP: {e}")
    if log_callback:
        log_callback("Extracting...")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(TOOLS_DIR)
    os.remove(zip_path)
    subdirs = [d for d in os.listdir(TOOLS_DIR) if os.path.isdir(os.path.join(TOOLS_DIR, d))]
    for sd in subdirs:
        sd_path = os.path.join(TOOLS_DIR, sd)
        for item in os.listdir(sd_path):
            src = os.path.join(sd_path, item)
            dst = os.path.join(TOOLS_DIR, item)
            if os.path.isfile(src):
                shutil.move(src, dst)
        shutil.rmtree(sd_path, onerror=_remove_readonly)
    if not is_installed():
        raise RuntimeError("Extraction completed but ForceBindIP.exe not found")
    if log_callback:
        log_callback("ForceBindIP installed successfully")


def get_forcebindip_path():
    if os.path.isfile(FORCEBINDIP64_EXE):
        return FORCEBINDIP64_EXE
    return FORCEBINDIP_EXE


def _format_mb_s(bytes_per_sec):
    mbps = bytes_per_sec / (1024 * 1024)
    if mbps < 0.01:
        return "0.0 MB/s"
    return f"{mbps:.1f} MB/s"


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


class NetSplitApp:
    def __init__(self):
        self.root = ctk.CTk()
        self.root.title("NetSplit")
        self.root.geometry("1100x750")
        self.root.minsize(900, 600)

        self.config = load_config()
        self.adapters = {}
        self.nicknames = get_nicknames(self.config)
        self._prev_io = {}
        self._poll_timer = None
        self.app_entries = []
        self.adapter_frames = {}
        self.routing_active = False
        self.launch_active = False
        self.launch_lock = threading.Lock()
        self.status_dot = None
        self.status_label = None
        self.dl_total_label = None
        self.ul_total_label = None
        self.log_text = None
        self.adapters_container = None

        self._build_ui()
        self.root.after(100, self._initialize)

    def _build_ui(self):
        self.root.grid_rowconfigure(0, weight=0)
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_rowconfigure(2, weight=0)
        self.root.grid_columnconfigure(0, weight=3)
        self.root.grid_columnconfigure(1, weight=7)

        self._build_top_bar()
        self._build_left_panel()
        self._build_right_panel()
        self._build_bottom_bar()

    def _build_top_bar(self):
        bar = ctk.CTkFrame(self.root, height=40, corner_radius=0)
        bar.grid(row=0, column=0, columnspan=2, sticky="nsew")
        bar.grid_columnconfigure(2, weight=1)

        title = ctk.CTkLabel(bar, text="NetSplit", font=("Segoe UI", 18, "bold"))
        title.grid(row=0, column=0, padx=(15, 5), pady=5)

        self.status_dot = ctk.CTkLabel(bar, text="\u25cf", font=("Segoe UI", 14), text_color="#888888")
        self.status_dot.grid(row=0, column=1, padx=(5, 2), pady=5)

        self.status_label = ctk.CTkLabel(bar, text="Idle", font=("Segoe UI", 12), text_color="#888888")
        self.status_label.grid(row=0, column=2, padx=(2, 5), pady=5, sticky="w")

        version = ctk.CTkLabel(bar, text="v1.0", font=("Segoe UI", 12), text_color="#666666")
        version.grid(row=0, column=3, padx=(5, 15), pady=5)

    def _build_left_panel(self):
        panel = ctk.CTkFrame(self.root, corner_radius=8)
        panel.grid(row=1, column=0, sticky="nsew", padx=(5, 2), pady=(2, 5))
        panel.grid_rowconfigure(1, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        header = ctk.CTkLabel(panel, text="Network Adapters", font=("Segoe UI", 14, "bold"))
        header.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="w")

        self.adapters_container = ctk.CTkScrollableFrame(panel, corner_radius=6)
        self.adapters_container.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        self.adapters_container.grid_columnconfigure(0, weight=1)

        refresh_btn = ctk.CTkButton(panel, text="Refresh Adapters", command=self._refresh_adapters)
        refresh_btn.grid(row=2, column=0, padx=10, pady=10, sticky="ew")

    def _build_right_panel(self):
        panel = ctk.CTkFrame(self.root, corner_radius=8)
        panel.grid(row=1, column=1, sticky="nsew", padx=(2, 5), pady=(2, 5))
        panel.grid_rowconfigure(1, weight=1)
        panel.grid_rowconfigure(3, weight=0)
        panel.grid_columnconfigure(0, weight=1)

        toolbar = ctk.CTkFrame(panel, corner_radius=0, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))
        toolbar.grid_columnconfigure(0, weight=0)
        toolbar.grid_columnconfigure(1, weight=1)

        apps_label = ctk.CTkLabel(toolbar, text="Applications", font=("Segoe UI", 14, "bold"))
        apps_label.grid(row=0, column=0, padx=(0, 10), sticky="w")

        add_app_btn = ctk.CTkButton(toolbar, text="Add App", command=self._add_app, width=90)
        add_app_btn.grid(row=0, column=1, padx=2, sticky="e")

        launch_all_btn = ctk.CTkButton(toolbar, text="Launch All", command=self._launch_all, width=90)
        launch_all_btn.grid(row=0, column=2, padx=2)

        self.apps_table = ctk.CTkScrollableFrame(panel, corner_radius=6)
        self.apps_table.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        self.apps_table.grid_columnconfigure(0, weight=2)
        self.apps_table.grid_columnconfigure(1, weight=2)
        self.apps_table.grid_columnconfigure(2, weight=0)
        self.apps_table.grid_columnconfigure(3, weight=1)
        self.apps_table.grid_columnconfigure(4, weight=1)
        self.apps_table.grid_columnconfigure(5, weight=0)

        header_frame = ctk.CTkFrame(self.apps_table, corner_radius=0, fg_color="transparent")
        header_frame.grid(row=0, column=0, columnspan=6, sticky="ew", padx=2, pady=1)
        header_frame.grid_columnconfigure(0, weight=2)
        header_frame.grid_columnconfigure(1, weight=2)
        header_frame.grid_columnconfigure(2, weight=0)
        header_frame.grid_columnconfigure(3, weight=1)
        header_frame.grid_columnconfigure(4, weight=1)
        header_frame.grid_columnconfigure(5, weight=0)

        headers = ["Application", "Assigned Network", "Action", "\u2193 Download", "\u2191 Upload", ""]
        for i, h in enumerate(headers):
            lbl = ctk.CTkLabel(header_frame, text=h, font=("Segoe UI", 11, "bold"), anchor="w")
            lbl.grid(row=0, column=i, padx=4, pady=2, sticky="ew")

        log_header_frame = ctk.CTkFrame(panel, corner_radius=0, fg_color="transparent")
        log_header_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=(5, 0))
        log_header_frame.grid_columnconfigure(0, weight=1)

        log_label = ctk.CTkLabel(log_header_frame, text="System Activity", font=("Segoe UI", 14, "bold"))
        log_label.grid(row=0, column=0, sticky="w")

        clear_log_btn = ctk.CTkButton(log_header_frame, text="Clear Activity", command=self._clear_log, width=100)
        clear_log_btn.grid(row=0, column=1, padx=5)

        self.log_text = ctk.CTkTextbox(panel, height=130, wrap="word")
        self.log_text.grid(row=3, column=0, sticky="ew", padx=10, pady=(2, 10))

    def _build_bottom_bar(self):
        bar = ctk.CTkFrame(self.root, height=36, corner_radius=0)
        bar.grid(row=2, column=0, columnspan=2, sticky="nsew")
        bar.grid_columnconfigure(2, weight=1)

        self.dl_total_label = ctk.CTkLabel(
            bar, text="\u2193 0.0 MB/s", font=("Segoe UI", 13, "bold"), text_color="#4CAF50"
        )
        self.dl_total_label.grid(row=0, column=0, padx=(15, 10), pady=5)

        self.ul_total_label = ctk.CTkLabel(
            bar, text="\u2191 0.0 MB/s", font=("Segoe UI", 13, "bold"), text_color="#FF9800"
        )
        self.ul_total_label.grid(row=0, column=1, padx=(10, 15), pady=5)

    def _initialize(self):
        if not is_installed():
            self._log("ForceBindIP not found. Downloading...")
            try:
                download_and_extract(self._log)
                self._log("ForceBindIP ready")
            except Exception as e:
                self._log(f"ERROR: {e}")
                messagebox.showerror("Setup Error", f"Failed to install ForceBindIP:\n{e}")
        else:
            self._log("ForceBindIP found")

        self.nicknames = get_nicknames(self.config)
        self._refresh_adapters()
        self._load_apps_from_config()
        self._start_monitor()

    def _log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{timestamp}] {message}\n")

    def _clear_log(self):
        self.log_text.delete("1.0", "end")

    def _update_status_ui(self):
        if self.routing_active:
            self.status_dot.configure(text_color="#4CAF50")
            self.status_label.configure(text="Service Active", text_color="#4CAF50")
        else:
            self.status_dot.configure(text_color="#888888")
            self.status_label.configure(text="Idle", text_color="#888888")

    def _refresh_adapters(self):
        for w in self.adapter_frames.values():
            w.destroy()
        self.adapter_frames.clear()

        try:
            self.adapters = get_all_adapters()
        except Exception as e:
            self._log(f"ERROR scanning adapters: {e}")
            self.adapters = {}

        try:
            metrics = get_adapter_metrics()
        except Exception:
            metrics = {}

        if not self.adapters:
            empty_lbl = ctk.CTkLabel(self.adapters_container, text="No adapters found", text_color="#888888")
            empty_lbl.grid(row=0, column=0, padx=5, pady=5)
            self.adapter_frames["_empty"] = empty_lbl
        else:
            self.nicknames = get_nicknames(self.config)
            for i, (name, info) in enumerate(self.adapters.items()):
                frame = ctk.CTkFrame(self.adapters_container, corner_radius=6)
                frame.grid(row=i, column=0, sticky="ew", padx=3, pady=2)
                frame.grid_columnconfigure(1, weight=1)

                metric_info = metrics.get(name, {})
                metric_val = metric_info.get("metric", "?")
                display_name = self.nicknames.get(name, name)

                dot = ctk.CTkLabel(frame, text="\u25cf", font=("Segoe UI", 12), text_color="#4CAF50")
                dot.grid(row=0, column=0, padx=(8, 4), pady=2, sticky="w")

                name_lbl = ctk.CTkLabel(frame, text=display_name, font=("Segoe UI", 12, "bold"), anchor="w")
                name_lbl.grid(row=0, column=1, padx=2, pady=2, sticky="ew")

                pencil_btn = ctk.CTkButton(
                    frame, text="\u270f\ufe0f", width=30, height=24, corner_radius=4,
                    command=lambda n=name: self._rename_adapter(n)
                )
                pencil_btn.grid(row=0, column=2, padx=4, pady=2)

                info_text = f"{info['ip']}  |  Metric: {metric_val}  |  {info['type']}"
                info_lbl = ctk.CTkLabel(
                    frame, text=info_text, font=("Segoe UI", 10), text_color="#AAAAAA", anchor="w"
                )
                info_lbl.grid(row=1, column=0, columnspan=3, padx=(30, 4), pady=0, sticky="w")

                for widget in [frame, dot, name_lbl, info_lbl]:
                    widget.bind("<Double-Button-1>", lambda e, n=name: self._rename_adapter(n))

                self.adapter_frames[name] = frame

        self._update_app_combos()
        self._log(f"Found {len(self.adapters)} adapter(s)")

    def _rename_adapter(self, system_name):
        current_nickname = self.nicknames.get(system_name, "")
        dialog = ctk.CTkInputDialog(
            text=f"Enter nickname for:\n{system_name}",
            title="Rename Adapter"
        )
        new_nickname = dialog.get_input()
        if new_nickname is None:
            return
        self.config = set_nickname(self.config, system_name, new_nickname.strip())
        save_config(self.config)
        self.nicknames = get_nicknames(self.config)
        self._refresh_adapters()
        self._log(f"Nickname for '{system_name}' set to '{new_nickname.strip() or '(none)'}'")

    def _update_app_combos(self):
        combo_values = self._get_combo_values()
        for entry in self.app_entries:
            current = entry["combo"].get()
            entry["combo"].configure(values=combo_values)
            if current in combo_values:
                entry["combo"].set(current)
            else:
                entry["combo"].set("Unassigned")

    def _get_combo_values(self):
        values = ["Unassigned"]
        for name, info in self.adapters.items():
            display = self.nicknames.get(name, name)
            values.append(f"{display} ({info['ip']})")
        return values

    def _get_adapter_from_combo(self, combo_value):
        if combo_value == "Unassigned" or not combo_value:
            return None
        for name, info in self.adapters.items():
            display = self.nicknames.get(name, name)
            expected = f"{display} ({info['ip']})"
            if combo_value == expected:
                return name, info["ip"]
        return None

    def _load_apps_from_config(self):
        for app_path in self.config.get("apps", []):
            if os.path.isfile(app_path) and app_path not in [e["app_path"] for e in self.app_entries]:
                self._add_app_row(app_path)

    def _add_app(self):
        path = filedialog.askopenfilename(
            title="Select Application",
            filetypes=[("Executable files", "*.exe"), ("All files", "*.*")]
        )
        if not path:
            return
        if path in [e["app_path"] for e in self.app_entries]:
            self._log(f"Already added: {os.path.basename(path)}")
            return
        self._add_app_row(path)
        self.config.setdefault("apps", [])
        self.config["apps"].append(path)
        save_config(self.config)
        self._log(f"Added: {os.path.basename(path)}")

    def _add_app_row(self, app_path):
        row = len(self.app_entries) + 1
        combo_values = self._get_combo_values()
        app_name = os.path.basename(app_path)

        row_frame = ctk.CTkFrame(self.apps_table, corner_radius=4)
        row_frame.grid(row=row, column=0, columnspan=6, sticky="ew", padx=2, pady=1)
        row_frame.grid_columnconfigure(0, weight=2)
        row_frame.grid_columnconfigure(1, weight=2)
        row_frame.grid_columnconfigure(2, weight=0)
        row_frame.grid_columnconfigure(3, weight=1)
        row_frame.grid_columnconfigure(4, weight=1)
        row_frame.grid_columnconfigure(5, weight=0)

        name_lbl = ctk.CTkLabel(row_frame, text=app_name, font=("Segoe UI", 11), anchor="w")
        name_lbl.grid(row=0, column=0, padx=4, pady=2, sticky="ew")

        combo = ctk.CTkComboBox(row_frame, values=combo_values, state="readonly", width=160)
        combo.grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        combo.set("Unassigned")

        for rule in get_rules(self.config):
            if rule["app_path"] == app_path:
                aname = rule["adapter_name"]
                if aname in self.adapters:
                    display = self.nicknames.get(aname, aname)
                    ip = self.adapters[aname]["ip"]
                    combo.set(f"{display} ({ip})")
                else:
                    combo.set(f"{aname} (?)")
                break

        launch_btn = ctk.CTkButton(
            row_frame, text="Launch", width=70, height=28,
            command=lambda p=app_path: self._launch_app(p)
        )
        launch_btn.grid(row=0, column=2, padx=4, pady=2)

        dl_lbl = ctk.CTkLabel(
            row_frame, text="0.0 MB/s", font=("Segoe UI", 11), text_color="#4CAF50", anchor="e"
        )
        dl_lbl.grid(row=0, column=3, padx=4, pady=2, sticky="ew")

        ul_lbl = ctk.CTkLabel(
            row_frame, text="0.0 MB/s", font=("Segoe UI", 11), text_color="#FF9800", anchor="e"
        )
        ul_lbl.grid(row=0, column=4, padx=4, pady=2, sticky="ew")

        remove_btn = ctk.CTkButton(
            row_frame, text="\u2715", width=24, height=24, corner_radius=4,
            fg_color="transparent", text_color="#FF5252", hover_color="#FF1744",
            command=lambda p=app_path: self._remove_app_row(p)
        )
        remove_btn.grid(row=0, column=5, padx=2, pady=2)

        def on_combo_change(choice, path=app_path):
            self._on_app_combo_change(path, choice)
        combo.configure(command=on_combo_change)

        entry = {
            "app_path": app_path,
            "frame": row_frame,
            "combo": combo,
            "launch_btn": launch_btn,
            "dl_label": dl_lbl,
            "ul_label": ul_lbl,
        }
        self.app_entries.append(entry)

    def _on_app_combo_change(self, app_path, choice):
        result = self._get_adapter_from_combo(choice)
        if result is None:
            self.config = remove_rule_for_app(self.config, app_path)
            self._log(f"Removed rule for '{os.path.basename(app_path)}'")
        else:
            adapter_name, adapter_ip = result
            self.config = add_rule(self.config, app_path, adapter_name, adapter_ip)
            self._log(f"Assigned '{os.path.basename(app_path)}' -> {adapter_name} ({adapter_ip})")
        save_config(self.config)

    def _remove_app_row(self, app_path):
        for i, entry in enumerate(self.app_entries):
            if entry["app_path"] == app_path:
                entry["frame"].destroy()
                self.app_entries.pop(i)
                if app_path in self.config.get("apps", []):
                    self.config["apps"].remove(app_path)
                self.config = remove_rule_for_app(self.config, app_path)
                save_config(self.config)
                self._log(f"Removed: {os.path.basename(app_path)}")
                self._reorder_app_rows()
                break

    def _reorder_app_rows(self):
        for i, entry in enumerate(self.app_entries):
            entry["frame"].grid(row=i + 1)

    def _get_assigned_adapter(self, app_path):
        for rule in get_rules(self.config):
            if rule["app_path"] == app_path:
                return rule.get("adapter_name")
        return None

    def _launch_app(self, app_path):
        if not self.launch_lock.acquire(blocking=False):
            messagebox.showinfo("In Progress", "A launch is already in progress")
            return

        adapter_name = self._get_assigned_adapter(app_path)
        if not adapter_name or adapter_name not in self.adapters:
            messagebox.showwarning(
                "No Assignment",
                f"No adapter assigned to '{os.path.basename(app_path)}'.\nAssign it first."
            )
            self.launch_lock.release()
            return

        self.launch_active = True
        self.routing_active = True
        self._update_status_ui()
        threading.Thread(
            target=self._launch_and_monitor,
            args=(app_path, adapter_name),
            daemon=True
        ).start()

    def _launch_all(self):
        if not self.launch_lock.acquire(blocking=False):
            messagebox.showinfo("In Progress", "A launch is already in progress")
            return

        rules = get_rules(self.config)
        if not rules:
            messagebox.showinfo("No Rules", "No rules to launch")
            self.launch_lock.release()
            return

        valid_rules = [r for r in rules if r["adapter_name"] in self.adapters]
        if not valid_rules:
            messagebox.showwarning("No Valid Rules", "No rules with valid adapters found.")
            self.launch_lock.release()
            return

        self.launch_active = True
        self.routing_active = True
        self._update_status_ui()
        threading.Thread(
            target=self._launch_all_and_monitor,
            args=(valid_rules,),
            daemon=True
        ).start()

    def _apply_metrics(self, adapter_name):
        changed = []
        metrics = get_adapter_metrics()
        primary = metrics.get(adapter_name)
        if not primary:
            raise RuntimeError(f"Adapter '{adapter_name}' not found in metrics")
        self._log(f'Setting adapter {primary["idx"]} to metric 1')
        set_adapter_metric(primary['idx'], 1)
        changed.append(adapter_name)
        for name, info in metrics.items():
            if name != adapter_name:
                self._log(f'Setting adapter {info["idx"]} to metric 50')
                set_adapter_metric(info['idx'], 50)
                changed.append(name)
        return metrics, changed

    def _restore_metrics(self, snapshot, changed=None):
        targets = changed or list(snapshot.keys())
        for name in targets:
            info = snapshot.get(name)
            if info is not None and info['metric'] is not None:
                set_adapter_metric(info['idx'], info['metric'])
                self._log(f'Restored adapter {info["idx"]} to metric {info["metric"]}')
            elif info is not None:
                set_metric_auto(info['idx'])
                self._log(f'Restored adapter {info["idx"]} to automatic metric')

    def _restore_route(self, original_route):
        gw = original_route['gateway']
        idx = original_route['index']
        met = original_route['metric']
        self._log(f'Restoring default route to {gw}')
        restore_default_route(gw, idx, met)

    def _restore_all(self, metric_snapshot, metric_changed, original_route):
        self._restore_metrics(metric_snapshot, metric_changed)
        if original_route:
            self._restore_route(original_route)

    def _launch_and_monitor(self, app_path, adapter_name):
        metric_snapshot = {}
        metric_changed = []
        original_route = None
        try:
            metric_snapshot, metric_changed = self._apply_metrics(adapter_name)

            self._log(f'Looking up gateway for adapter: {adapter_name}')
            gw_info = get_adapter_gateway_and_idx(adapter_name)
            if not gw_info:
                error_msg = "Could not find the default gateway for the selected adapter."
                self._log('ERROR: ' + error_msg)
                self.root.after(0, lambda: messagebox.showerror("Routing Error", error_msg))
                self._restore_metrics(metric_snapshot, metric_changed)
                self.launch_active = False
                self.routing_active = False
                self.root.after(0, self._update_status_ui)
                return

            gateway = gw_info['gateway']
            gw_idx = gw_info['idx']
            self._log(f'Gateway: {gateway}, Index: {gw_idx}')

            original_route = get_current_default_route()
            self._log(f'Switching default route to {gateway} via {adapter_name}')
            set_default_route(gateway, gw_idx, 1)
            time.sleep(0.5)

            adapter_ip = self.adapters.get(adapter_name, {}).get("ip", "")
            if not adapter_ip:
                raise RuntimeError(f"No IP for adapter '{adapter_name}'")

            forcebindip = get_forcebindip_path()
            cmd = [forcebindip, "-i", adapter_ip, app_path]
            self._log(f"Launching: {' '.join(cmd)}")
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._log(f"Launched {os.path.basename(app_path)}")

            time.sleep(0.3)

            target_name = os.path.basename(app_path).lower()
            target_proc = None
            threshold = time.time()
            for p in psutil.process_iter(['pid', 'name', 'create_time']):
                try:
                    if p.info['name'] and p.info['name'].lower() == target_name:
                        if p.info['create_time'] and p.info['create_time'] >= threshold - 2:
                            parent = p.parent()
                            if parent and 'forcebindip' in parent.name().lower():
                                target_proc = p
                                break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            if target_proc:
                self._log(f"Monitoring {target_name} (PID {target_proc.pid})")
                target_proc.wait()
                self._log("Process exited. Restoring network settings...")
            else:
                self._log("Target process not found, monitoring ForceBindIP launcher")
                proc.wait()
                self._log("Launcher exited. Restoring network settings...")

            if self.launch_active:
                self._restore_all(metric_snapshot, metric_changed, original_route)
        except Exception as e:
            self._log(f"ERROR: {e}")
            self._restore_metrics(metric_snapshot, metric_changed)
            if original_route:
                self._restore_route(original_route)
        finally:
            self.launch_active = False
            self.routing_active = False
            self.root.after(0, self._update_status_ui)
            self.launch_lock.release()

    def _launch_all_and_monitor(self, rules):
        if not rules:
            return
        primary_adapter = rules[0]["adapter_name"]
        metric_snapshot = {}
        metric_changed = []
        original_route = None
        try:
            metric_snapshot, metric_changed = self._apply_metrics(primary_adapter)

            self._log(f'Looking up gateway for adapter: {primary_adapter}')
            gw_info = get_adapter_gateway_and_idx(primary_adapter)
            if not gw_info:
                error_msg = "Could not find the default gateway for the selected adapter."
                self._log('ERROR: ' + error_msg)
                self.root.after(0, lambda: messagebox.showerror("Routing Error", error_msg))
                self._restore_metrics(metric_snapshot, metric_changed)
                return

            gateway = gw_info['gateway']
            gw_idx = gw_info['idx']
            self._log(f'Gateway: {gateway}, Index: {gw_idx}')

            original_route = get_current_default_route()
            self._log(f'Switching default route to {gateway} via {primary_adapter}')
            set_default_route(gateway, gw_idx, 1)
            time.sleep(0.5)

            target_procs = []
            for rule in rules:
                app_path = rule["app_path"]
                adapter_name = rule["adapter_name"]
                adapter_ip = self.adapters.get(adapter_name, {}).get("ip", "")
                if not adapter_ip:
                    self._log(f'ERROR: No IP for adapter "{adapter_name}"')
                    continue
                forcebindip = get_forcebindip_path()
                cmd = [forcebindip, "-i", adapter_ip, app_path]
                self._log(f"Launching: {' '.join(cmd)}")
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                target_procs.append((proc, app_path))
                self._log(f"Launched {os.path.basename(app_path)}")

            if not target_procs:
                self._log("No applications were launched")
                self._restore_metrics(metric_snapshot, metric_changed)
                if original_route:
                    self._restore_route(original_route)
                return

            time.sleep(0.3)
            targets = []
            for proc, app_path in target_procs:
                target_name = os.path.basename(app_path).lower()
                target_proc = None
                threshold = time.time()
                for p in psutil.process_iter(['pid', 'name', 'create_time']):
                    try:
                        if p.info['name'] and p.info['name'].lower() == target_name:
                            if p.info['create_time'] and p.info['create_time'] >= threshold - 2:
                                parent = p.parent()
                                if parent and 'forcebindip' in parent.name().lower():
                                    target_proc = p
                                    break
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                if target_proc:
                    self._log(f"Monitoring {target_name} (PID {target_proc.pid})")
                    targets.append(target_proc)
                else:
                    self._log(f"Fallback monitoring for {target_name}")
                    targets.append(proc)

            for t in targets:
                t.wait()

            self._log("All processes exited. Restoring network settings...")
            self._restore_all(metric_snapshot, metric_changed, original_route)
        except Exception as e:
            self._log(f"ERROR: {e}")
            self._restore_metrics(metric_snapshot, metric_changed)
            if original_route:
                self._restore_route(original_route)
        finally:
            self.launch_active = False
            self.routing_active = False
            self.root.after(0, self._update_status_ui)
            self.launch_lock.release()

    def _start_monitor(self):
        try:
            self._prev_io = psutil.net_io_counters(pernic=True)
        except Exception:
            self._prev_io = {}
        self._poll_traffic()

    def _poll_traffic(self):
        try:
            current = psutil.net_io_counters(pernic=True)
        except Exception:
            current = {}

        total_dl = 0
        total_ul = 0

        for name in current:
            if name in self._prev_io:
                prev = self._prev_io.get(name)
                cur = current.get(name)
                if prev and cur:
                    total_dl += max(0, cur.bytes_recv - prev.bytes_recv)
                    total_ul += max(0, cur.bytes_sent - prev.bytes_sent)

        for entry in self.app_entries:
            adapter_name = self._get_assigned_adapter(entry["app_path"])
            dl_speed = 0
            ul_speed = 0
            if adapter_name and adapter_name in current and adapter_name in self._prev_io:
                prev = self._prev_io.get(adapter_name)
                cur = current.get(adapter_name)
                if prev and cur:
                    dl_speed = max(0, cur.bytes_recv - prev.bytes_recv)
                    ul_speed = max(0, cur.bytes_sent - prev.bytes_sent)

            entry["dl_label"].configure(text=_format_mb_s(dl_speed))
            entry["ul_label"].configure(text=_format_mb_s(ul_speed))

        self.dl_total_label.configure(text=f"\u2193 {_format_mb_s(total_dl)}")
        self.ul_total_label.configure(text=f"\u2191 {_format_mb_s(total_ul)}")

        self._prev_io = current
        self._poll_timer = self.root.after(1000, self._poll_traffic)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    _elevate()
    app = NetSplitApp()
    app.run()
