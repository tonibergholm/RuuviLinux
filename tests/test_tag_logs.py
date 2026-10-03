import asyncio,struct,threading
from dataclasses import replace
from types import SimpleNamespace
import pytest
from ruuvilinux.tag_logs import LogAccumulator,LogSample,download_session,RX,TX,RETENTION
from ruuvilinux.storage import Store
from ruuvilinux.protocol import decode_rawv2
NOW=1567047917

def frame(field,stamp,value):return bytes([0x3A,field,0x10])+struct.pack('>II',stamp,value&0xFFFFFFFF)
def test_official_request_and_signed_values():
    acc=LogAccumulator(NOW,start=1566047917)
    assert acc.request()==bytes.fromhex('3A3A115D6740ED5D57FEAD')
    for f,v in [(0x32,100044),(0x30,-1876),(0x31,2445)]:acc.feed(frame(f,NOW-1,v))
    assert acc.samples()==[LogSample(NOW-1,-18.76,24.45,1000.44)]
    acc.feed(bytes.fromhex('3A3A10FFFFFFFFFFFFFFFF'));assert acc.complete
    acc.feed(frame(0x30,NOW-1,999));assert acc.samples()[0].temperature==-18.76

def test_partial_timestamp_grouping_and_rejection():
    acc=LogAccumulator(NOW)
    acc.feed(frame(0x30,NOW-20,2000));acc.feed(frame(0x31,NOW-10,6000))
    acc.feed(frame(0x30,NOW+1,2100));acc.feed(frame(0x30,NOW-RETENTION-1,2200))
    acc.feed(frame(0x30,NOW-1,0x80000000));acc.feed(frame(0x32,NOW-1,0xFFFFFFFF))
    acc.feed(b'\x00\x00\x00');assert len(acc.samples())==2
    assert acc.samples()[0].humidity is None
    with pytest.raises(ValueError):acc.feed(b'\x3a\x30\x10\x00')
    with pytest.raises(ValueError):acc.feed(bytes.fromhex('3A3AF0FFFFFFFFFFFFFFFF'))

def test_merge_preserves_freshness_and_deduplicates(tmp_path):
    path=tmp_path/'sensors.db';store=Store(path)
    r=decode_rawv2(bytes.fromhex('0512FC5394C37C0004FFFC040CAC364200CDCBB8334C884F'))
    identity=store.receive('test',r,-60,NOW);store.rename(identity,'Kitchen');store.favorite(identity,True)
    original=store.sensor(identity)
    logs=[LogSample(NOW-86400*3,18,45,1000),LogSample(NOW,99,99,999),LogSample(NOW-RETENTION-1,0,0,0)]
    assert store.merge_logs(identity,logs,NOW)==1
    assert store.merge_logs(identity,[replace(logs[0],time=logs[0].time+1)],NOW)==0
    assert store.sensor(identity)==original
    assert len(store.history(identity,NOW))==1
    assert len(store.history(identity,NOW,RETENTION))==2
    store.close();store=Store(path)
    assert len(store.history(identity,NOW,RETENTION))==2;store.close()

def test_merge_partial_fields_same_minute():
    store=Store(':memory:');r=decode_rawv2(bytes.fromhex('0512FC5394C37C0004FFFC040CAC364200CDCBB8334C884F'))
    identity=store.receive('test',r,-60,NOW)
    stamp=(NOW-1000)//60*60
    store.merge_logs(identity,[LogSample(stamp,18),LogSample(stamp+1,humidity=50)],NOW)
    row=store.history(identity,NOW)[0];assert row['temperature']==18 and row['humidity']==50
    store.close()

def test_transport_subscribe_write_end_and_cleanup():
    events=[]
    class Scanner:
        @staticmethod
        async def find_device_by_filter(predicate,**kwargs):return SimpleNamespace(address='tag')
    class Client:
        is_connected=False
        def __init__(self,device,**kwargs):pass
        async def connect(self):self.is_connected=True
        async def start_notify(self,characteristic,callback):events.append(characteristic);self.callback=callback
        async def write_gatt_char(self,characteristic,data,response):
            events.append((characteristic,data,response))
            for f,v in [(0x30,2400),(0x31,5000),(0x32,100000)]:self.callback(None,frame(f,NOW-300,v))
            self.callback(None,bytes.fromhex('3A3A10FFFFFFFFFFFFFFFF'))
        async def stop_notify(self,characteristic):events.append('unsubscribe')
        async def disconnect(self):events.append('disconnect');self.is_connected=False
    acc=LogAccumulator(NOW)
    asyncio.run(download_session('tag',threading.Event(),lambda _:None,acc,scanner_factory=Scanner,client_factory=Client,clock=lambda:NOW))
    assert TX in events and (RX,acc.request(),True) in events
    assert events[-2:]==['unsubscribe','disconnect'] and acc.complete
    assert acc.samples()[0].pressure==1000

def test_transport_cancel_disconnects():
    stop=threading.Event();events=[]
    class Scanner:
        @staticmethod
        async def find_device_by_filter(*args,**kwargs):return object()
    class Client:
        is_connected=True
        def __init__(self,*args,**kwargs):pass
        async def connect(self):pass
        async def start_notify(self,*args):pass
        async def write_gatt_char(self,*args,**kwargs):stop.set()
        async def stop_notify(self,*args):events.append('unsubscribe')
        async def disconnect(self):events.append('disconnect')
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(download_session('tag',stop,lambda _:None,LogAccumulator(NOW),scanner_factory=Scanner,client_factory=Client))
    assert events==['unsubscribe','disconnect']
