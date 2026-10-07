import asyncio
from dataclasses import replace
import json
import tempfile
import time
from types import SimpleNamespace
import pytest
from ruuvilinux.collector import Collector, main as collector_main
from ruuvilinux.collector_client import control_path
from ruuvilinux.homeassistant import HomeAssistantPublisher, HomeAssistantSettings, collector_id
from ruuvilinux.protocol import decode_rawv2
from ruuvilinux.storage import Store

READING=decode_rawv2(bytes.fromhex('0512FC5394C37C0004FFFC040CAC364200CDCBB8334C884F'))
OK=SimpleNamespace(is_failure=False)


class Client:
    def __init__(self,*a,**kw):self.published=[];self.events=[];self.will=None;self.locked=[];self.owner=None;self.qos=[]
    def username_pw_set(self,*a):self.events.append('auth')
    def tls_set(self):self.events.append('tls')
    def will_set(self,*a,**kw):self.will=(a,kw)
    def reconnect_delay_set(self,**kw):pass
    def connect_async(self,*a,**kw):self.events.append('connect')
    def loop_start(self):pass
    def subscribe(self,topic,qos):self.events.append(topic);return 0,1
    def publish(self,topic,payload,qos=0,retain=False):
        self.published.append((topic,payload,retain));self.locked.append(self.owner.lock.locked() if self.owner else None);self.qos.append(qos);return SimpleNamespace(wait_for_publish=lambda t:None)
    def disconnect(self):self.events.append('disconnect')
    def loop_stop(self):pass
    def topics(self):return [p[0] for p in self.published]


def publisher(wall=None,**changes):
    clock=[1000.0];wall=wall or [1_700_000_010.0]
    ha=HomeAssistantPublisher(HomeAssistantSettings('broker',**changes),client_factory=Client,clock=lambda:clock[0],wall=lambda:wall[0])
    ha.client.owner=ha;ha.start();return ha,clock


def test_discovery_waits_for_connection_and_describes_device():
    ha,clock=publisher(username='u',password='p',tls=True)
    assert ha.client.will==(('ruuvilinux/collectors/default/status','offline'),{'qos':1,'retain':True})
    assert 'auth' in ha.client.events and 'tls' in ha.client.events
    ha.publish(READING.mac,'Kitchen',READING,-60,1_700_000_000)
    assert ha.client.published==[]  # queued until the broker accepts the connection
    ha.on_connect(ha.client,None,None,OK,None)
    assert 'homeassistant/status' in ha.client.events
    topics=ha.client.topics()
    assert topics==['ruuvilinux/collectors/default/status','homeassistant/device/ruuvilinux_cbb8334c884f/config','ruuvilinux/cbb8334c884f/state']
    assert [retain for _,_,retain in ha.client.published]==[True,True,False]  # expiring state is not retained
    config=json.loads(ha.client.published[1][1])
    assert config['device']['name']=='Kitchen' and config['device']['connections']==[['bluetooth','cb:b8:33:4c:88:4f']]
    assert config['origin']['name']=='RuuviLinux' and config['availability_topic']=='ruuvilinux/collectors/default/status'
    temperature=config['components']['temperature']
    assert temperature['platform']=='sensor' and temperature['device_class']=='temperature'
    assert temperature['unit_of_measurement']=='°C' and temperature['value_template']=='{{ value_json.temperature }}'
    assert temperature['unique_id']=='ruuvilinux_cbb8334c884f_temperature' and temperature['expire_after']==300
    assert config['components']['pressure']['device_class']=='atmospheric_pressure'
    assert config['components']['acceleration_x']['enabled_by_default'] is False
    assert all(c['expire_after']==300 for c in config['components'].values())  # including Last seen
    assert len({c['unique_id'] for c in config['components'].values()})==len(config['components'])
    state=json.loads(ha.client.published[2][1])
    assert state['temperature']==24.3 and state['pressure']==1000.44 and state['rssi']==-60
    assert state['last_seen']=='2023-11-14T22:13:20+00:00' and 'mac' not in state
    ha.stop()
    assert ha.client.published[-1]==('ruuvilinux/collectors/default/status','offline',True)


def test_state_is_throttled_rename_rediscovers_and_stale_is_ignored():
    ha,clock=publisher(interval=60);ha.on_connect(ha.client,None,None,OK,None)
    ha.publish(READING.mac,'Kitchen',READING,-60,1_700_000_000);count=len(ha.client.published)
    clock[0]+=10;ha.publish(READING.mac,'Kitchen',replace(READING,temperature=25),-60,1_700_000_001)
    assert len(ha.client.published)==count
    clock[0]+=50;ha.publish(READING.mac,'Kitchen',replace(READING,temperature=26),-60,1_700_000_002)
    assert json.loads(ha.client.published[-1][1])['temperature']==26
    clock[0]+=1;ha.publish(READING.mac,'Fridge',READING,-60,1_700_000_003)
    assert json.loads(ha.client.published[-2][1])['device']['name']=='Fridge'
    count=len(ha.client.published);clock[0]+=600
    ha.publish(READING.mac,'Fridge',READING,-60,1_699_999_000)  # older retained/out-of-order sample
    assert len(ha.client.published)==count


def test_home_assistant_restart_and_reconnect_republish_discovery():
    ha,clock=publisher();ha.on_connect(ha.client,None,None,OK,None)
    ha.publish(READING.mac,'Kitchen',READING,-60,1_700_000_000);ha.client.published.clear()
    ha.on_message(ha.client,None,SimpleNamespace(topic='homeassistant/status',payload=b'offline'))
    assert ha.client.published==[]
    ha.on_message(ha.client,None,SimpleNamespace(topic='homeassistant/status',payload=b'online'))
    assert ha.client.topics()==['homeassistant/device/ruuvilinux_cbb8334c884f/config','ruuvilinux/cbb8334c884f/state']
    ha.on_disconnect(ha.client,None,None,OK,None);ha.client.published.clear()
    ha.publish(READING.mac,'Kitchen',READING,-60,1_700_000_005);assert ha.client.published==[]
    ha.on_connect(ha.client,None,None,OK,None)
    assert 'homeassistant/device/ruuvilinux_cbb8334c884f/config' in ha.client.topics()


def test_expired_readings_are_never_resent_but_discovery_is():
    wall=[1_700_000_010.0];ha,clock=publisher(wall=wall,expire_after=300)
    ha.on_connect(ha.client,None,None,OK,None)
    ha.publish(READING.mac,'Kitchen',READING,-60,1_700_000_000)
    assert ha.client.topics()[-1]=='ruuvilinux/cbb8334c884f/state'
    wall[0]+=600;ha.client.published.clear()
    # Tag is gone longer than expire_after; birth and reconnect only rediscover.
    ha.on_message(ha.client,None,SimpleNamespace(topic='homeassistant/status',payload=b'online'))
    ha.on_disconnect(ha.client,None,None,OK,None);ha.on_connect(ha.client,None,None,OK,None)
    assert 'ruuvilinux/cbb8334c884f/state' not in ha.client.topics()
    assert ha.client.topics().count('homeassistant/device/ruuvilinux_cbb8334c884f/config')==2
    # An old reading arriving late (e.g. retained input) is not published either.
    ha.client.published.clear();ha.publish('AA:BB:CC:DD:EE:FF','Old',READING,-60,wall[0]-400)
    assert ha.client.topics()==['homeassistant/device/ruuvilinux_aabbccddeeff/config']
    # A fresh reading after that publishes normally.
    ha.publish('AA:BB:CC:DD:EE:FF','Old',READING,-60,wall[0]-1)
    assert ha.client.topics()[-1]=='ruuvilinux/aabbccddeeff/state'


def test_state_is_retained_only_without_expiry():
    ha,clock=publisher(expire_after=0);ha.on_connect(ha.client,None,None,OK,None)
    ha.publish(READING.mac,'Kitchen',READING,-60,1_000)  # very old, but expiry is disabled
    # Retained state has its own topic: enabling expiry later never subscribes to it.
    assert ha.client.published[-1][0]=='ruuvilinux/cbb8334c884f/state/retained' and ha.client.published[-1][2] is True
    assert ha.client.qos[-1]==1
    assert json.loads(ha.client.published[-2][1])['state_topic']=='ruuvilinux/cbb8334c884f/state/retained'


def test_expiring_state_uses_qos0_so_paho_never_resends_it():
    ha,clock=publisher();ha.on_connect(ha.client,None,None,OK,None)
    ha.publish(READING.mac,'Kitchen',READING,-60,1_700_000_000)
    topics=ha.client.topics()
    assert ha.client.qos[topics.index('ruuvilinux/cbb8334c884f/state')]==0
    assert ha.client.qos[topics.index('homeassistant/device/ruuvilinux_cbb8334c884f/config')]==1


def test_birth_topic_is_configured_separately_from_discovery_prefix():
    ha,clock=publisher(discovery_prefix='custom',status_topic='homeassistant/status')
    ha.on_connect(ha.client,None,None,OK,None)
    assert 'homeassistant/status' in ha.client.events and 'custom/status' not in ha.client.events
    ha.publish(READING.mac,'Kitchen',READING,-60,1_700_000_000);ha.client.published.clear()
    ha.on_message(ha.client,None,SimpleNamespace(topic='custom/status',payload=b'online'))
    assert ha.client.published==[]
    ha.on_message(ha.client,None,SimpleNamespace(topic='homeassistant/status',payload=b'online'))
    assert ha.client.topics()==['custom/device/ruuvilinux_cbb8334c884f/config','ruuvilinux/cbb8334c884f/state']


def test_connect_after_shutdown_never_publishes_online_or_state():
    ha,clock=publisher();ha.publish(READING.mac,'Kitchen',READING,-60,1_700_000_000)
    ha.stop()  # not yet connected: no offline publish needed
    ha.on_connect(ha.client,None,None,OK,None)  # connect callback that lost the race
    ha.flush(READING.mac,force=True)
    assert ha.client.published==[] and not ha.connected


def test_interval_may_equal_half_expiry_or_ignore_disabled_expiry():
    HomeAssistantSettings('broker',interval=150,expire_after=300).validate()
    HomeAssistantSettings('broker',interval=3600,expire_after=0).validate()


def test_collectors_have_distinct_stable_availability_topics(tmp_path):
    first,second=collector_id(tmp_path/'a.db'),collector_id(tmp_path/'b.db')
    assert first!=second and first==collector_id(tmp_path/'a.db')
    HomeAssistantSettings('broker',node_id=first).validate()
    ha=HomeAssistantPublisher(HomeAssistantSettings('broker',node_id=first),client_factory=Client)
    assert ha.availability=='ruuvilinux/collectors/'+first+'/status' and ha.client.will[0][0]==ha.availability
    assert ha.discovery('CB:B8:33:4C:88:4F','Kitchen')['availability_topic']==ha.availability


def test_publishes_are_serialized_with_their_snapshot():
    ha,clock=publisher();ha.on_connect(ha.client,None,None,OK,None)
    ha.publish(READING.mac,'Kitchen',READING,-60,1_700_000_000)
    ha.on_message(ha.client,None,SimpleNamespace(topic='homeassistant/status',payload=b'online'))
    clock[0]+=1;ha.publish(READING.mac,'Sauna',READING,-60,1_700_000_001)
    # Discovery and state go out while the lock that chose their snapshot is held.
    flushed=[locked for (topic,_,_),locked in zip(ha.client.published,ha.client.locked) if not topic.endswith('/status')]
    assert len(flushed)==6 and all(flushed)


def test_rejected_connection_reports_status():
    statuses=[]
    ha=HomeAssistantPublisher(HomeAssistantSettings('broker'),statuses.append,client_factory=Client);ha.start()
    ha.on_connect(ha.client,None,None,SimpleNamespace(is_failure=True),None)
    assert 'rejected' in statuses[-1] and ha.client.published==[]


@pytest.mark.parametrize('changes',[{'host':''},{'host':'mqtt://x'},{'port':0},{'discovery_prefix':'a/#'},
    {'base_topic':''},{'base_topic':'x/'},{'interval':-1},{'expire_after':-5},
    {'interval':200},{'interval':60,'expire_after':100},{'node_id':''},{'node_id':'a/b'},{'node_id':'#'},
    {'status_topic':''},{'status_topic':'ha/#'}])
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
            stamp=Store(database).sensor(READING.mac)['last_seen']
            MQTT.instance.reading(READING.mac,READING,-45,stamp);await asyncio.sleep(.01)  # retained redelivery: equal stamp
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


def test_shutdown_racing_connect_still_ends_offline():
    import threading
    ha,clock=publisher();stopper=[]
    def subscribe(topic,qos):
        # Shutdown starts on another thread while the connect callback is mid-way.
        thread=threading.Thread(target=ha.stop);thread.start();stopper.append(thread)
        thread.join(.2);return 0,1
    ha.client.subscribe=subscribe
    ha.on_connect(ha.client,None,None,OK,None);stopper[0].join(2)
    assert ha.client.published[-1]==('ruuvilinux/collectors/default/status','offline',True)


def test_denied_birth_subscription_reports_actionable_status():
    statuses=[]
    ha=HomeAssistantPublisher(HomeAssistantSettings('broker'),statuses.append,client_factory=Client);ha.start()
    ha.on_connect(ha.client,None,None,OK,None);assert statuses[-1]=='Home Assistant · publishing'
    ha.on_subscribe(ha.client,None,1,[OK],None);assert statuses[-1]=='Home Assistant · publishing'
    ha.on_subscribe(ha.client,None,1,[SimpleNamespace(is_failure=True)],None)
    assert 'denied reading homeassistant/status' in statuses[-1]
