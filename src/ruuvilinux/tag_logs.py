"""RuuviTag NUS log-read protocol, following the official Ruuvi specification."""
import asyncio
from dataclasses import dataclass
import struct
import threading
import time
from bleak import BleakClient, BleakScanner
from PySide6.QtCore import QThread, Signal
from .protocol import decode_advertisement

SERVICE = '6e400001-b5a3-f393-e0a9-e50e24dcca9e'
RX = '6e400002-b5a3-f393-e0a9-e50e24dcca9e'
TX = '6e400003-b5a3-f393-e0a9-e50e24dcca9e'
RETENTION = 10 * 86400
MAX_SAMPLES = 14400

@dataclass(frozen=True)
class LogSample:
    time: int
    temperature: float | None = None
    humidity: float | None = None
    pressure: float | None = None

class LogAccumulator:
    def __init__(self, now, start=None):
        self.now = int(now)
        self.start = max(0, self.now-RETENTION) if start is None else int(start)
        self.values = {}
        self.complete = False

    def request(self):
        return b'\x3a\x3a\x11' + struct.pack('>II', self.now, self.start)

    def feed(self, packet):
        packet = bytes(packet)
        if self.complete or len(packet)<3 or packet[0]!=0x3A: return
        if packet[2]==0xF0: raise ValueError('Tag reported a log-transfer error. Retry the download.')
        if packet[2]!=0x10: return  # heartbeat / unrelated NUS traffic
        if len(packet)!=11: raise ValueError('Malformed tag history packet.')
        if packet[3:]==b'\xff'*8:
            self.complete=True; return
        field={0x30:'temperature',0x31:'humidity',0x32:'pressure'}.get(packet[1])
        if field is None: return
        stamp,raw=struct.unpack('>II',packet[3:])
        if not self.start<=stamp<=self.now: return
        if field=='temperature':
            if raw==0x80000000: return
            value=struct.unpack('>i',packet[7:])[0]/100
        else:
            if raw==0xFFFFFFFF: return
            value=raw/100  # humidity 0.01%; pressure 1 Pa -> hPa
        if stamp not in self.values and len(self.values)>=MAX_SAMPLES:
            raise ValueError('Tag history exceeded the sample limit.')
        self.values.setdefault(stamp,{})[field]=value

    def samples(self):
        return [LogSample(t,**fields) for t,fields in sorted(self.values.items())]


async def download_session(identity, stop, progress, accumulator, adapter=None,
                           scanner_factory=BleakScanner, client_factory=BleakClient, clock=time.time):
    def matches(device, advertisement):
        reading=decode_advertisement(advertisement.manufacturer_data)
        return reading is not None and (reading.mac==identity or device.address.upper()==identity)
    options={'timeout':15}
    if adapter: options['adapter']=adapter
    progress('Finding the tag over Bluetooth…')
    device=await scanner_factory.find_device_by_filter(matches,**options)
    if device is None: raise RuntimeError('Tag not found. Bring it closer and enable connectable firmware.')
    if stop.is_set(): raise asyncio.CancelledError()
    progress('Connecting to tag…')
    disconnected=asyncio.Event()
    kwargs={'timeout':15,'disconnected_callback':lambda _:disconnected.set()}
    if adapter: kwargs['adapter']=adapter
    client=client_factory(device,**kwargs)
    started=False
    try:
        await asyncio.wait_for(client.connect(),20)
        last_packet=time.monotonic(); packet_error=None
        def notified(characteristic,data):
            nonlocal last_packet,packet_error
            try: accumulator.feed(data)
            except ValueError as error: packet_error=error
            if len(data)>=3 and data[0]==0x3A and data[2] in (0x10,0xF0):
                last_packet=time.monotonic()
                progress(f'Downloading tag history · {len(accumulator.values)} samples')
        await asyncio.wait_for(client.start_notify(TX,notified),10); started=True
        accumulator.now=int(clock()); accumulator.start=max(0,accumulator.now-RETENTION)
        await asyncio.wait_for(client.write_gatt_char(RX,accumulator.request(),response=True),10)
        deadline=time.monotonic()+300
        while not accumulator.complete:
            if stop.is_set(): raise asyncio.CancelledError()
            if packet_error: raise packet_error
            if disconnected.is_set(): raise RuntimeError('Tag disconnected. Bring it closer and retry.')
            if time.monotonic()>deadline or time.monotonic()-last_packet>30:
                raise TimeoutError('Tag stopped sending history. Check connectable firmware, close other tag connections, and retry.')
            await asyncio.sleep(.1)
        if packet_error: raise packet_error
    finally:
        try:
            if started and client.is_connected: await asyncio.wait_for(client.stop_notify(TX),3)
        finally:
            await asyncio.wait_for(client.disconnect(),5)


class LogWorker(QThread):
    progress=Signal(str)
    result=Signal(object,str)
    def __init__(self,identity,adapter=None,parent=None):
        super().__init__(parent);self.identity=identity;self.adapter=adapter
        self.stop_event=threading.Event()
    def stop(self): self.stop_event.set()
    def run(self):
        acc=LogAccumulator(time.time())
        async def run():
            task=asyncio.create_task(download_session(self.identity,self.stop_event,self.progress.emit,acc,self.adapter))
            try:
                while not task.done():
                    if self.stop_event.is_set(): task.cancel();break
                    await asyncio.sleep(.1)
                await task
            finally:
                if not task.done(): task.cancel()
        error=''
        try: asyncio.run(run())
        except asyncio.CancelledError: error='Download cancelled.'
        except Exception as exc: error=f'History download failed: {exc or "Connection or transfer timed out. Bring the tag closer, enable connectable firmware, and close other tag connections."}'
        self.result.emit(acc.samples(),error)
