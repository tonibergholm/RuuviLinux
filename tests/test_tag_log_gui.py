import threading,time
from PySide6.QtCore import QThread,Signal
from PySide6.QtWidgets import QApplication
from ruuvilinux.storage import Store
from ruuvilinux.protocol import decode_rawv2
from ruuvilinux.tag_logs import LogSample
from ruuvilinux.window import MainWindow


def test_download_button_imports_history_without_changing_live_sensor(monkeypatch):
    app=QApplication.instance() or QApplication([])
    class Worker(QThread):
        progress=Signal(str);result=Signal(object,str)
        def __init__(self,identity,adapter,parent):super().__init__(parent);self.stop_event=threading.Event()
        def stop(self):self.stop_event.set()
        def run(self):
            self.result.emit([LogSample(int(time.time())-3*86400,18,50,1000)],'')
    monkeypatch.setattr('ruuvilinux.window.LogWorker',Worker)
    store=Store(':memory:');r=decode_rawv2(bytes.fromhex('0512FC5394C37C0004FFFC040CAC364200CDCBB8334C884F'))
    identity=store.receive('tag',r,-50,time.time());store.rename(identity,'Kitchen');store.favorite(identity,True)
    original=store.sensor(identity);window=MainWindow(store,start_scanning=False)
    window.download_button.click()
    end=time.monotonic()+5
    while window.log_worker is not None and time.monotonic()<end:app.processEvents();time.sleep(.02)
    assert window.log_worker is None
    assert window.period_picker.currentData()==864000
    assert len(window.chart.points)==2
    assert 'Imported 1 new samples' in window.log_status.text()
    assert store.sensor(identity)==original
    assert window.pause.isEnabled() and window.mqtt_button.isEnabled()
    window.close();app.processEvents()
