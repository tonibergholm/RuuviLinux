from dataclasses import replace
import sqlite3
import pytest
from ruuvilinux.protocol import decode_rawv2
from ruuvilinux.storage import Store, data_path
R = decode_rawv2(bytes.fromhex("0512FC5394C37C0004FFFC040CAC364200CDCBB8334C884F"))


def test_retention_deduplication_and_relaunch(tmp_path):
    path = tmp_path / "data/store.sqlite3"
    store = Store(path)
    identity = store.receive("address", R, -60, 100000)
    store.receive("address", R, -65, 100061)
    assert len(store.history(identity, 100061)) == 1
    store.receive("address", replace(R,sequence=206), -50, 100062)
    assert len(store.history(identity, 100062)) == 2
    store.rename(identity, " Kitchen "); store.favorite(identity,True)
    store.close()
    store = Store(path)
    assert store.sensor(identity)["name"] == "Kitchen"
    assert len(store.sensors(True)) == 1
    store.receive("address", replace(R,sequence=207), -45, 186463)
    assert len(store.history(identity, 186463)) == 1
    assert store.sensor(identity)["rssi"] == -45
    store.close()


def test_missing_sequence_and_mac_fallback():
    store = Store(":memory:")
    r = replace(R,mac=None,sequence=None)
    identity = store.receive("aa:bb:cc:dd:ee:ff",r,-50,100000)
    assert identity == "AA:BB:CC:DD:EE:FF"
    store.receive(identity,r,-50,100059)
    assert len(store.history(identity,100059)) == 1
    store.receive(identity,r,-50,100060)
    assert len(store.history(identity,100060)) == 2
    with pytest.raises(ValueError): store.rename(identity,"   ")
    store.close()


def test_sql_names_and_favorite_filter():
    store = Store(":memory:")
    a = store.receive("a",R,-50,100000)
    b = store.receive("b",replace(R,mac="CB:B8:33:4C:88:50"),-70,100000)
    store.rename(a,"Robert'); DROP TABLE sensors;--")
    store.favorite(b,True)
    assert len(store.sensors()) == 2
    assert store.sensors()[0]["id"] == b
    assert store.sensors(True)[0]["id"] == b
    store.close()


def test_retains_at_most_1440_samples():
    store = Store(":memory:")
    for i in range(1500):
        identity = store.receive("a",replace(R,sequence=i),-50,100000+i*60)
    assert len(store.history(identity,100000+1499*60)) == 1440
    store.close()


def test_xdg_location(monkeypatch,tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME",str(tmp_path))
    assert data_path() == tmp_path / "ruuvilinux/sensors.sqlite3"


def test_corrupt_database_is_reported(tmp_path):
    path = tmp_path / "invalid.db"; path.write_bytes(b"not a SQLite database")
    with pytest.raises(sqlite3.DatabaseError): Store(path)
