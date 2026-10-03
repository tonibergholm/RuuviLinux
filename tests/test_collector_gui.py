import time
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication
from ruuvilinux.protocol import decode_rawv2
from ruuvilinux.storage import Store
from ruuvilinux.window import MainWindow


def test_gui_uses_daemon_pauses_for_download_and_leaves_it_running(tmp_path,monkeypatch):
    import ruuvilinux.window as gui
    app=QApplication.instance() or QApplication([])
    path=tmp_path/'sensors.db';store=Store(path)
    reading=decode_rawv2(bytes.fromhex('0512FC5394C37C0004FFFC040CAC364200CDCBB8334C884F'))
    identity=store.receive('tag',reading,-60,time.time())
    commands=[];state={'running':True,'paused':False,'source':'bluetooth','status':'Background collector · scanning'}
    def control(database,command='status',**arguments):
        commands.append((command,arguments))
        if command=='pause':state['paused']=True
        elif command=='resume':state['paused']=False
        return dict(state)
    monkeypatch.setattr(gui,'collector_request',control)
    class Worker(QThread):
        progress=Signal(str);result=Signal(object,str)
        def __init__(self,*args):super().__init__()
        def run(self):self.result.emit([],'')
    monkeypatch.setattr(gui,'LogWorker',Worker)
    window=MainWindow(store,start_scanning=False);window.start_scan()
    assert window.collector_active and window.worker is None
    window.name.setText('Unsaved name');window.poll_collector();assert window.name.text()=='Unsaved name'
    window.download_history()
    deadline=time.monotonic()+2
    while window.log_worker:
        app.processEvents();time.sleep(.01);assert time.monotonic()<deadline
    assert ('pause',{'timeout':8,'leaseSeconds':360}) in commands
    assert any(c[0]=='resume' for c in commands) and not state['paused']
    before=len(commands);window.close();app.processEvents()
    assert len(commands)==before,'Closing the GUI must not stop or pause its daemon'
