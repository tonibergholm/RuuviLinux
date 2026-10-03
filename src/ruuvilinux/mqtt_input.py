"""Qt adapter for the shared, headless MQTT transport."""
from PySide6.QtCore import QObject, Signal
import paho.mqtt.client as mqtt
from .mqtt_backend import MQTTTransport, MQTTSettings, decode_mqtt_message, MQTTReading

class MQTTInput(MQTTTransport, QObject):
    reading_received=Signal(str,object,int,float)
    status_changed=Signal(str)
    def __init__(self,settings,parent=None,client_factory=mqtt.Client):
        QObject.__init__(self,parent)
        MQTTTransport.__init__(self,settings,self.reading_received.emit,self.status_changed.emit,client_factory)
