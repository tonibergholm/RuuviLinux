"""Keep BlueZ / asyncio off the Qt GUI thread. One loop per scan session."""
import asyncio
import threading
import time
from bleak import BleakScanner
from PySide6.QtCore import QThread, Signal
from .protocol import decode_advertisement


async def scan_session(stop: threading.Event, on_reading, on_status, scanner_factory=BleakScanner, adapter: str | None = None):
    def detected(device, advertisement):
        reading = decode_advertisement(advertisement.manufacturer_data)
        if reading is not None:
            on_reading(device.address, reading, advertisement.rssi, time.time())

    options = {"detection_callback": detected}
    if adapter:
        options["adapter"] = adapter
    scanner = scanner_factory(**options)
    started = False
    try:
        await asyncio.wait_for(scanner.start(), timeout=15)
        started = True
        on_status("Scanning for nearby RuuviTags")
        while not stop.is_set():
            await asyncio.sleep(0.15)
    finally:
        # A partially started backend may also own a discovery session.
        try:
            await asyncio.wait_for(scanner.stop(), timeout=5)
        except Exception:
            if started and not stop.is_set():
                raise


def error_message(error: Exception) -> str:
    return (f"Bluetooth unavailable: {error}. Check Bluetooth power, rfkill, and the BlueZ service. "
            "Then press Resume scanning. Run this app as your regular desktop user.")


class ScannerWorker(QThread):
    reading_received = Signal(str, object, int, float)
    status_changed = Signal(str)

    def __init__(self, adapter=None, parent=None):
        super().__init__(parent)
        self.adapter = adapter
        self.stop_event = threading.Event()

    def stop(self):
        self.stop_event.set()

    def run(self):
        try:
            asyncio.run(scan_session(self.stop_event, self.reading_received.emit,
                                     self.status_changed.emit, adapter=self.adapter))
        except Exception as error:
            self.status_changed.emit(error_message(error))
