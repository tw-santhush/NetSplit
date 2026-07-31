import psutil
import socket
import win32com.client


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
    stats = psutil.net_if_stats()
    adapters = {}
    for name, addrs in psutil.net_if_addrs().items():
        nic_stat = stats.get(name)
        if not nic_stat or not nic_stat.isup:
            continue

        name_lower = name.lower()
        if any(kw in name_lower for kw in ["loopback", "pseudo", "virtual"]):
            continue

        ipv4 = None
        for addr in addrs:
            if addr.family == socket.AF_INET:
                ipv4 = addr.address
                break
        if not ipv4 or ipv4.startswith("169.254."):
            continue

        is_wireless = False
        if name in wmi_nics:
            wmi_nic = wmi_nics[name]
            desc = getattr(wmi_nic, 'Description', None) or ""
            desc_lower = desc.lower()
            aid = getattr(wmi_nic, 'AdapterTypeId', None)
            if any(kw in desc_lower for kw in ["virtual", "hyper-v", "vmware", "virtualbox", "pseudo", "loopback"]):
                continue
            is_wireless = (aid == 9) or ('wireless' in desc_lower or 'wi-fi' in name_lower or 'wlan' in name_lower)

        label = "Wi-Fi" if is_wireless else ("Ethernet" if name in wmi_nics else "Unknown")
        adapters[name] = {"ip": ipv4, "type": label}
    return adapters