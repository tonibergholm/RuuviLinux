# RuuviLinux

An independent, open-source **native Qt desktop app** for RuuviTags on Omarchy / Arch Linux. Sister project: [RuuviMac](https://github.com/tonibergholm/RuuviMac).

![Demo interface with generated sensor readings](docs/demo-preview.png)

*Demo preview; desktop styling follows the Qt environment.*

## MVP features

- Live BLE discovery using Bleak's BlueZ D-Bus backend. No pairing, Ruuvi account, internet connection, or Gateway needed during use.
- Temperature, humidity, pressure, voltage, acceleration, movement count, TX power, and signal strength.
- Saved device names and favorites, favorite filter, and stale-reading indicator.
- Persistent SQLite history, up to one sample per minute and 1,440 samples per tag. Temperature, humidity, and pressure charts show the last 24 hours, with gaps for missing data / long outages.
- Pause / resume scanning, actionable Bluetooth error messages, safe asynchronous shutdown.
- Native desktop launcher for Omarchy's **Super + Space** menu.
- Demo mode with generated data; demo never accesses your sensor database or Bluetooth.

Supports **RuuviTag RAWv2 / format 5** only in v0.1. Ruuvi Air, legacy formats, cloud sync, alerts, sensor-memory downloads, and firmware updates are outside this release.

## Install on Omarchy / Arch

Requires Python 3.11+, BlueZ 5.55+, a Bluetooth LE adapter, and a running graphical desktop. Dependencies download from PyPI at installation. The native Qt interface supports Wayland (Hyprland) and X11; no browser or web server is involved.

```sh
sudo pacman -S --needed git python uv bluez bluez-utils
sudo systemctl enable --now bluetooth.service
bluetoothctl power on

git clone https://github.com/tonibergholm/RuuviLinux.git
cd RuuviLinux
./scripts/install-omarchy.sh
```

Open **RuuviLinux** from Super + Space, or run `~/.local/bin/ruuvilinux`. Bring a RAWv2 RuuviTag nearby; it appears automatically. Edit a name and press Enter or Save name; use Favorite to save it in the favorite list.

The installer creates an isolated Python environment under `${XDG_DATA_HOME:-~/.local/share}/ruuvilinux/venv`, a launcher under `~/.local/bin`, a desktop entry, and an icon. It does not change Hyprland configuration, enable background services for the app, or run Bluetooth scanning as root. Re-run the installer after pulling updates.

If the Wayland Qt plugin cannot load, check missing shared-library messages; install the matching desktop runtime dependencies. `QT_QPA_PLATFORM=xcb ~/.local/bin/ruuvilinux` is a fallback when XWayland is available (Arch may also need `libxcb`, `xcb-util-cursor`, and `libxkbcommon-x11`). Prefer the default native Wayland backend on Hyprland.

## Run from source / try the demo

```sh
uv venv --python python3
uv pip install --python .venv/bin/python -e '.[dev]'
.venv/bin/ruuvilinux
.venv/bin/ruuvilinux --demo
.venv/bin/ruuvilinux --adapter hci1
```

`--adapter` selects a Linux adapter if multiple are installed. This project targets Linux; demo / test mode can also run on macOS for development. Use RuuviMac for supported macOS BLE operation.

## History and storage

Data lives in `${XDG_DATA_HOME:-~/.local/share}/ruuvilinux/sensors.sqlite3`. Names, favorites, latest readings, and collected history are committed in SQLite transactions. Use `--database /path/to/sensors.sqlite3` to choose another location. Quit the app before copying / moving its database.

History contains local receipt timestamps and measurements observed while the app is running, awake, and scanning. Repeat measurement sequences are skipped; samples are spaced by at least one minute. Old history is pruned on incoming readings and filtered out of charts immediately. A sleeping computer or paused app cannot collect data, and this MVP does not backfill readings from tag memory. Previously saved sensors stay visible after relaunch; readings become stale after 30 seconds without an advertisement. Identity uses the RAWv2 MAC, falling back to the BlueZ device address if unavailable.

## Bluetooth troubleshooting

- Check `systemctl status bluetooth.service`, `bluetoothctl show`, and `rfkill list bluetooth`. If blocked, enable Bluetooth in your desktop controls or use `rfkill unblock bluetooth` as appropriate.
- If the app shows a BlueZ NotReady / adapter error, turn Bluetooth on and press Resume scanning. After an adapter power cycle or BlueZ restart, pause/resume scanning to re-establish discovery.
- A D-Bus access error should be resolved through the distribution's BlueZ / session permissions. Run the app as your normal logged-in desktop user; it does not require raw HCI socket capabilities or root.
- Tags broadcasting formats other than 5 are ignored. Compare the tag's mode and readings with Ruuvi Station.
- SQLite storage errors are displayed. If the database is corrupt, quit and move it aside to start fresh; preserve it first if you need its data.

## Tests and validation

```sh
.venv/bin/python -m pytest -q
QT_QPA_PLATFORM=offscreen .venv/bin/ruuvilinux --smoke-test --screenshot /tmp/ruuvilinux-demo.png
.venv/bin/python -m build
```

Tests cover official protocol vectors and unavailable values, every truncated payload length, wrong manufacturers / unsupported formats, history deduplication / retention, name and favorite persistence, XDG paths, failed scanner startup / shutdown, advertisement dispatch, and GUI interactions. GitHub Actions runs these checks on Ubuntu Linux.

A passing simulated test does **not** establish physical BlueZ radio behavior or Hyprland integration. See `VALIDATION.md` for what was executed. Hardware smoke test on Omarchy: discover a real RAWv2 tag, compare readings with Ruuvi Station, rename/favorite, wait for minute samples, relaunch, pause/resume, move out of range, turn Bluetooth off/on, and close while scanning.

## Protocol and library research

- [Official Ruuvi RAWv2 specification](https://docs.ruuvi.com/communication/bluetooth-advertisements/data-format-5-rawv2): this small Python decoder implements the documented wire format and is tested against its published valid, minimum, maximum, and unavailable vectors. Ruuvi's Swift BTKit is used in the Mac sibling; it is not a Linux Python dependency.
- [Official Ruuvi BTKit](https://github.com/ruuvi/BTKit) and [Bluetooth connection protocols](https://docs.ruuvi.com/communication/bluetooth-connection): reference implementations / future sensor-memory transfers. No Ruuvi library code or logos are copied here.
- [Bleak scanner API](https://bleak.readthedocs.io/en/latest/api/scanner.html) / [Linux backend](https://bleak.readthedocs.io/en/latest/backends/linux.html): BlueZ D-Bus discovery, manufacturer data keyed by company ID. Bleak strips company bytes; `manufacturer_data[0x0499]` is the payload, unlike the Mac CoreBluetooth field.
- [Omarchy](https://omarchy.org/) / [GUI manual](https://omarchy.org/manual/guis/): desktop launcher integration uses a regular freedesktop entry, with no changes to the user's desktop setup.
- [Official Ruuvi Cloud API](https://github.com/ruuvi/ruuvi.cloudapi.yaml): cloud support is deferred; this MVP stays local.

## Licensing

Project code is MIT (`LICENSE`). The original SVG application icon is included under the same license. Bleak is MIT. PySide6 / Qt remain under their own [Qt for Python licensing terms](https://doc.qt.io/qtforpython-6/licenses.html), including LGPLv3 / GPLv3 / commercial options; installing this source app does not relicense them. This app uses QtCore, QtGui, and QtWidgets via PySide6-Essentials and does not use Qt Charts. If redistributing bundled runtime libraries, preserve notices and meet applicable license obligations. Ruuvi and Omarchy trademarks belong to their owners. This project is independent and is not an official Ruuvi or Omarchy product.
