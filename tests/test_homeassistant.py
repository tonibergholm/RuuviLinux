import asyncio
from dataclasses import replace
import json
import tempfile
import time
from types import SimpleNamespace
import pytest
from ruuvilinux.collector import Collector, main as collector_main
from ruuvilinux.collector_client import control_path
from ruuvilinux.homeassistant import HomeAssistantPublisher, HomeAssistantSettings
from ruuvilinux.protocol import decode_rawv2
from ruuvilinux.storage import Store

READING=decode_rawv2(bytes.fromhex('0512FC5394C37C0004FFFC040CAC364200CDCBB8334C884F'))
OK=SimpleNamespace(is_failure=False)


class Client:
    def __init__(self,*a,**kw):self.published=[];self.events=[];self.will=None
    def username_pw_set(self,*a):self.events.append('auth')
    def tls_set(self):self.events.append('tls')
    def will_set(self,*a,**kw):self.will=(a,kw)
    def reconnect_delay_set(self,**kw):pass
    def connect_async(self,*a,**kw):self.events.append('connect')
    def loop_start(self):pass
    def subscribe(self,topic,qos):self.events.append(topic);return 0,1
    def publish(self,topic,payload,qos=0,retain=False):
        self.published.append((topic,payload,retain));return SimpleNamespace(wait_for_publish=lambda t:None)
    def disconnect(self):self.events.append('disconnect')
    def loop_stop(self):pass
    def topics(self):return [p[0] for p in self.published]


def publisher(**changes):
    clock=[1000.0]
    ha=HomeAssistantPublisher(HomeAssistantSettings('broker',**changes),client_factory=Client,clock=lambda:clock[0])
    ha.start();return ha,clock


def test_discovery_waits_for_connection_and_describes_device():
    ha,clock=publisher(username='u',password='p',tls=True)
    assert ha.client.will==(('ruuvilinux/collector/status','offline'),{'qos':1,'retain':True})
    assert 'auth' in ha.client.events and 'tls' in ha.client.events
    ha.publish(READING.mac,'Kitchen',READING,-60,1_700_000_000)
    assert ha.client.published==[]  # queued until the broker accepts the connection
    ha.on_connect(ha.client,None,None,OK,None)
    assert 'homeassistant/status' in ha.client.events
    topics=ha.client.topics()
    assert topics==['ruuvilinux/collector/status','homeassistant/device/ruuvilinux_cbb8334c884f/config','ruuvilinux/cbb8334c884f/state']
    assert all(retain for _,_,retain in ha.client.published)
    config=json.loads(ha.client.published[1][1])
    assert config['device']['name']=='Kitchen' and config['device']['connections']==[['bluetooth','cb:b8:33:4c:88:4f']]
    assert config['origin']['name']=='RuuviLinux' and config['availability_topic']=='ruuvilinux/collector/status'
    temperature=config['components']['temperature']
    assert temperature['platform']=='sensor' and temperature['device_class']=='temperature'
    assert temperature['unit_of_measurement']=='°C' and temperature['value_template']=='{{ value_json.temperature }}'
    assert temperature['unique_id']=='ruuvilinux_cbb8334c884f_temperature' and temperature['expire_after']==300
    assert config['components']['pressure']['device_class']=='atmospheric_pressure'
    assert config['components']['acceleration_x']['enabled_by_default'] is False
    assert len({c['unique_id'] for c in config['components'].values()})==len(config['components'])
    state=json.loads(ha.client.published[2][1])
    assert state['temperature']==24.3 and state['pressure']==1000.44 and state['rssi']==-60
    assert state['last_seen']=='2023-11-14T22:13:20+00:00' and 'mac' not in state
    ha.stop()
    assert ha.client.published[-1]==('ruuvilinux/collector/status','offline',True)


def test_state_is_throttled_rename_rediscovers_and_stale_is_ignored():
    ha,clock=publisher(interval=60);ha.on_connect(ha.client,None,None,OK,None)
    ha.publish(READING.mac,'Kitchen',READING,-60,100);count=len(ha.client.published)
    clock[0]+=10;ha.publish(READING.mac,'Kitchen',replace(READING,temperature=25),-60,101)
    assert len(ha.client.published)==count
    clock[0]+=50;ha.publish(READING.mac,'Kitchen',replace(READING,temperature=26),-60,102)
    assert json.loads(ha.client.published[-1][1])['temperature']==26
    clock[0]+=1;ha.publish(READING.mac,'Fridge',READING,-60,103)
    assert json.loads(ha.client.published[-2][1])['device']['name']=='Fridge'
    count=len(ha.client.published);clock[0]+=600
    ha.publish(READING.mac,'Fridge',READING,-60,50)  # older retained/out-of-order sample
    assert len(ha.client.published)==count


def test_home_assistant_restart_and_reconnect_republish_discovery():
    ha,clock=publisher();ha.on_connect(ha.client,None,None,OK,None)
    ha.publish(READING.mac,'Kitchen',READING,-60,100);ha.client.published.clear()
    ha.on_message(ha.client,None,SimpleNamespace(topic='homeassistant/status',payload=b'offline'))
    assert ha.client.published==[]
    ha.on_message(ha.client,None,SimpleNamespace(topic='homeassistant/status',payload=b'online'))
    assert ha.client.topics()==['homeassistant/device/ruuvilinux_cbb8334c884f/config','ruuvilinux/cbb8334c884f/state']
    ha.on_disconnect(ha.client,None,None,OK,None);ha.client.published.clear()
    ha.publish(READING.mac,'Kitchen',READING,-60,200);assert ha.client.published==[]
    ha.on_connect(ha.client,None,None,OK,None)
    assert 'homeassistant/device/ruuvilinux_cbb8334c884f/config' in ha.client.topics()


def test_rejected_connection_reports_status():
    statuses=[]
    ha=HomeAssistantPublisher(HomeAssistantSettings('broker'),statuses.append,client_factory=Client);ha.start()
    ha.on_connect(ha.client,None,None,SimpleNamespace(is_failure=True),None)
    assert 'rejected' in statuses[-1] and ha.client.published==[]


@pytest.mark.parametrize('changes',[{'host':''},{'host':'mqtt://x'},{'port':0},{'discovery_prefix':'a/#'},
    {'base_topic':''},{'base_topic':'x/'},{'interval':-1},{'expire_after':-5}])
def test_invalid_settings(changes):
    with pytest.raises(ValueError):HomeAssistantSettings(**({'host':'broker'}|changes)).validate()
    assert 'password' not in HomeAssistantSettings('b',password='secret').public()


def test_cli_rejects_invalid_home_assistant_settings(capsys):
    with pytest.raises(SystemExit):collector_main(['--ha-host','mqtt://broker'])
    assert 'hostname' in capsys.readouterr().err


def test_collector_publishes_accepted_readings_with_saved_names(tmp_path,monkeypatch):
    database=tmp_path/'sensors.db';publishers=[]
    class Publisher:
        def __init__(self,settings,on_status):self.on_status=on_status;self.calls=[];self.stopped=False;publishers.append(self)
        def start(self):self.on_status('Home Assistant · publishing')
        def publish(self,*args):self.calls.append(args)
        def stop(self):self.stopped=True
    class MQTT:
        def __init__(self,settings,on_reading,on_status):self.reading=on_reading;MQTT.instance=self
        def start(self):pass
        def stop(self):pass
    from ruuvilinux.mqtt_backend import MQTTSettings
    with tempfile.TemporaryDirectory(prefix='ruuvi-',dir='/tmp') as runtime:
        monkeypatch.setenv('XDG_RUNTIME_DIR',runtime)
        async def scenario():
            stop=asyncio.Event();collector=Collector(database,mqtt_factory=MQTT,ha_factory=Publisher)
            task=asyncio.create_task(collector.run(stop,MQTTSettings('broker'),HomeAssistantSettings('broker')))
            path=control_path(database)
            while not path.exists():await asyncio.sleep(.01)
            await asyncio.sleep(.01)
            MQTT.instance.reading(READING.mac,READING,-60,time.time()-30);await asyncio.sleep(.01)
            store=Store(database);store.rename(READING.mac,'Sauna');store.close()
            MQTT.instance.reading(READING.mac,READING,-55,time.time());await asyncio.sleep(.01)
            MQTT.instance.reading(READING.mac,READING,-50,time.time()-600);await asyncio.sleep(.01)  # stale: not published
            reader,writer=await asyncio.open_unix_connection(str(path))
            writer.write(b'{"command":"status"}\n');await writer.drain()
            status=json.loads(await reader.readline());writer.close();await writer.wait_closed()
            stop.set();await task;return status
        status=asyncio.run(scenario())
    calls=publishers[0].calls
    assert [c[1] for c in calls]==['Ruuvi 88:4F','Sauna'] and [c[3] for c in calls]==[-60,-55]
    assert status['homeassistant']=={'enabled':True,'status':'Home Assistant · publishing'}
    assert publishers[0].stopped


def test_settings_from_environment_file_variables(monkeypatch):
    import ruuvilinux.collector as collector
    captured={}
    monkeypatch.setattr(collector,'asyncio',SimpleNamespace(run=lambda coroutine:(coroutine.close(),None)[1]))
    for key,value in {'HOST':'ha.local','PORT':'8883','USERNAME':'ruuvi','PASSWORD':'secret','TLS':'true','INTERVAL':'15'}.items():
        monkeypatch.setenv('RUUVILINUX_HA_'+key,value)
    original=collector.HomeAssistantSettings
    def capture(*args):
        captured['settings']=original(*args);return captured['settings']
    monkeypatch.setattr(collector,'HomeAssistantSettings',capture)
    assert collector.main([])==0
    settings=captured['settings']
    assert (settings.host,settings.port,settings.username,settings.password,settings.tls,settings.interval)==('ha.local',8883,'ruuvi','secret',True,15)
    assert collector.main(['--ha-port','1883'])==0 and captured['settings'].port==1883
