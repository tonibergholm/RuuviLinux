"""Headless BLE/MQTT collector. No Qt, window or tray process is required."""
import argparse
import asyncio
import fcntl
import json
import logging
import os
from pathlib import Path
import signal
import sqlite3
import time
from bleak import BleakScanner
from .collector_client import control_path
from .mqtt_backend import MQTTSettings, MQTTTransport
from .protocol import decode_advertisement
from .storage import Store, data_path

LOG = logging.getLogger("ruuvilinux.collector")


class Collector:
    def __init__(self, database, adapter=None, scanner_factory=BleakScanner, mqtt_factory=MQTTTransport):
        self.database=database;self.adapter=adapter
        self.scanner_factory=scanner_factory;self.mqtt_factory=mqtt_factory
        self.paused=False;self.mqtt_settings=None;self.status="Starting collector…"
        self.task=None;self.mqtt=None;self.lease=None;self.loop=None;self.store=None
        self.control_lock=asyncio.Lock()

    def report(self):
        return {"running": True, "paused": self.paused,
                "source": "mqtt" if self.mqtt_settings else "bluetooth", "status": self.status}

    def ingest(self, identity, reading, rssi, stamp):
        try: self.store.receive(identity,reading,rssi,stamp)
        except sqlite3.Error:
            self.status="Could not save collector readings. Check database access."
            LOG.warning("Could not save a reading")

    async def bluetooth(self):
        def detected(device, advertisement):
            reading=decode_advertisement(advertisement.manufacturer_data)
            if reading: self.ingest(device.address,reading,advertisement.rssi,time.time())
        while True:
            retry_delay=.1
            options={"detection_callback":detected}
            if self.adapter: options["adapter"]=self.adapter
            scanner=self.scanner_factory(**options)
            try:
                await asyncio.wait_for(scanner.start(),15)
                self.status="Background collector · scanning for nearby RuuviTags"
                # Reopen discovery periodically so adapter power cycles and
                # BlueZ restarts recover without needing a desktop window.
                await asyncio.sleep(60)
            except asyncio.CancelledError: raise
            except Exception:
                self.status="Collector waiting for Bluetooth. Check power and BlueZ."
                LOG.warning("Bluetooth unavailable; retrying in five seconds")
                retry_delay=5
            finally:
                try: await asyncio.wait_for(scanner.stop(),5)
                except Exception: LOG.warning("Bluetooth discovery cleanup did not finish")
            await asyncio.sleep(retry_delay)

    async def stop_input(self):
        if self.task:
            self.task.cancel()
            try: await self.task
            except asyncio.CancelledError: pass
            self.task=None
        if self.mqtt:
            self.mqtt.stop();self.mqtt=None

    def start_input(self):
        if self.paused: self.status="Background collector paused";return
        if self.mqtt_settings:
            transport=None
            def received(*args):
                def deliver():
                    if self.mqtt is transport and not self.paused: self.ingest(*args)
                self.loop.call_soon_threadsafe(deliver)
            def status(message):
                def deliver():
                    if self.mqtt is transport: self.status="Background collector · "+message
                self.loop.call_soon_threadsafe(deliver)
            transport=self.mqtt_factory(self.mqtt_settings,received,status)
            self.mqtt=transport;transport.start()
        else: self.task=asyncio.create_task(self.bluetooth())

    async def resume(self):
        async with self.control_lock:
            if self.lease: self.lease.cancel();self.lease=None
            if self.paused:
                self.paused=False;self.start_input()

    async def command(self, message):
        action=message.get("command")
        if action=="status": return self.report()
        if action=="resume": await self.resume();return self.report()
        async with self.control_lock:
            if action=="pause":
                lease=message.get("leaseSeconds",0)
                if not isinstance(lease,(int,float)) or isinstance(lease,bool) or not 0<=lease<=360:
                    raise ValueError("Invalid collector pause lease")
                await self.stop_input();self.paused=True;self.status="Background collector paused"
                if self.lease: self.lease.cancel();self.lease=None
                if lease: self.lease=self.loop.call_later(lease,lambda:asyncio.create_task(self.resume()))
            elif action in ("bluetooth","mqtt"):
                settings=None
                if action=="mqtt":
                    settings=MQTTSettings(**message.get("settings",{}));settings.validate()
                await self.stop_input();self.mqtt_settings=settings;self.paused=False
                if self.lease: self.lease.cancel();self.lease=None
                self.start_input()
            else: raise ValueError("Unknown collector command")
        return self.report()

    async def client(self, reader, writer):
        try:
            data=await asyncio.wait_for(reader.readline(),2)
            if len(data)>16384: raise ValueError("Collector request too large")
            message=json.loads(data)
            if not isinstance(message,dict): raise ValueError("Invalid collector request")
            result=await self.command(message)
        except Exception:
            result={"error":"Collector command failed. Check its status and settings."}
        try:
            writer.write(json.dumps(result).encode()+b"\n");await writer.drain()
        finally:
            writer.close();await writer.wait_closed()

    async def run(self, stop, mqtt_settings=None):
        self.loop=asyncio.get_running_loop();self.store=Store(self.database)
        path=control_path(self.database)
        lock_path=Path(str(path)+".lock")
        lock=open(lock_path,"a");os.chmod(lock_path,0o600)
        try:
            try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError: raise RuntimeError("A collector already owns this database")
            path.unlink(missing_ok=True)
            server=await asyncio.start_unix_server(self.client,path=str(path),limit=16384)
            os.chmod(path,0o600)
            self.mqtt_settings=mqtt_settings;self.start_input()
            LOG.info("Background collector started")
            try:
                async with server: await stop.wait()
            finally:
                if self.lease: self.lease.cancel()
                await self.stop_input();path.unlink(missing_ok=True)
        finally:
            lock.close();self.store.close()
        LOG.info("Background collector stopped")


def main(argv=None):
    parser=argparse.ArgumentParser(description="Headless RuuviTag collector for the desktop app and Omarchy bar")
    parser.add_argument("--database",type=Path,default=data_path())
    parser.add_argument("--adapter")
    parser.add_argument("--mqtt-host")
    parser.add_argument("--mqtt-port",type=int,default=1883)
    parser.add_argument("--mqtt-topic",default="ruuvi/#")
    parser.add_argument("--mqtt-username",default="")
    parser.add_argument("--mqtt-tls",action="store_true")
    args=parser.parse_args(argv)
    settings=None
    if args.mqtt_host:
        settings=MQTTSettings(args.mqtt_host,args.mqtt_port,args.mqtt_topic,args.mqtt_username,os.environ.get("RUUVILINUX_MQTT_PASSWORD",""),args.mqtt_tls)
        settings.validate()
    logging.basicConfig(level=logging.INFO,format="%(levelname)s %(message)s")
    async def run():
        stop=asyncio.Event();loop=asyncio.get_running_loop()
        for sig in (signal.SIGINT,signal.SIGTERM):loop.add_signal_handler(sig,stop.set)
        await Collector(args.database,args.adapter).run(stop,settings)
    try: asyncio.run(run())
    except (RuntimeError,OSError) as error:
        LOG.error("%s",error);return 1
    return 0


if __name__=="__main__": raise SystemExit(main())
