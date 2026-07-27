import os
import ssl
import shutil
import stat
import subprocess
import urllib.request
import zipfile

TOOLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools")
FORCEBINDIP_URL = "https://r1ch.net/assets/forcebindip/ForceBindIP-1.32.zip"
FORCEBINDIP_EXE = os.path.join(TOOLS_DIR, "ForceBindIP.exe")
FORCEBINDIP_DLL = os.path.join(TOOLS_DIR, "BindIP.dll")
FORCEBINDIP64_EXE = os.path.join(TOOLS_DIR, "ForceBindIP64.exe")
FORCEBINDIP64_DLL = os.path.join(TOOLS_DIR, "BindIP64.dll")


def _ensure_tools_dir():
    os.makedirs(TOOLS_DIR, exist_ok=True)


def _remove_readonly(func, path, excinfo):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def is_installed():
    return os.path.isfile(FORCEBINDIP_EXE) and os.path.isfile(FORCEBINDIP_DLL)


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