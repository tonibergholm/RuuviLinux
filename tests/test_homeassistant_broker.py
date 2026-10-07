"""Real collector process publishing Home Assistant discovery through a broker."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import paho.mqtt.client as mqtt
import pytest
from ruuvilinux.collector_client import request, control_path


@pytest.mark.skipif(not os.environ.get('RUUVILINUX_MQTT_TEST_PORT'),reason='no test broker supplied')
def test_collector_publishes_discovery_state_and_availability(tmp_path,monkeypatch):
    port=int(os.environ['RUUVILINUX_MQTT_TEST_PORT']);database=tmp_path/'daemon.sqlite3'
    prefix='ha-test-'+str(os.getpid());base='ruuvi-ha-test-'+str(os.getpid())
    received={};lock=threading.Lock()
    def message(client,userdata,msg):
        with lock: received[msg.topic]=msg.payload
    watcher=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2);watcher.on_message=message
    watcher.connect('127.0.0.1',port);watcher.subscribe([(prefix+'/#',1),(base+'/#',1)]);watcher.loop_start()
    with tempfile.TemporaryDirectory(prefix='ruuvi-',dir='/tmp') as runtime:
        monkeypatch.setenv('XDG_RUNTIME_DIR',runtime)
        process=subprocess.Popen([sys.executable,'-m','ruuvilinux.collector','--database',str(database),
            '--mqtt-host','127.0.0.1','--mqtt-port',str(port),'--mqtt-topic',base+'-input/#',
            '--ha-host','127.0.0.1','--ha-port',str(port),'--ha-discovery-prefix',prefix,'--ha-base-topic',base,'--ha-node-id','test-node'],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        def wait(predicate):
            deadline=time.monotonic()+8
            while not predicate():
                assert time.monotonic()<deadline
                time.sleep(.02)
        config=f'{prefix}/device/ruuvilinux_cbb8334c884f/config';state=f'{base}/cbb8334c884f/state'
        try:
            wait(lambda:control_path(database).exists())
            wait(lambda:'subscribed' in request(database)['status'] and request(database)['homeassistant']['status']=='Home Assistant · publishing')
            assert received.get(base+'/collectors/test-node/status')==b'online'
            payload={'data':'0201061BFF99040512FC5394C37C0004FFFC040CAC364200CDCBB8334C884F','ts':time.time()-5,'rssi':-60}
            watcher.publish(base+'-input/tag',json.dumps(payload),qos=1).wait_for_publish(5)
            wait(lambda:config in received and state in received)
            discovery=json.loads(received[config])
            assert discovery['state_topic']==state and discovery['device']['name']=='Ruuvi 88:4F'
            assert json.loads(received[state])['temperature']==24.3
            # A Home Assistant restart (birth message) republishes discovery.
            del received[config]
            watcher.publish(prefix+'/status','online',qos=1).wait_for_publish(5)
            wait(lambda:config in received)
        finally:
            process.terminate();process.wait(timeout=10)
        wait(lambda:received.get(base+'/collectors/test-node/status')==b'offline')
        assert process.returncode==0
        for topic in (config,state,base+'/collectors/test-node/status'):  # clear retained test messages
            watcher.publish(topic,b'',qos=1,retain=True).wait_for_publish(5)
        watcher.disconnect();watcher.loop_stop()
