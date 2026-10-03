"""Install a freedesktop launcher without requiring elevated privileges."""
import os
from pathlib import Path
import shutil
import sys


def install(executable: Path, icon_source: Path, data_dir: Path):
    applications = data_dir / "applications"
    icons = data_dir / "icons/hicolor/scalable/apps"
    applications.mkdir(parents=True, exist_ok=True)
    icons.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(icon_source, icons / "org.ruuvilinux.app.svg")
    # Desktop Exec is not a shell. Quote reserved characters and escape % field codes.
    path = str(executable.resolve()).replace("%", "%%")
    for char in ('\\', '"', '`', '$'):
        path = path.replace(char, "\\" + char)
    # Desktop string-value parsing consumes backslashes before Exec argument parsing.
    path = path.replace('\\', '\\\\')
    desktop = applications / "org.ruuvilinux.app.desktop"
    desktop.write_text(f"""[Desktop Entry]
Type=Application
Name=RuuviLinux
Comment=Live readings from nearby RuuviTags
Exec="{path}"
Icon=org.ruuvilinux.app
Terminal=false
Categories=Utility;Monitor;
StartupWMClass=org.ruuvilinux.app
Keywords=Ruuvi;Bluetooth;temperature;humidity;sensor;
""")
    return desktop


if __name__ == "__main__":
    base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    install(Path(sys.argv[1]), Path(sys.argv[2]), base)
