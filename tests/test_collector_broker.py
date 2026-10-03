"""Exercise the actual daemon process, local control socket and MQTT broker."""
import json
import os
import subprocess
import sys
import tempfile
import time
import paho.mqtt.client as mqtt
import pytest
from ruuvilinux.collector_client import request, control_path
from ruuvilinux.storage import Store


@pytest.mark.skipif(not os.environ.get('RUUVILINUX_MQTT_TEST_PORT'),reason='no test broker supplied')
def test_real_daemon_process_keeps_collecting_without_gui(tmp_path,monkeypatch):
    port=int(os.environ['RUUVILINUX_MQTT_TEST_PORT']);database=tmp_path/'daemon.sqlite3'
    with tempfile.TemporaryDirectory(prefix='ruuvi-',dir='/tmp') as runtime:
        monkeypatch.setenv('XDG_RUNTIME_DIR',runtime)
        process=subprocess.Popen([sys.executable,'-m','ruuvilinux.collector','--database',str(database),
                                  '--mqtt-host','127.0.0.1','--mqtt-port',str(port),'--mqtt-topic','ruuvi-daemon-test/#'],
                                 stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        publisher=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        publisher.connect('127.0.0.1',port);publisher.loop_start()
        def wait(predicate):
            deadline=time.monotonic()+8
            while not predicate():
                assert process.poll() is None and time.monotonic()<deadline
                time.sleep(.02)
        try:
            wait(lambda:control_path(database).exists())
            wait(lambda:'subscribed' in request(database)['status'])
            stamp=time.time()-90
            payload={'data':'0201061BFF99040512FC5394C37C0004FFFC040CAC364200CDCBB8334C884F','ts':stamp,'rssi':-60}
            publisher.publish('ruuvi-daemon-test/tag',json.dumps(payload),qos=1).wait_for_publish(5)
            def saved():
                store=Store(database)
                try:return store.db.execute('SELECT count(*) FROM sensors').fetchone()[0]>0
                finally:store.close()
            wait(saved)
            store=Store(database);sensor=store.sensors()[0]
            assert sensor['last_seen']==stamp and sensor['latest']['pressure']==1000.44
            assert store.history(sensor['id'],time.time());store.close()
            assert request(database,'pause',timeout=8)['paused']
            assert not request(database,'resume',timeout=8)['paused']
            # Closing the only desktop-style data reader did not stop the daemon.
            assert process.poll() is None
        finally:
            publisher.disconnect();publisher.loop_stop()
            process.terminate();process.wait(timeout=10)
        assert process.returncode==0 and not control_path(database).exists()
