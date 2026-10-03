import asyncio
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import time
import tempfile
import pytest
from types import SimpleNamespace
from ruuvilinux.collector import Collector
from ruuvilinux.collector_client import control_path
from ruuvilinux.mqtt_backend import MQTTSettings
from ruuvilinux.protocol import decode_rawv2
from ruuvilinux.storage import Store

RAW=bytes.fromhex('0512FC5394C37C0004FFFC040CAC364200CDCBB8334C884F')

@pytest.fixture
def runtime(monkeypatch):
    # macOS Unix sockets have a short path limit; pytest's full path exceeds it.
    with tempfile.TemporaryDirectory(prefix='ruuvi-',dir='/tmp') as folder:
        monkeypatch.setenv('XDG_RUNTIME_DIR',folder)
        yield folder


async def exchange(path, **message):
    reader,writer=await asyncio.open_unix_connection(str(path))
    writer.write(json.dumps(message).encode()+b'\n');await writer.drain()
    result=json.loads(await reader.readline())
    writer.close();await writer.wait_closed()
    return result


async def wait(predicate):
    deadline=time.monotonic()+2
    while not predicate():
        assert time.monotonic()<deadline
        await asyncio.sleep(.01)


def test_daemon_persistence_pause_lease_and_single_owner(tmp_path,runtime):
    database=tmp_path/'sensors.db';events=[]
    class Scanner:
        def __init__(self,detection_callback,**options):self.callback=detection_callback
        async def start(self):
            events.append('start')
            self.callback(SimpleNamespace(address='tag'),SimpleNamespace(manufacturer_data={0x499:RAW},rssi=-60))
        async def stop(self):events.append('stop')
    async def scenario():
        stop=asyncio.Event();collector=Collector(database,scanner_factory=Scanner)
        task=asyncio.create_task(collector.run(stop));path=control_path(database)
        await wait(lambda:path.exists() and events==['start'])
        assert (path.stat().st_mode & 0o777)==0o600
        store=Store(database);identity=store.sensors()[0]['id'];store.rename(identity,'Kitchen');store.favorite(identity,True);store.close()
        status=await exchange(path,command='status');assert status['source']=='bluetooth' and not status['paused']
        duplicate=Collector(database,scanner_factory=Scanner)
        try: await duplicate.run(asyncio.Event())
        except RuntimeError as error: assert 'already owns' in str(error)
        else: assert False,'Second collector acquired the database'
        assert path.exists()
        status=await exchange(path,command='pause',leaseSeconds=.08)
        assert status['paused'] and events[-1]=='stop'
        await wait(lambda:events.count('start')==2)
        assert not (await exchange(path,command='status'))['paused']
        assert 'error' in await exchange(path,command='unknown')
        stop.set();await task
        assert events[-1]=='stop' and not path.exists()
        store=Store(database);saved=store.sensor(identity)
        assert saved['name']=='Kitchen' and saved['favorite']
        assert saved['latest']['temperature']==24.3
        assert store.history(identity,time.time());store.close()
    asyncio.run(scenario())


def test_mqtt_collector_runs_without_gui_and_keeps_source_timestamps(tmp_path,runtime):
    database=tmp_path/'sensors.db';transports=[]
    class MQTT:
        def __init__(self,settings,on_reading,on_status):
            self.reading=on_reading;self.status=on_status;self.stopped=False;transports.append(self)
        def start(self):self.status('MQTT subscribed')
        def stop(self):self.stopped=True
    async def scenario():
        stop=asyncio.Event();collector=Collector(database,mqtt_factory=MQTT)
        task=asyncio.create_task(collector.run(stop,MQTTSettings('broker')));path=control_path(database)
        await wait(lambda:path.exists() and transports)
        stamp=time.time()-90;reading=decode_rawv2(RAW)
        transports[0].reading(reading.mac,reading,-60,stamp)
        await asyncio.sleep(.01)
        store=Store(database);assert store.sensor(reading.mac)['last_seen']==stamp;store.close()
        assert (await exchange(path,command='status'))['source']=='mqtt'
        await exchange(path,command='pause');assert transports[0].stopped
        transports[0].reading(reading.mac,replace(reading,temperature=99),-20,time.time())
        await asyncio.sleep(.01)
        store=Store(database);assert store.sensor(reading.mac)['latest']['temperature']==24.3;store.close()
        await exchange(path,command='resume');await wait(lambda:len(transports)==2)
        stop.set();await task;assert transports[1].stopped
    asyncio.run(scenario())


def test_collector_import_does_not_load_qt():
    subprocess.run([sys.executable,'-c',"import sys,ruuvilinux.collector; assert not any(m.startswith('PySide6') for m in sys.modules)"],check=True)
