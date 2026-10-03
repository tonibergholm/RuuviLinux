"""Real broker tests enabled with RUUVILINUX_MQTT_TEST_PORT."""
import json,os,time
import paho.mqtt.client as paho
import pytest
from PySide6.QtWidgets import QApplication
from ruuvilinux.mqtt_input import MQTTInput,MQTTSettings
from ruuvilinux.storage import Store
from ruuvilinux.window import MainWindow

@pytest.mark.skipif(not os.environ.get("RUUVILINUX_MQTT_TEST_PORT"),reason="no test broker supplied")
def test_real_broker_gateway_bridge_and_retained_timestamp():
    app=QApplication.instance() or QApplication([])
    window=MainWindow(Store(":memory:"),start_scanning=False)
    topic="ruuvi-tests/CB:B8:33:4C:88:4F"
    port=int(os.environ["RUUVILINUX_MQTT_TEST_PORT"])
    window.use_mqtt(MQTTSettings("127.0.0.1",port,"ruuvi-tests/#"))
    def wait(predicate):
        deadline=time.monotonic()+8
        while not predicate() and time.monotonic()<deadline:
            app.processEvents(); time.sleep(.02)
        assert predicate()
    wait(lambda:"subscribed" in window.status.text())
    publisher=paho.Client(paho.CallbackAPIVersion.VERSION2)
    publisher.connect("127.0.0.1",port); publisher.loop_start()
    timestamp=time.time()-90
    payload=json.dumps({"data":"0201061BFF99040512FC5394C37C0004FFFC040CAC364200CDCBB8334C884F","ts":timestamp,"rssi":-60})
    publisher.publish(topic,payload,qos=1,retain=True).wait_for_publish(5)
    wait(lambda:window.list.count()==1)
    identity=window.selected
    assert window.store.sensor(identity)["last_seen"]==pytest.approx(timestamp)
    assert "No recent signal" in window.last_seen.text()
    # A freshly received retained message must retain its original age.
    window.use_mqtt(MQTTSettings("127.0.0.1",port,"ruuvi-tests/#"))
    wait(lambda:"subscribed" in window.status.text())
    assert window.store.sensor(identity)["last_seen"]==pytest.approx(timestamp)
    bridge={"data_format":5,"mac":identity,"timestamp":time.time(),"rssi":-50,"temperature":28,"pressure":100000}
    publisher.publish(topic,json.dumps(bridge),qos=1).wait_for_publish(5)
    wait(lambda:window.store.sensor(identity)["latest"]["temperature"]==28)
    assert window.list.count()==1 and window.cards["pressure"].text()=="1000.0 hPa"
    publisher.publish(topic,b"",retain=True).wait_for_publish(5)
    publisher.disconnect(); publisher.loop_stop()
    window.close(); app.processEvents()
