from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QDialog,QFormLayout,QLineEdit,QSpinBox,QCheckBox,QPushButton,QHBoxLayout,QMessageBox
from .mqtt_input import MQTTSettings


class MQTTDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent); self.setWindowTitle("MQTT input")
        prefs=QSettings(); layout=QFormLayout(self)
        self.host=QLineEdit(prefs.value("mqtt/host","localhost"))
        self.port=QSpinBox(); self.port.setRange(1,65535); self.port.setValue(int(prefs.value("mqtt/port",1883)))
        self.topic=QLineEdit(prefs.value("mqtt/topic","ruuvi/#"))
        self.username=QLineEdit(prefs.value("mqtt/username",""))
        self.password=QLineEdit(); self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.tls=QCheckBox("Use TLS (system trusted certificates)"); self.tls.setChecked(prefs.value("mqtt/tls",False,type=bool))
        for name,widget in (("Broker hostname",self.host),("Port",self.port),("Topic filter",self.topic),("Username",self.username),("Password (this session)",self.password),("",self.tls)): layout.addRow(name,widget)
        buttons=QHBoxLayout(); connect=QPushButton("Connect MQTT"); ble=QPushButton("Use Bluetooth"); cancel=QPushButton("Cancel")
        for b in (connect,ble,cancel): buttons.addWidget(b)
        layout.addRow(buttons)
        connect.clicked.connect(self.connect); ble.clicked.connect(lambda:self.done(2)); cancel.clicked.connect(self.reject)

    def settings(self):
        return MQTTSettings(self.host.text().strip(),self.port.value(),self.topic.text(),self.username.text(),self.password.text(),self.tls.isChecked())

    def connect(self):
        config=self.settings()
        try: config.validate()
        except ValueError as e: QMessageBox.warning(self,"MQTT settings",str(e)); return
        prefs=QSettings()
        for key in ("host","port","topic","username","tls"): prefs.setValue("mqtt/"+key,getattr(config,key))
        self.accept()
