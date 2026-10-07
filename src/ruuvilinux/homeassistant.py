"""Home Assistant MQTT discovery publisher for the headless collector.

Each RuuviTag becomes one Home Assistant device through device-based discovery:
https://www.home-assistant.io/integrations/mqtt/#device-discovery-payload
"""
from dataclasses import asdict, dataclass
import json
import re
import threading
import time
import uuid
import paho.mqtt.client as mqtt
from . import __version__

# key, name, device_class, unit, state_class, precision, enabled by default, diagnostic
ENTITIES = (
    ("temperature", "Temperature", "temperature", "°C", "measurement", 2, True, False),
    ("humidity", "Humidity", "humidity", "%", "measurement", 2, True, False),
    ("pressure", "Pressure", "atmospheric_pressure", "hPa", "measurement", 2, True, False),
    ("voltage", "Battery voltage", "voltage", "V", "measurement", 3, True, True),
    ("rssi", "Signal strength", "signal_strength", "dBm", "measurement", 0, True, True),
    ("movement", "Movement counter", None, None, "total_increasing", 0, True, False),
    ("acceleration_x", "Acceleration X", None, "g", "measurement", 3, False, True),
    ("acceleration_y", "Acceleration Y", None, "g", "measurement", 3, False, True),
    ("acceleration_z", "Acceleration Z", None, "g", "measurement", 3, False, True),
    ("tx_power", "TX power", "signal_strength", "dBm", None, 0, False, True),
)


def topic_id(identity):
    return re.sub(r"[^0-9a-z]", "", identity.lower()) or "unknown"


@dataclass
class HomeAssistantSettings:
    host: str
    port: int = 1883
    username: str = ""
    password: str = ""
    tls: bool = False
    discovery_prefix: str = "homeassistant"
    base_topic: str = "ruuvilinux"
    interval: float = 60
    expire_after: int = 300

    def validate(self):
        if not self.host.strip() or "://" in self.host or not 1 <= self.port <= 65535:
            raise ValueError("Enter a Home Assistant broker hostname and a port between 1 and 65535.")
        for topic in (self.discovery_prefix, self.base_topic):
            if not topic or any(c in topic for c in "+#\0") or topic.startswith("/") or topic.endswith("/"):
                raise ValueError("Home Assistant topics need plain levels without wildcards.")
        if not 0 <= self.interval <= 3600:
            raise ValueError("Home Assistant publish interval must be 0–3600 seconds.")
        if not 0 <= self.expire_after <= 86400:
            raise ValueError("Home Assistant expiry must be 0–86400 seconds.")

    def public(self):
        return {k: v for k, v in asdict(self).items() if k != "password"}


class HomeAssistantPublisher:
    """Thread-safe: publish() may be called from asyncio, paho callbacks run on paho's thread."""
    def __init__(self, settings, on_status=lambda message: None, client_factory=mqtt.Client, clock=time.monotonic, wall=time.time):
        settings.validate(); self.settings = settings; self.on_status = on_status; self.clock = clock; self.wall = wall
        self.running = False; self.connected = False; self.lock = threading.Lock()
        self.sensors = {}  # identity -> {"name", "state", "announced", "sent"}
        self.availability = f"{settings.base_topic}/collector/status"
        self.client = client_factory(mqtt.CallbackAPIVersion.VERSION2, client_id="ruuvilinux-ha-" + uuid.uuid4().hex,
                                     protocol=mqtt.MQTTv311)
        if settings.username: self.client.username_pw_set(settings.username, settings.password)
        if settings.tls: self.client.tls_set()  # system CA validation; no insecure fallback
        self.client.will_set(self.availability, "offline", qos=1, retain=True)
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        self.client.on_connect = self.on_connect
        self.client.on_connect_fail = lambda c, u: self.status("Home Assistant broker unavailable; retrying…")
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message

    def status(self, message):
        if self.running: self.on_status(message)

    def start(self):
        self.running = True; self.status("Home Assistant · connecting to MQTT…")
        self.client.connect_async(self.settings.host.strip(), self.settings.port, keepalive=30)
        self.client.loop_start()

    def on_connect(self, client, userdata, flags, reason, properties):
        if not self.running: return
        if reason.is_failure:
            self.status("Home Assistant MQTT rejected; check credentials and broker permissions."); return
        client.subscribe(self.settings.discovery_prefix + "/status", qos=1)
        client.publish(self.availability, "online", qos=1, retain=True)
        with self.lock:
            self.connected = True
            for sensor in self.sensors.values(): sensor["announced"] = None
            pending = list(self.sensors)
        for identity in pending: self.flush(identity, force=True)
        self.status("Home Assistant · publishing")

    def on_disconnect(self, client, userdata, flags, reason, properties):
        with self.lock: self.connected = False
        self.status("Home Assistant MQTT disconnected; reconnecting…")

    def on_message(self, client, userdata, message):
        # Home Assistant's birth message: rediscover after it restarts.
        if message.topic == self.settings.discovery_prefix + "/status" and message.payload == b"online":
            with self.lock:
                for sensor in self.sensors.values(): sensor["announced"] = None
                pending = list(self.sensors)
            for identity in pending: self.flush(identity, force=True)

    def publish(self, identity, name, reading, rssi, stamp):
        state = {key: value for key, value in asdict(reading).items() if key != "mac"}
        state.update(rssi=rssi, last_seen=time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(stamp)))
        with self.lock:
            sensor = self.sensors.setdefault(identity, {"name": name, "state": None, "announced": None, "sent": None, "stamp": None})
            if sensor["stamp"] is not None and stamp <= sensor["stamp"]: return  # stale / retained duplicates
            sensor.update(name=name, state=state, stamp=stamp)
        self.flush(identity)

    def flush(self, identity, force=False):
        with self.lock:
            sensor = self.sensors.get(identity)
            if not self.connected or not sensor or sensor["state"] is None: return
            announce = sensor["announced"] != sensor["name"]
            # Home Assistant restarts expire_after on every message, so an
            # expired reading must never be resent (reconnect, birth or late input).
            expiry = self.settings.expire_after
            fresh = not expiry or self.wall() - sensor["stamp"] < expiry
            now = self.clock()
            due = fresh and (force or announce or sensor["sent"] is None or now - sensor["sent"] >= self.settings.interval)
            if not (due or announce): return
            if due: sensor["sent"] = now
            if announce: sensor["announced"] = sensor["name"]
            name, state = sensor["name"], dict(sensor["state"])
        if announce:
            self.client.publish(self.discovery_topic(identity), json.dumps(self.discovery(identity, name)), qos=1, retain=True)
        if due:
            # Retained state would revive expired sensors when replayed, so it is
            # only retained when expiry is disabled. Birth messages resend it instead.
            self.client.publish(self.state_topic(identity), json.dumps(state, allow_nan=False), qos=1, retain=not expiry)

    def discovery_topic(self, identity):
        return f"{self.settings.discovery_prefix}/device/ruuvilinux_{topic_id(identity)}/config"

    def state_topic(self, identity):
        return f"{self.settings.base_topic}/{topic_id(identity)}/state"

    def discovery(self, identity, name):
        compact = topic_id(identity)
        components = {}
        for key, label, device_class, unit, state_class, precision, enabled, diagnostic in ENTITIES:
            component = {"platform": "sensor", "name": label, "unique_id": f"ruuvilinux_{compact}_{key}",
                         "value_template": f"{{{{ value_json.{key} }}}}", "suggested_display_precision": precision}
            if device_class: component["device_class"] = device_class
            if unit: component["unit_of_measurement"] = unit
            if state_class: component["state_class"] = state_class
            if not enabled: component["enabled_by_default"] = False
            if diagnostic: component["entity_category"] = "diagnostic"
            if self.settings.expire_after: component["expire_after"] = self.settings.expire_after
            components[key] = component
        components["last_seen"] = {"platform": "sensor", "name": "Last seen", "unique_id": f"ruuvilinux_{compact}_last_seen",
                                   "device_class": "timestamp", "entity_category": "diagnostic",
                                   "value_template": "{{ value_json.last_seen }}"}
        device = {"identifiers": [f"ruuvilinux_{compact}"], "name": name, "manufacturer": "Ruuvi Innovations",
                  "model": "RuuviTag (RAWv2)"}
        if re.fullmatch(r"([0-9A-F]{2}:){5}[0-9A-F]{2}", identity): device["connections"] = [["bluetooth", identity.lower()]]
        return {"device": device,
                "origin": {"name": "RuuviLinux", "sw_version": __version__, "support_url": "https://github.com/tonibergholm/RuuviLinux"},
                "components": components, "state_topic": self.state_topic(identity),
                "availability_topic": self.availability, "qos": 1}

    def stop(self):
        if not self.running: return
        self.running = False
        try:
            if self.connected: self.client.publish(self.availability, "offline", qos=1, retain=True).wait_for_publish(2)
        except (RuntimeError, ValueError): pass
        self.client.disconnect()
        threading.Thread(target=self.client.loop_stop, daemon=True).start()
