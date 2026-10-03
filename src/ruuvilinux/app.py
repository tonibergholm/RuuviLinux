import argparse
import sys
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from . import __version__
from .storage import Store
from .window import MainWindow


def main(argv=None):
    parser = argparse.ArgumentParser(description="Native RuuviTag viewer for Omarchy / Linux")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--demo", action="store_true", help="Show generated data without Bluetooth or persistent storage")
    parser.add_argument("--adapter", help="Linux Bluetooth adapter, e.g. hci0")
    parser.add_argument("--database", type=Path, help="Override the SQLite database location")
    parser.add_argument("--smoke-test", action="store_true", help="Render demo UI and exit without Bluetooth")
    parser.add_argument("--screenshot", type=Path, help="Save a demo screenshot (requires --demo or --smoke-test)")
    args = parser.parse_args(argv)
    if args.screenshot and not (args.demo or args.smoke_test):
        parser.error("--screenshot requires --demo or --smoke-test")
    app = QApplication([sys.argv[0]])
    app.setApplicationName("RuuviLinux")
    app.setDesktopFileName("org.ruuvilinux.app")
    app.setOrganizationName("RuuviLinux")
    try:
        # Demo never reads or writes the real sensor database.
        store = Store(":memory:" if args.demo or args.smoke_test else args.database)
    except Exception as error:
        QMessageBox.critical(None, "Could not open sensor database", str(error))
        return 1
    window = MainWindow(store, demo=args.demo or args.smoke_test, adapter=args.adapter)
    window.show()
    def capture():
        if args.screenshot:
            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            if not window.grab().save(str(args.screenshot)):
                print("Could not save screenshot", file=sys.stderr)
                app.exit(1)
                return
        if args.smoke_test:
            window.close()
    if args.screenshot or args.smoke_test:
        QTimer.singleShot(700, capture)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
