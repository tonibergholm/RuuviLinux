import json,time
from types import SimpleNamespace
import pytest
from ruuvilinux.mqtt_input import decode_mqtt_message, MQTTInput,MQTTSettings
from ruuvilinux.storage import Store
RAW="0201061BFF99040512FC5394C37C0004FFFC040CAC364200CDCBB8334C884F"
def message(**changes):
    obj={"data":RAW,"ts":"100000","rssi":-60}; obj.update(changes)
    return json.dumps(obj).encode()


def test_gateway_tlv_timestamp_and_pressure():
    sample=decode_mqtt_message(message(),"ruuvi/CB:B8:33:4C:88:4F",now=100001)
    assert sample.reading.temperature==pytest.approx(24.3)
    assert sample.reading.pressure==pytest.approx(1000.44)
    assert sample.timestamp==100000 and sample.identity=="CB:B8:33:4C:88:4F"
    # Company AD structure may be located after arbitrary other AD fields.
    moved="0303AAFE"+RAW[6:]
    assert decode_mqtt_message(message(data=moved),"topic",now=100001).reading==sample.reading


def test_bridge_decoded_json():
    obj={"data_format":5,"mac":"cbb8334c884f","timestamp":100000,"rssi":-70,
         "temperature":24.3,"humidity":53.49,"pressure":100044,"batteryVoltage":2.977}
    sample=decode_mqtt_message(json.dumps(obj).encode(),"ruuvi/anything",now=100001)
    assert sample.identity=="CB:B8:33:4C:88:4F"
    assert sample.reading.pressure==pytest.approx(1000.44)
    assert sample.reading.sequence is None


@pytest.mark.parametrize("payload",[b"not json",b"[]",b'{"state":"online"}',b"x"*65537,
    message(ts="NaN"),message(ts=-1),message(ts=100400),message(data="FF"),message(data="not hex"),message(rssi=True)])
def test_bad_or_unrelated_messages(payload):
    assert decode_mqtt_message(payload,"topic",now=100001) is None


def test_retained_and_out_of_order_dont_refresh_or_replace():
    store=Store(":memory:"); sample=decode_mqtt_message(message(),"topic",now=100001)
    store.receive(sample.identity,sample.reading,sample.rssi,sample.timestamp)
    store.receive(sample.identity,sample.reading,-40,sample.timestamp)
    store.receive(sample.identity,sample.reading,-30,sample.timestamp-60)
    saved=store.sensor(sample.identity)
    assert saved["last_seen"]==100000 and saved["rssi"]==-60
    assert len(store.history(sample.identity,100001))==1
    store.close()


@pytest.mark.parametrize("topic",["a/#/b","abc+","#foo", "", "a\0b"])
def test_invalid_filters(topic):
    with pytest.raises(ValueError): MQTTSettings("localhost",topic=topic).validate()


def test_auth_tls_subscribe_and_status_callbacks():
    events=[]
    class Client:
        def __init__(self,*a,**kw): events.append(kw)
        def username_pw_set(self,*a): events.append("auth")
        def tls_set(self): events.append("tls")
        def reconnect_delay_set(self,**kw): pass
        def connect_async(self,*a,**kw): events.append("connect")
        def loop_start(self): events.append("loop")
        def subscribe(self,*a,**kw): events.append(a[0]); return 0,1
        def disconnect(self): events.append("stop")
        def loop_stop(self): pass
    input=MQTTInput(MQTTSettings("host",username="u",password="p",tls=True),client_factory=Client)
    statuses=[]; input.status_changed.connect(statuses.append)
    input.start()
    reason=SimpleNamespace(is_failure=False)
    input.connected(input.client,None,None,reason,None)
    input.subscribed(input.client,None,1,[reason],None)
    assert "auth" in events and "tls" in events and "ruuvi/#" in events
    assert "subscribed" in statuses[-1]
    input.subscribed(input.client,None,1,[SimpleNamespace(is_failure=True)],None)
    assert "rejected" in statuses[-1]
    input.stop()
