# Validation — October 3, 2026

## Background collector v0.4 — current installation

- All 79 tests passed locally and in Ubuntu CI, including a real MQTT broker,
  collector control socket, single collector ownership, bounded pause leases,
  shared GUI/history-download coordination and window reuse. Packaging,
  installation and demo checks also passed:
  [v0.4 CI run](https://github.com/tonibergholm/RuuviLinux/actions/runs/37119475497).
- Installed and enabled `ruuvilinux-collector.service` on the actual Omarchy
  machine. Fresh BLE readings and additional history samples arrived while
  no RuuviLinux desktop process was running. The collector uses no Qt window.
- The native RuuviOmarchy dropdown rendered with live readings and shared names
  and favorites. Activating its launcher with Enter opened the desktop GUI,
  whose footer confirmed attachment to the background collector. Activating
  the launcher again reused the same process and window.
- Closing that GUI through the compositor removed its window while the
  collector remained active. The user service is enabled for login.
- Existing tag-memory downloads remain available. Coordination with the new
  daemon is covered by a simulated transfer; another physical tag-memory
  transfer was not repeated for v0.4. The successful physical v0.3 transfer
  is recorded below.
- Collection requires an awake machine and logged-in user. Extended unattended
  operation, suspend/wake and production MQTT TLS credentials remain untested.

The sections below record earlier versions, including their deployment state
at the time. The v0.4 service replaces the earlier GUI-only collection setup.

## Automated checks (v0.1)

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
used by this MVP. Comparison against Ruuvi Station, successful sensor-memory downloads,
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
- Ubuntu CI passed all 62 tests including Mosquitto, plus the installer,
  desktop entry, demo rendering and package build:
  [v0.2 CI run](https://github.com/tonibergholm/RuuviLinux/actions/runs/37107548394).
- Omarchy installation upgraded to v0.2 and restarted in its Wayland desktop.
  The installed app received actual Gateway and Bridge messages over a
  temporary SSH-forwarded test broker, preserved retained-message age,
  converted pressure and shared the sensor identity. The test used an
  in-memory database; the normal app keeps the existing sensor database and
  resumes Bluetooth. No broker or collector service was installed.

## Tag history v0.3

- All 72 tests passed locally, including the real MQTT broker test. Coverage
  includes the official request vector, negative temperature and pressure units,
  missing values, partial/out-of-order fields, duplicate imports and persistence.
- Fake Bluetooth sessions verify subscribe/request/end-marker/disconnect and
  cancellation cleanup. A Qt test verifies the download action, ten-day chart
  and preservation of the latest live reading.
- After the user released the competing iOS connection, the actual Omarchy
  native download action succeeded. SQLite retained 1,693 samples spanning
  5.72 days, all with temperature, humidity and pressure populated. The user
  confirmed the native button works; existing names and favorites remain.
- Initial hardware attempts hit connection timeouts, a GATT notification error
  and a disconnect timeout. The app reports errors and retains partial samples.
  Standalone test sessions were followed by a successful native GUI transfer;
  no firmware or tag data was changed.

- Ubuntu CI passed all 69 initial v0.3 tests, demo rendering, installer and
  package checks: [CI run](https://github.com/tonibergholm/RuuviLinux/actions/runs/37110056745).
- Omarchy upgraded to v0.3.0; its native Wayland window shows the download
  button below the chart, and the existing sensor/history database is intact.
- A follow-up regression test verifies that an empty Bluetooth timeout
  exception produces a useful message about range, firmware and connections.

- Follow-up Ubuntu CI passed all 70 tests and packaging/install checks:
  [CI run](https://github.com/tonibergholm/RuuviLinux/actions/runs/37110281769).

- A complete Omarchy transfer initially displayed a failure because BlueZ
  notification/disconnect cleanup timed out after all 1,644 samples arrived.
  Disconnect now releases notifications directly, has a longer bounded wait,
  and reports cleanup warnings separately from successful transfers. Regression
  tests cover completed-transfer cleanup and preservation of original errors.
