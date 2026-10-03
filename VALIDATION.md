# Validation — October 3, 2026

## Automated checks

- Local macOS development environment: 42 tests passed, headless Qt demo rendered,
  source archive and platform-independent Python wheel built.
- Ubuntu 24.04 GitHub Actions: 42 tests passed; headless demo, source/wheel build,
  Linux installer, installed launcher, and desktop-file validation passed.
  [Successful CI run](https://github.com/tonibergholm/RuuviLinux/actions/runs/37106084931).
- Protocol vectors, every truncated payload length, missing-value sentinels,
  manufacturer framing, SQLite retention/deduplication/name/favorite persistence,
  scanner cleanup, GUI controls, and worker pause/resume/shutdown are tested.

## Actual Omarchy machine

The app was installed as a normal desktop user on x86_64 Omarchy / Arch Linux
with a Hyprland Wayland session, using Python 3.12.14, Bleak 3.0.2,
PySide6-Essentials 6.11.2, and the machine's powered BlueZ adapter.

- Installer completed; freedesktop entry validated; desktop demo rendered under
  the actual Wayland session and exited successfully.
- Native GUI launched in the user's desktop session through a transient user
  unit. The unit remains running so the app can be used immediately. Nothing
  was enabled to start the app automatically at login.
- Real BLE scanner received and decoded multiple RAWv2 packets from a nearby
  physical RuuviTag and stopped its own discovery session successfully.
- All 42 tests also passed on this Omarchy machine.
- The running GUI saved the real tag and two minute-spaced history samples in
  SQLite; the first observed spacing was 70.7 seconds (radio arrival is intermittent).
- The public preview contains generated demo readings only, not personal live
  readings or the physical tag's identity.

The current desktop portal logged an app-ID registration warning; native
Wayland rendering and BLE readings still succeeded. Portal features are not
used by this MVP. Comparison against Ruuvi Station, sensor-memory downloads,
long unattended runs, suspend/wake, and Bluetooth power-cycle behavior were
not tested on physical hardware. Automated tests use fake scan sessions for
failure / shutdown paths and do not establish those additional radio behaviors.

## MQTT v0.2

- Local development: 62 tests passed including a real loopback broker and Qt
  window ingestion. Gateway raw and RuuviBridge decoded messages resolve to
  one sensor; source timestamps, retained-message age, duplicate/out-of-order
  protection, pressure conversion, credentials/TLS configuration, and broker
  subscription rejection are covered.
- Credentials/TLS setup is unit tested; a production authenticated/TLS broker
  was not used. Passwords are session-only.
- CI now includes a Mosquitto broker integration test.
