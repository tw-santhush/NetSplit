# 🌐 NetSplit

**NetSplit v3.1.0** is a Windows desktop application that lets you route specific applications (like Chrome, Steam, Discord) through specific network adapters (Wi‑Fi, USB tethering, Ethernet) – all from a modern, dark‑themed dashboard.

Whether you want to download large files through a mobile hotspot while keeping your games on a low‑latency Wi‑Fi connection, or simply control which app uses which network, NetSplit makes it effortless.

---

## ✨ Features

- ✅ **Add apps (file picker)** – Browse and add any `.exe` with a native file picker.
- ✅ **Assign apps to adapters (dropdown)** – Select which network adapter each app uses.
- ✅ **Launch apps (routing works)** – Launch any assigned app with its dedicated network route.
- ✅ **Live network monitor** – Real‑time download/upload speeds per adapter and per app.
- ✅ **Rename adapters** – Give adapters custom nicknames (e.g., "Home Wi‑Fi", "USB Tether").
- ✅ **System activity log** – Timestamped log of all actions.
- ✅ **One‑click start (start.bat)** – Launch with a single batch file.

---

## 🖼️ Screenshot

*(Add a screenshot of your app here – you can replace this with an actual image later.)*

![NetSplit Dashboard](./screenshot.png)

---

## 📋 Requirements

- **Windows 10 / 11** (64‑bit recommended)
- **Python 3.10+** (if running from source)
- **Administrator privileges** (required to modify Windows routing tables and launch ForceBindIP)

---

## 🛠️ Installation & Setup

### 1. Clone the repository

```bash
git clone https://github.com/tw-santhush/NetSplit.git
cd NetSplit
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

This installs:
- `pywebview` – for the native desktop window
- `psutil` – for network statistics and process management
- `pywin32` – for Windows API calls (icon extraction, routing)
- `Pillow` – for image processing (icon fallbacks)

### 3. Run the app

```bash
python main.py
```

> **Note:** The app must be run with **administrator privileges** to modify network routes. Right‑click your terminal and select **"Run as administrator"**, or run the `start.bat` file (which you can create to auto‑elevate).

---

## 🚀 Usage Guide

### Add an Application
1. Click the **"Add App"** button.
2. Browse and select any `.exe` file (e.g., `chrome.exe`).
3. The app appears in the list with its original icon.

### Assign a Network
1. In the application row, click the **"Assigned Network"** dropdown.
2. Select an adapter from the list (e.g., "Wi‑Fi", "USB Tethering").
3. The rule is saved immediately – the **"Launch"** button becomes active.

### Launch the App
- Click **"Launch"** – the application opens and all its traffic is forced through the selected adapter.
- The **System Activity** log confirms the launch.

### Monitor Traffic
- The **Traffic** column shows real‑time download/upload speeds for each running app.
- The **Network Adapters** panel also displays aggregate speeds for each adapter.

### Refresh Adapters
- Click **"↻ Refresh Adapters"** at the bottom of the Network Adapters panel to re‑scan for newly connected adapters (e.g., a USB Wi‑Fi dongle).

### Rename an Adapter
- Double‑click an adapter in the list and enter a custom nickname (e.g., "Home Wi‑Fi").

---

## 🗂️ Configuration

All settings are stored in `config.json` (created automatically in the app directory):

```json
{
  "apps": [
    { "path": "C:/.../chrome.exe", "name": "chrome.exe", "icon": "data:image/png;base64,..." }
  ],
  "rules": [
    { "app_path": "C:/.../chrome.exe", "adapter_name": "Wi-Fi", "adapter_ip": "192.168.1.100" }
  ],
  "nicknames": {
    "Wi-Fi": "Home Wi-Fi",
    "Ethernet 2": "USB Tether"
  }
}
```

You can edit this file manually, but the app provides a UI for all settings.

---

## 📦 Packaging as a Single `.exe`

To share the app with friends who don't have Python installed, you can package it with **PyInstaller**.

```bash
# Install PyInstaller
pip install pyinstaller

# Create a single .exe
pyinstaller --onefile --windowed --name NetSplit main.py

# The .exe will be in the dist/ folder
```

Your friends can just double‑click `NetSplit.exe` – no Python needed.

---

## 🧠 How It Works (Under the Hood)

NetSplit uses a combination of techniques to route traffic:

- **ForceBindIP** – A lightweight tool that forces a specific application to bind to a specific IP address (and thus a specific network adapter). The app auto‑downloads it on first run.
- **Windows Routing Table** – Temporarily adjusts the default route so that traffic from the launched app is directed through the chosen adapter.
- **psutil** – Polls network statistics every second to provide live speed updates.
- **PyWebView** – Provides a native window and allows JavaScript to call Python functions directly – no API mismatches, no CORS, no Electron bloat.

---

## ⚠️ Known Issues

- **Administrator privileges required** – NetSplit modifies Windows routing tables, so it must be run as admin.
- **ForceBindIP** – The app auto-downloads ForceBindIP on first run. Some antivirus software may flag it as suspicious; this is a false positive.
- **Adapter detection** – Virtual adapters (Hyper‑V, VMware, VirtualBox) are intentionally hidden to avoid confusion.
- **Single‑instance routing** – Only one app can be actively routed at a time. Routing resets when the app exits.

---

## 🤝 Contributing

Contributions are welcome! If you have ideas for:
- Bandwidth limiting per app
- System tray integration
- Dark/light theme toggle
- Export/Import rules

Feel free to open an issue or submit a pull request.

---

## 📄 License

This project is open‑source and available under the [MIT License](LICENSE).

---

## 🙏 Credits

- [ForceBindIP](https://r1ch.net/projects/forcebindip) – the core injection tool.
- [PyWebView](https://pywebview.flowrl.com/) – for the lightweight desktop window.
- Built with ❤️ by [tw‑santhush](https://github.com/tw-santhush).

---

**Enjoy full control over your network traffic!** 🚀