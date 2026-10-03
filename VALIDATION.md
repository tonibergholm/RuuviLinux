# Validation — October 3, 2026

Local development host is Apple Silicon macOS, not an Omarchy installation.
Python 3.12, Bleak 3.0.2, and PySide6-Essentials 6.11.2 are used for local checks.

Protocol, SQLite, fake BLE adapter, and native GUI tests are automated. Physical
BlueZ discovery and Hyprland window integration require an Omarchy hardware
smoke test. Demo and headless tests do not access Bluetooth or live sensor data.

Linux CI also runs protocol/storage/scanner/GUI tests, headless demo rendering,
and source/wheel builds on Ubuntu 24.04. The initial implementation is submitted for Linux CI validation.

Local result: 42 tests passed; the generated-data desktop rendered successfully;
source archive and platform-independent Python wheel built. The headless Qt
preview was inspected. The Mac workspace marked dependency files hidden; moving
the temporary environment outside the output folder resolved plugin discovery.
