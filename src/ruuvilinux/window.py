import math
import sqlite3
import time
from dataclasses import replace, asdict
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QPushButton, QLineEdit, QCheckBox,
    QComboBox, QFrame, QSplitter, QMessageBox, QStackedWidget)
from .chart import HistoryChart
from .protocol import decode_rawv2
from .scanner import ScannerWorker
from .mqtt_input import MQTTInput
from .mqtt_dialog import MQTTDialog
from .tag_logs import LogWorker
from .collector_client import request as collector_request


def value(v, unit, digits=1):
    return "—" if v is None else f"{v:.{digits}f} {unit}"


class MainWindow(QMainWindow):
    def __init__(self, store, demo=False, adapter=None, start_scanning=True):
        super().__init__()
        self.store, self.demo, self.adapter = store, demo, adapter
        self.worker = None
        self.mqtt_client = None
        self.pending_mqtt = None
        self.log_worker = None
        self.pending_log = None
        self.resume_after_log = False
        self.log_identity = None
        self.collector_active = False
        self.collector_state = None
        self.resume_daemon_after_log = False
        self.selected = None
        self.closing = False
        self.setWindowTitle("RuuviLinux" + (" · Demo" if demo else ""))
        self.resize(1060, 720)
        self.setMinimumSize(820, 580)
        shell = QWidget(); self.setCentralWidget(shell)
        outer = QVBoxLayout(shell); outer.setContentsMargins(16, 16, 16, 12)
        split = QSplitter(); outer.addWidget(split, 1)
        sidebar = QWidget(); side = QVBoxLayout(sidebar)
        title = QLabel("RuuviLinux"); title.setObjectName("title"); side.addWidget(title)
        caption = QLabel("Your nearby environment"); caption.setObjectName("muted"); side.addWidget(caption)
        self.only_favorites = QCheckBox("Favorites only")
        side.addWidget(self.only_favorites)
        self.list = QListWidget(); side.addWidget(self.list)
        self.list.setAccessibleName("Ruuvi sensors")
        split.addWidget(sidebar)
        self.pages = QStackedWidget(); split.addWidget(self.pages)
        empty = QWidget(); layout = QVBoxLayout(empty); layout.addStretch()
        label = QLabel("Bring a RuuviTag nearby"); self.empty_title=label; label.setObjectName("title"); label.setAlignment(Qt.AlignmentFlag.AlignCenter); layout.addWidget(label)
        label = QLabel("Read temperature, humidity, and pressure over Bluetooth.\nNo pairing, Gateway, or account needed.\n\nSupports RuuviTag RAWv2 (format 5).")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter); layout.addWidget(label); layout.addStretch()
        self.pages.addWidget(empty)
        details = QWidget(); d = QVBoxLayout(details); d.setContentsMargins(22, 8, 8, 0)
        header = QHBoxLayout()
        self.name = QLineEdit(); self.name.setPlaceholderText("Sensor name"); self.name.setAccessibleName("Sensor name")
        header.addWidget(self.name, 1)
        self.save = QPushButton("Save name"); header.addWidget(self.save)
        self.favorite = QPushButton("☆ Favorite"); self.favorite.setCheckable(True); header.addWidget(self.favorite)
        d.addLayout(header)
        self.last_seen = QLabel(); self.last_seen.setObjectName("muted"); d.addWidget(self.last_seen)
        cards = QHBoxLayout(); self.cards = {}
        for field, title in (("temperature", "Temperature"), ("humidity", "Humidity"), ("pressure", "Pressure")):
            card = QFrame(); card.setObjectName("card"); c = QVBoxLayout(card)
            c.addWidget(QLabel(title)); number = QLabel("—"); number.setObjectName("reading"); c.addWidget(number)
            cards.addWidget(card); self.cards[field] = number
        d.addLayout(cards)
        chart_header = QHBoxLayout(); chart_header.addWidget(QLabel("History"), 1)
        self.period_picker=QComboBox();self.period_picker.addItem("Last 24 hours",86400);self.period_picker.addItem("Last 10 days",864000)
        chart_header.addWidget(self.period_picker)
        self.metric_picker = QComboBox()
        for label, field in (("Temperature", "temperature"), ("Humidity", "humidity"), ("Pressure", "pressure")):
            self.metric_picker.addItem(label, field)
        chart_header.addWidget(self.metric_picker); d.addLayout(chart_header)
        self.chart = HistoryChart(); d.addWidget(self.chart, 1)
        self.download_button=QPushButton("Download tag history");self.download_button.setEnabled(not demo)
        self.download_button.clicked.connect(self.download_history);d.addWidget(self.download_button)
        self.log_status=QLabel();self.log_status.setWordWrap(True);d.addWidget(self.log_status)
        self.history_note = QLabel(); self.history_note.setObjectName("muted"); d.addWidget(self.history_note)
        self.secondary = QLabel(); self.secondary.setWordWrap(True); d.addWidget(self.secondary)
        self.identity = QLabel(); self.identity.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); self.identity.setObjectName("muted"); d.addWidget(self.identity)
        self.pages.addWidget(details)
        split.setSizes([260, 780])
        footer = QHBoxLayout()
        self.status = QLabel("Demo data · Bluetooth is disabled" if demo else "Starting Bluetooth…")
        self.status.setWordWrap(True); footer.addWidget(self.status, 1)
        self.pause = QPushButton("Pause scanning"); self.pause.setEnabled(not demo); footer.addWidget(self.pause)
        self.mqtt_button=QPushButton("MQTT settings…"); self.mqtt_button.setEnabled(not demo)
        self.mqtt_button.clicked.connect(self.configure_mqtt); footer.addWidget(self.mqtt_button)
        outer.addLayout(footer)
        self.setStyleSheet("""
            QLabel#title { font-size: 24px; font-weight: 600; }
            QLabel#reading { font-size: 27px; font-weight: 600; }
            QLabel#muted { color: #8a949e; }
            QFrame#card { border: 1px solid #52756e; border-radius: 10px; padding: 15px; }
            QLineEdit { padding: 8px; font-size: 20px; }
            QPushButton { padding: 7px 12px; }
            QListWidget { border: 0; }
            QListWidget::item { padding: 12px 6px; }
        """)
        self.list.currentItemChanged.connect(self.select_item)
        self.only_favorites.toggled.connect(self.refresh_list)
        self.save.clicked.connect(self.rename)
        self.name.returnPressed.connect(self.rename)
        self.favorite.clicked.connect(self.set_favorite)
        self.metric_picker.currentIndexChanged.connect(self.refresh_detail)
        self.period_picker.currentIndexChanged.connect(self.refresh_detail)
        self.pause.clicked.connect(self.toggle_scan)
        self.timer = QTimer(self); self.timer.timeout.connect(self.refresh_detail); self.timer.start(5000)
        self.timer.timeout.connect(self.poll_collector)
        self.demo_timer = None
        if demo:
            self.seed_demo()
            self.demo_timer = QTimer(self); self.demo_timer.timeout.connect(self.update_demo); self.demo_timer.start(2000)
        self.refresh_list()
        if start_scanning and not demo:
            QTimer.singleShot(0, self.start_scan)

    def start_scan(self):
        if self.closing or (self.worker and self.worker.isRunning()):
            return
        if not self.demo and str(self.store.path) != ":memory:":
            try:
                self.collector_state = collector_request(self.store.path)
                self.collector_active = True; self.poll_collector(); return
            except (OSError,ValueError): pass
        self.empty_title.setText("Bring a RuuviTag nearby")
        self.status.setText("Starting Bluetooth…")
        self.pause.setText("Pause scanning"); self.pause.setEnabled(True)
        self.worker = ScannerWorker(adapter=self.adapter, parent=self)
        self.worker.reading_received.connect(self.receive)
        self.worker.status_changed.connect(self.status.setText)
        self.worker.finished.connect(self.scan_finished)
        self.worker.start()

    def poll_collector(self):
        if not self.collector_active or self.closing: return
        try:
            self.collector_state = collector_request(self.store.path)
            self.status.setText(self.collector_state["status"])
            busy = bool(self.log_worker or self.pending_log)
            self.pause.setEnabled(not busy)
            self.pause.setText("Use Bluetooth" if self.collector_state["source"] == "mqtt" else
                               ("Resume collector" if self.collector_state["paused"] else "Pause collector"))
            sensors = self.store.sensors(self.only_favorites.isChecked())
            ids = [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]
            if ids != [s["id"] for s in sensors]: self.refresh_list()
            else:
                for i,s in enumerate(sensors): self.list.item(i).setText(("★ " if s["favorite"] else "")+s["name"])
            self.refresh_detail()
        except (OSError,ValueError,sqlite3.Error):
            self.status.setText("Background collector is offline. Start ruuvilinux-collector.service to resume.")
            self.pause.setEnabled(False)

    def scan_finished(self):
        if self.worker:
            self.worker.deleteLater(); self.worker = None
        self.pause.setEnabled(True); self.pause.setText("Resume scanning")
        if self.closing:
            self.close()
        elif self.pending_log:
            self.begin_download()
        elif self.pending_mqtt:
            config=self.pending_mqtt; self.pending_mqtt=None; self.start_mqtt(config)

    def download_history(self):
        if self.log_worker:
            self.log_worker.stop();self.download_button.setEnabled(False);return
        if self.pending_log or not self.selected or self.demo:return
        self.log_identity=self.selected;self.pending_log=self.selected
        self.resume_after_log=bool(self.worker and self.worker.isRunning())
        self.pause.setEnabled(False);self.mqtt_button.setEnabled(False)
        self.download_button.setText("Cancel history download")
        self.log_status.setText("Preparing history download…")
        if self.collector_active:
            try:
                state=collector_request(self.store.path)
                self.resume_daemon_after_log=state["source"]=="bluetooth" and not state["paused"]
                if self.resume_daemon_after_log:
                    collector_request(self.store.path,"pause",timeout=8,leaseSeconds=360)
            except (OSError,ValueError):
                self.pending_log=None;self.resume_daemon_after_log=False
                self.download_button.setText("Download tag history")
                self.log_status.setText("Could not pause the collector. Check its service and retry.")
                self.mqtt_button.setEnabled(True);self.poll_collector();return
        if self.resume_after_log:self.worker.stop()
        else:self.begin_download()

    def begin_download(self):
        self.pause.setEnabled(False)
        identity=self.pending_log;self.pending_log=None
        self.log_worker=LogWorker(identity,self.adapter,self)
        self.log_worker.progress.connect(self.log_status.setText)
        self.log_worker.result.connect(self.import_history)
        self.log_worker.finished.connect(self.log_finished)
        self.log_worker.start()

    def import_history(self,samples,error):
        if self.closing:return
        try:
            added=self.store.merge_logs(self.log_identity,samples,time.time())
            self.log_status.setText((error+" " if error else "Download complete. ")+f"Imported {added} new samples ({len(samples)} received).")
            if samples:self.period_picker.setCurrentIndex(1)
            self.refresh_detail()
        except (sqlite3.Error,ValueError) as exc:self.log_status.setText(f"Could not save tag history: {exc}")

    def log_finished(self):
        self.log_worker.deleteLater();self.log_worker=None
        self.download_button.setText("Download tag history");self.download_button.setEnabled(not self.demo)
        self.pause.setEnabled(True);self.mqtt_button.setEnabled(True)
        if self.resume_daemon_after_log:
            self.resume_daemon_after_log=False
            try: collector_request(self.store.path,"resume",timeout=8)
            except (OSError,ValueError): self.status.setText("Collector will resume when the history pause lease expires.")
        if self.closing:self.close()
        elif self.resume_after_log:self.start_scan()

    def configure_mqtt(self):
        dialog=MQTTDialog(self)
        result=dialog.exec()
        if result==1: self.use_mqtt(dialog.settings())
        elif result==2:
            if self.collector_active:
                try: collector_request(self.store.path,"bluetooth",timeout=8);self.poll_collector()
                except (OSError,ValueError) as error:self.status.setText(f"Could not switch collector: {error}")
                return
            self.stop_mqtt(); self.pending_mqtt=None
            if not self.worker: self.start_scan()

    def stop_mqtt(self):
        if self.mqtt_client:
            self.mqtt_client.reading_received.disconnect(self.receive)
            self.mqtt_client.status_changed.disconnect(self.status.setText)
            self.mqtt_client.stop(); self.mqtt_client.deleteLater(); self.mqtt_client=None

    def use_mqtt(self,config):
        if not self.collector_active and not self.demo and str(self.store.path) != ":memory:":
            try:
                self.collector_state=collector_request(self.store.path);self.collector_active=True
            except (OSError,ValueError): pass
        if self.collector_active:
            try:
                collector_request(self.store.path,"mqtt",timeout=8,settings=asdict(config));self.poll_collector()
            except (OSError,ValueError) as error:self.status.setText(f"Could not configure collector: {error}")
            return
        self.stop_mqtt()
        if self.worker and self.worker.isRunning():
            self.pending_mqtt=config; self.worker.stop(); self.pause.setEnabled(False)
        else: self.start_mqtt(config)

    def start_mqtt(self,config):
        try:
            self.empty_title.setText("Waiting for MQTT readings")
            self.mqtt_client=MQTTInput(config,self)
            self.mqtt_client.reading_received.connect(self.receive)
            self.mqtt_client.status_changed.connect(self.status.setText)
            self.mqtt_client.start(); self.pause.setText("Disconnect MQTT"); self.pause.setEnabled(True)
        except Exception as error: self.status.setText("Could not start MQTT: "+str(error))

    def toggle_scan(self):
        if self.collector_active:
            try:
                state=collector_request(self.store.path)
                command="bluetooth" if state["source"]=="mqtt" else ("resume" if state["paused"] else "pause")
                collector_request(self.store.path,command,timeout=8);self.poll_collector()
            except (OSError,ValueError) as error:self.status.setText(f"Could not control collector: {error}")
            return
        if self.mqtt_client:
            self.stop_mqtt(); self.status.setText("MQTT disconnected"); self.pause.setText("Resume Bluetooth")
            return
        if self.worker and self.worker.isRunning():
            self.worker.stop(); self.status.setText("Stopping scan…")
            self.pause.setEnabled(False)
            # The finish signal will re-enable controls; BLE stop is asynchronous.
            self.worker.finished.connect(lambda: self.status.setText("Scanning paused") if self.mqtt_client is None and not self.closing else None)
        else:
            self.start_scan()

    def receive(self, address, reading, rssi, now):
        if self.closing:
            return
        try:
            identity = self.store.receive(address, reading, rssi, now)
            ids = [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]
            if identity not in ids:
                self.refresh_list()
            # Update detail immediately; do not overwrite an in-progress name edit.
            self.refresh_detail()
        except sqlite3.Error as error:
            self.status.setText(f"Could not save sensor data: {error}")

    def refresh_list(self, *args):
        current = self.selected
        self.list.blockSignals(True)
        self.list.clear()
        for sensor in self.store.sensors(self.only_favorites.isChecked()):
            item = QListWidgetItem(("★ " if sensor["favorite"] else "") + sensor["name"])
            item.setData(Qt.ItemDataRole.UserRole, sensor["id"])
            self.list.addItem(item)
            if sensor["id"] == current:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self.list.blockSignals(False)
        self.select_item(self.list.currentItem())

    def select_item(self, item, previous=None):
        self.selected = item.data(Qt.ItemDataRole.UserRole) if item else None
        sensor = self.store.sensor(self.selected) if self.selected else None
        self.pages.setCurrentIndex(1 if sensor else 0)
        if sensor:
            self.name.setText(sensor["name"])
        self.refresh_detail()

    def refresh_detail(self, *args):
        if self.closing or not self.selected:
            return
        sensor = self.store.sensor(self.selected)
        if not sensor:
            return
        r = sensor["latest"]; now = time.time()
        self.cards["temperature"].setText(value(r["temperature"], "°C"))
        self.cards["humidity"].setText(value(r["humidity"], "%"))
        self.cards["pressure"].setText(value(r["pressure"], "hPa"))
        self.favorite.setChecked(bool(sensor["favorite"]))
        self.favorite.setText("★ Favorite" if sensor["favorite"] else "☆ Favorite")
        age = max(0, int(now - sensor["last_seen"]))
        self.last_seen.setText(f"{'No recent signal' if age > 30 else 'Recent reading'} · last seen {age}s ago · {sensor['rssi']} dBm")
        rows = self.store.history(self.selected, now,self.period_picker.currentData())
        self.chart.set_data(rows, self.metric_picker.currentData())
        self.history_note.setText(f"{len(rows)} samples · up to one per minute · live readings and downloaded tag history")
        movement = "—" if r["movement"] is None else str(r["movement"])
        tx = "—" if r["tx_power"] is None else str(r["tx_power"])
        self.secondary.setText(f"Battery {value(r['voltage'], 'V', 3)} · movement {movement} · TX {tx} dBm\n"
            f"Acceleration: X {value(r['acceleration_x'], 'g', 3)} · Y {value(r['acceleration_y'], 'g', 3)} · Z {value(r['acceleration_z'], 'g', 3)}")
        self.identity.setText(sensor["id"])

    def rename(self):
        if self.selected:
            try:
                self.store.rename(self.selected, self.name.text()); self.refresh_list()
            except (ValueError, sqlite3.Error) as error:
                QMessageBox.warning(self, "Could not save name", str(error))

    def set_favorite(self, checked):
        if self.selected:
            try:
                self.store.favorite(self.selected, checked); self.refresh_list()
            except sqlite3.Error as error:
                QMessageBox.warning(self, "Could not save favorite", str(error))

    def seed_demo(self):
        base = decode_rawv2(bytes.fromhex("0512FC5394C37C0004FFFC040CAC364200CDCBB8334C884F"))
        now = time.time()
        for index, (mac, name, offset) in enumerate((("CB:B8:33:4C:88:4F", "Living room", 0), ("CB:B8:33:4C:88:50", "Balcony", -7))):
            for i in range(120):
                reading = replace(base, mac=mac, temperature=22 + offset + math.sin(i/18)*1.2,
                                  humidity=48 + math.sin(i/15)*5, sequence=i)
                self.store.receive(mac, reading, -55-index*10, now-(119-i)*60)
            self.store.rename(mac, name)
        self.store.favorite("CB:B8:33:4C:88:4F", True)
        self.demo_sequence = 120

    def update_demo(self):
        base = decode_rawv2(bytes.fromhex("0512FC5394C37C0004FFFC040CAC364200CDCBB8334C884F"))
        for index, mac in enumerate(("CB:B8:33:4C:88:4F", "CB:B8:33:4C:88:50")):
            reading = replace(base, mac=mac, temperature=22-index*7+math.sin(self.demo_sequence/18)*1.2,
                              humidity=48+math.sin(self.demo_sequence/15)*5, sequence=self.demo_sequence)
            self.receive(mac, reading, -55-index*10, time.time())
        self.demo_sequence += 1

    def closeEvent(self, event):
        self.stop_mqtt(); self.pending_mqtt=None;self.pending_log=None
        if self.log_worker and self.log_worker.isRunning():
            self.closing=True;self.timer.stop();self.log_worker.stop();event.ignore();return
        if self.worker and self.worker.isRunning():
            self.closing = True; self.timer.stop()
            self.worker.stop(); self.status.setText("Stopping Bluetooth before closing…")
            self.pause.setEnabled(False); event.ignore()
            return
        self.closing = True
        self.timer.stop()
        if self.demo_timer:
            self.demo_timer.stop()
        self.store.close()
        event.accept()
