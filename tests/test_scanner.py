import asyncio
import threading
from types import SimpleNamespace
import pytest
from ruuvilinux.scanner import scan_session, error_message
VALID = bytes.fromhex("0512FC5394C37C0004FFFC040CAC364200CDCBB8334C884F")


def test_scanner_callback_framing_and_shutdown():
    stop = threading.Event(); readings=[]; statuses=[]; instances=[]
    class FakeScanner:
        def __init__(self,**options): self.options=options; self.stopped=False; instances.append(self)
        async def start(self):
            callback = self.options["detection_callback"]
            callback(SimpleNamespace(address="AA:BB"),SimpleNamespace(manufacturer_data={0x1234:VALID},rssi=-70))
            callback(SimpleNamespace(address="AA:BB"),SimpleNamespace(manufacturer_data={0x0499:VALID},rssi=-60))
            stop.set()
        async def stop(self): self.stopped=True
    asyncio.run(scan_session(stop,lambda *args:readings.append(args),statuses.append,FakeScanner,"hci1"))
    assert len(readings)==1
    assert readings[0][0]=="AA:BB" and readings[0][1].temperature==pytest.approx(24.3)
    assert readings[0][2]==-60
    assert instances[0].options["adapter"]=="hci1"
    assert instances[0].stopped
    assert "Scanning" in statuses[0]


def test_failed_start_cleans_up_and_reports_error():
    instances=[]
    class FailedScanner:
        def __init__(self,**options): self.stopped=False; instances.append(self)
        async def start(self): raise RuntimeError("org.bluez.Error.NotReady")
        async def stop(self): self.stopped=True
    with pytest.raises(RuntimeError):
        asyncio.run(scan_session(threading.Event(),lambda *args:None,lambda s:None,FailedScanner))
    assert instances[0].stopped
    assert "BlueZ" in error_message(RuntimeError("NotReady"))


def test_stop_on_exception_after_start():
    stop=threading.Event(); instances=[]
    class FakeScanner:
        def __init__(self,**options): self.stopped=False; instances.append(self)
        async def start(self): pass
        async def stop(self): self.stopped=True
    def broken_status(s): raise ValueError("test failure")
    with pytest.raises(ValueError): asyncio.run(scan_session(stop,lambda *a:None,broken_status,FakeScanner))
    assert instances[0].stopped
