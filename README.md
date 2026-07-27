# NetSplit

A modern, dark-themed desktop application for Windows that routes individual applications through specific network adapters using ForceBindIP.

## Features

- Dark-themed UI built with CustomTkinter
- List and rename network adapters
- Add applications and assign them to specific adapters
- Launch applications through assigned adapters using ForceBindIP
- Real-time network traffic monitoring per adapter
- System activity log

## Requirements

- Python 3.8+
- Windows (requires Administrator privileges for routing)

## Setup

1. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Launch the application:
   ```
   python main.py
   ```
   Or double-click `start.bat`.

The app will auto-elevate to Administrator and download ForceBindIP on first run.

## Usage

1. **Refresh Adapters** – Scans for available network adapters.
2. **Add App** – Browse for an `.exe` file to add to the application list.
3. **Assign** – Use the dropdown in each app row to select a network adapter.
4. **Launch** – Click the Launch button to run an app through its assigned adapter.
5. **Rename** – Double-click an adapter or click the pencil icon to set a nickname.

## Notes

- Routing changes require Administrator privileges.
- ForceBindIP is downloaded automatically from r1ch.net.
