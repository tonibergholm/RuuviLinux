import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import time
from dataclasses import replace
import pytest
from PySide6.QtWidgets import QApplication
from ruuvilinux.protocol import decode_rawv2
from ruuvilinux.storage import Store
from ruuvilinux.window import MainWindow

@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_demo_gui_name_favorites_history_and_missing_readings(app):
    store=Store(":memory:")
    window=MainWindow(store,demo=True); window.show(); app.processEvents()
    assert window.list.count()==2
    assert window.chart.points
    selected=window.selected
    window.name.setText("Office"); window.rename()
    assert store.sensor(selected)["name"]=="Office"
    window.only_favorites.setChecked(True)
    assert window.list.count()==1
    window.set_favorite(False)
    assert window.list.count()==0 and window.pages.currentIndex()==0
    window.only_favorites.setChecked(False)
    r=decode_rawv2(bytes.fromhex("058000FFFFFFFF800080008000FFFFFFFFFFFFFFFFFFFFFF"))
    window.receive("AA:BB:CC:DD:EE:FF",r,-80,time.time())
    assert window.list.count()==3
    assert not window.grab().isNull()
    window.close(); app.processEvents()


def test_live_updates_preserve_unsaved_name_and_sensor_identity(app):
    store=Store(":memory:"); window=MainWindow(store,start_scanning=False)
    r=decode_rawv2(bytes.fromhex("0512FC5394C37C0004FFFC040CAC364200CDCBB8334C884F"))
    window.receive("a",r,-55,time.time())
    window.name.setText("Typing a name")
    window.receive("a",replace(r,temperature=25),-60,time.time())
    assert window.name.text()=="Typing a name"
    assert "25.0" in window.cards["temperature"].text()
    assert window.list.count()==1
    window.metric_picker.setCurrentIndex(2)
    assert window.chart.unit=="hPa"
    window.close(); app.processEvents()


def test_worker_pause_resume_and_close_while_scanning(app,monkeypatch):
    import asyncio
    import ruuvilinux.scanner as scanner
    async def fake_session(stop,on_reading,on_status,**options):
        on_status("Scanning test adapter")
        while not stop.is_set(): await asyncio.sleep(0.01)
    monkeypatch.setattr(scanner,"scan_session",fake_session)
    window=MainWindow(Store(":memory:"),start_scanning=False); window.show()
    def wait_for(predicate):
        deadline=time.monotonic()+2
        while not predicate() and time.monotonic()<deadline:
            app.processEvents(); time.sleep(0.01)
        assert predicate()
    window.start_scan()
    wait_for(lambda: "test adapter" in window.status.text())
    window.toggle_scan()
    wait_for(lambda: window.worker is None)
    assert window.pause.text()=="Resume scanning"
    window.toggle_scan()
    wait_for(lambda: "test adapter" in window.status.text())
    window.close()
    wait_for(lambda: window.worker is None)
    assert not window.isVisible()
