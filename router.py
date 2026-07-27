import subprocess
import time
import os
import psutil
import socket
import threading

from bindip_utils import get_forcebindip_path


_route_lock = threading.Lock()

_netsh_cache = {}
_NETSH_CACHE_TTL = 5


def _netsh_cached(args):
    key = tuple(args)
    now = time.time()
    if key in _netsh_cache and (now - _netsh_cache[key][0]) < _NETSH_CACHE_TTL:
        return _netsh_cache[key][1]
    result = subprocess.run(["netsh"] + args, capture_output=True, text=True)
    _netsh_cache[key] = (now, result)
    return result


def _get_interfaces():
    result = _netsh_cached(["interface", "ipv4", "show", "interfaces"])
    if result.returncode != 0:
        raise RuntimeError(f"netsh failed: {result.stderr.strip()}")
    adapters = {}
    for line in result.stdout.splitlines():
        parts = line.strip().split()
        if len(parts) < 5 or not parts[0].isdigit():
            continue
        idx = int(parts[0])
        met = int(parts[1])
        name = " ".join(parts[4:])
        if name:
            adapters[name] = {"metric": met, "idx": idx}
    return adapters


def _netsh(args):
    return subprocess.run(["netsh"] + args, capture_output=True, text=True)


def _route(args):
    return subprocess.run(["route"] + args, capture_output=True, text=True)


def get_adapter_index(adapter_name):
    interfaces = _get_interfaces()
    for name, info in interfaces.items():
        if name.lower() == adapter_name.lower():
            return str(info["idx"])
    raise RuntimeError(f"Adapter '{adapter_name}' not found")


def get_adapter_metrics():
    return _get_interfaces()


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


def get_adapter_gateway_and_idx(adapter_name):
    idx = get_adapter_index(adapter_name)
    adapters_ip = None
    for a in psutil.net_if_addrs().get(adapter_name, []):
        if a.family == socket.AF_INET:
            adapters_ip = a.address
            break
    if adapters_ip:
        result = subprocess.run(["route", "print", "-4"], capture_output=True, text=True)
        for line in result.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) >= 5 and parts[0] == "0.0.0.0" and parts[1] == "0.0.0.0":
                if parts[3] == adapters_ip:
                    return {"gateway": parts[2], "idx": idx}
    result = subprocess.run(["ipconfig"], capture_output=True, text=True)
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
    interfaces = _get_interfaces()
    for name, info in interfaces.items():
        if str(info["idx"]) == index:
            return {"gateway": gateway, "interface": name, "metric": info["metric"], "index": index}
    raise RuntimeError(f"Interface with index {index} not found")


def _log_and_route(args, log_callback=None):
    cmd = "route " + " ".join(args)
    if log_callback:
        log_callback(f"Running: {cmd}")
    return subprocess.run(["route"] + args, capture_output=True, text=True)


def _log_and_netsh(args, log_callback=None):
    cmd = "netsh " + " ".join(args)
    if log_callback:
        log_callback(f"Running: {cmd}")
    return subprocess.run(["netsh"] + args, capture_output=True, text=True)


def set_default_route(gateway_ip, idx, metric=5, log_callback=None):
    idx_str = str(idx)

    for m in ("5", "10", "20"):
        cmd = ["change", "0.0.0.0", "mask", "0.0.0.0", gateway_ip, "metric", m, "if", idx_str]
        result = _log_and_route(cmd, log_callback)
        if result.returncode == 0:
            return

    cmd2 = ["add", "0.0.0.0", "mask", "0.0.0.0", gateway_ip, "if", idx_str, "metric", str(metric)]
    result = _log_and_route(cmd2, log_callback)
    if result.returncode == 0:
        return

    cmd3 = ["interface", "ipv4", "set", "route", "0.0.0.0/0", idx_str, gateway_ip, f"metric={metric}"]
    result = _log_and_netsh(cmd3, log_callback)
    if result.returncode != 0:
        raise RuntimeError(
            f"All route attempts failed. Last command stderr: {result.stderr.strip() or result.stdout.strip()}"
        )


def launch_app(app_path, adapter_name, adapters, log_callback=None):
    def log(msg):
        if log_callback:
            log_callback(msg)

    metric_snapshot = {}
    metric_changed = []
    original_route = None
    with _route_lock:
        try:
            metrics = get_adapter_metrics()
            primary = metrics.get(adapter_name)
            if not primary:
                raise RuntimeError(f"Adapter '{adapter_name}' not found in metrics")
            metric_snapshot = metrics

            log(f"Setting adapter {primary['idx']} to metric 5")
            set_adapter_metric(primary['idx'], 5)
            metric_changed.append(adapter_name)
            for name, info in metrics.items():
                if name != adapter_name:
                    log(f"Setting adapter {info['idx']} to metric 50")
                    set_adapter_metric(info['idx'], 50)
                    metric_changed.append(name)

            log(f"Looking up gateway for adapter: {adapter_name}")
            gw_info = get_adapter_gateway_and_idx(adapter_name)
            if not gw_info:
                raise RuntimeError("Could not find the default gateway for the selected adapter.")

            gateway = gw_info['gateway']
            gw_idx = gw_info['idx']
            log(f"Gateway: {gateway}, Index: {gw_idx}")

            original_route = get_current_default_route()
            log(f"Switching default route to {gateway} via {adapter_name}")
            set_default_route(gateway, gw_idx, 5, log)
            time.sleep(0.5)

            adapter_ip = adapters.get(adapter_name, {}).get("ip", "")
            if not adapter_ip:
                raise RuntimeError(f"No IP for adapter '{adapter_name}'")

            forcebindip = get_forcebindip_path()
            cmd = [forcebindip, "-i", adapter_ip, app_path]
            log(f"Launching: {' '.join(cmd)}")
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            log(f"Launched {os.path.basename(app_path)}")

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

            _pid = 0
            if target_proc:
                log(f"Monitoring {target_name} (PID {target_proc.pid})")
                target_proc.wait()
                _pid = target_proc.pid
            else:
                log("Target process not found, monitoring ForceBindIP launcher")
                proc.wait()
                _pid = proc.pid
            log("Process exited. Restoring network settings...")
            return _pid

        except Exception as e:
            log(f"ERROR: {e}")
            raise
        finally:
            for name in metric_changed:
                info = metric_snapshot.get(name)
                if info is not None:
                    try:
                        if info['metric'] is not None:
                            set_adapter_metric(info['idx'], info['metric'])
                        else:
                            set_metric_auto(info['idx'])
                    except Exception as restore_err:
                        log(f"Metric restore error for {name} (non-fatal): {restore_err}")
            if original_route:
                try:
                    set_default_route(original_route['gateway'], original_route['index'], original_route['metric'], log)
                except Exception as restore_err:
                    log(f"Route restore error (non-fatal): {restore_err}")