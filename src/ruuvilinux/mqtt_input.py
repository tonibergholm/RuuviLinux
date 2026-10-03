"""Gateway raw advertisements and RuuviBridge decoded JSON over MQTT 3.1.1."""
from dataclasses import dataclass
import json
import math
import re
import time
import threading
import uuid
from PySide6.QtCore import QObject, Signal
import paho.mqtt.client as mqtt
from .protocol import Reading, decode_rawv2, COMPANY_ID


def mac(value):
    if not isinstance(value,str): return None
    compact=value.replace(":", "").replace("-", "")
    if not re.fullmatch(r"[0-9a-fA-F]{12}",compact): return None
    return ":".join(compact[i:i+2].upper() for i in range(0,12,2))


def number(value):
    if isinstance(value,bool): return None
    try: v=float(value)
    except (ValueError,TypeError): return None
    return v if math.isfinite(v) else None


def integer(value):
    v=number(value)
    return int(v) if v is not None and abs(v)<=100000 and v.is_integer() else None


def manufacturer_payload(data: bytes):
    if len(data)==26 and data[:2]==b"\x99\x04": return data[2:]
    index=0
    while index<len(data):
        length=data[index]; index+=1
        if length==0: break
        if index+length>len(data): return None
        kind=data[index]; contents=data[index+1:index+length]; index+=length
        if kind==255 and contents[:2]==b"\x99\x04": return contents[2:]
    return None


@dataclass(frozen=True)
class MQTTReading:
    identity: str
    reading: Reading
    rssi: int
    timestamp: float


def decode_mqtt_message(payload: bytes, topic: str, now=None):
    if len(payload)>65536: return None
    try: obj=json.loads(payload)
    except (ValueError,UnicodeError): return None
    if not isinstance(obj,dict): return None
    timestamp=number(obj.get("ts",obj.get("timestamp",obj.get("gwts"))))
    arrival=time.time() if now is None else now
    if timestamp is None or timestamp<=0 or timestamp>arrival+300: return None
    rssi=integer(obj.get("rssi"))
    if rssi is None or not -127<=rssi<=20: return None
    if isinstance(obj.get("data"),str):
        try: raw=bytes.fromhex(obj["data"])
        except ValueError: return None
        data=manufacturer_payload(raw)
        reading=decode_rawv2(data) if data is not None else None
        if reading is None: return None
        identity=reading.mac or mac(topic.split("/")[-1])
    elif integer(obj.get("data_format"))==5:
        identity=mac(obj.get("mac"))
        get=lambda key:number(obj.get(key))
        pressure=get("pressure")
        reading=Reading(get("temperature"),get("humidity"),None if pressure is None else pressure/100,
            get("accelerationX"),get("accelerationY"),get("accelerationZ"),get("batteryVoltage"),
            integer(obj.get("txPower")),integer(obj.get("movementCounter")),integer(obj.get("measurementSequenceNumber")),identity)
    else: return None
    if identity is None: return None
    return MQTTReading(identity,reading,int(rssi),timestamp)


@dataclass
class MQTTSettings:
    host: str
    port: int=1883
    topic: str="ruuvi/#"
    username: str=""
    password: str=""
    tls: bool=False

    def validate(self):
        if not self.host.strip() or "://" in self.host or not 1<=self.port<=65535:
            raise ValueError("Enter a broker hostname and a port between 1 and 65535.")
        parts=self.topic.split("/")
        if not self.topic or len(self.topic.encode())>65535 or "\0" in self.topic:
            raise ValueError("Enter a valid MQTT topic filter.")
        for index,part in enumerate(parts):
            if ("+" in part and part!="+") or ("#" in part and (part!="#" or index!=len(parts)-1)):
                raise ValueError("Use + for one full topic level, or # as the last level.")


class MQTTInput(QObject):
    reading_received=Signal(str,object,int,float)
    status_changed=Signal(str)

    def __init__(self,settings,parent=None,client_factory=mqtt.Client):
        super().__init__(parent)
        settings.validate(); self.settings=settings; self.running=False
        self.client=client_factory(mqtt.CallbackAPIVersion.VERSION2,client_id="ruuvilinux-"+uuid.uuid4().hex,
                                   protocol=mqtt.MQTTv311)
        if settings.username: self.client.username_pw_set(settings.username,settings.password)
        if settings.tls: self.client.tls_set()  # system CA validation; no insecure fallback
        self.client.reconnect_delay_set(min_delay=1,max_delay=30)
        self.client.on_connect=self.connected
        self.client.on_subscribe=self.subscribed
        self.client.on_connect_fail=lambda c,u:self.status_changed.emit("MQTT broker unavailable; retrying…") if self.running else None
        self.client.on_disconnect=self.disconnected
        self.client.on_message=self.message

    def start(self):
        self.running=True; self.status_changed.emit("Connecting to MQTT…")
        self.client.connect_async(self.settings.host.strip(),self.settings.port,keepalive=30)
        self.client.loop_start()

    def connected(self,client,userdata,flags,reason,properties):
        if not self.running: return
        if reason.is_failure:
            self.status_changed.emit("MQTT connection rejected; check credentials and broker permissions.")
            return
        result,_=client.subscribe(self.settings.topic,qos=1)
        if result!=mqtt.MQTT_ERR_SUCCESS: self.status_changed.emit("MQTT subscription request failed.")
        else: self.status_changed.emit("MQTT connected; subscribing…")

    def subscribed(self,client,userdata,mid,reasons,properties):
        if not self.running: return
        if any(r.is_failure for r in reasons): self.status_changed.emit("MQTT subscription rejected by broker.")
        else: self.status_changed.emit("MQTT subscribed · "+self.settings.topic)

    def disconnected(self,client,userdata,flags,reason,properties):
        if self.running: self.status_changed.emit("MQTT disconnected; reconnecting…")

    def message(self,client,userdata,message):
        if not self.running: return
        decoded=decode_mqtt_message(message.payload,message.topic)
        if decoded:
            self.reading_received.emit(decoded.identity,decoded.reading,decoded.rssi,decoded.timestamp)

    def stop(self):
        self.running=False
        self.client.disconnect()
        threading.Thread(target=self.client.loop_stop,daemon=True).start()
