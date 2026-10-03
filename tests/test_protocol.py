import pytest
from ruuvilinux.protocol import decode_rawv2, decode_advertisement
VALID = bytes.fromhex("0512FC5394C37C0004FFFC040CAC364200CDCBB8334C884F")


def test_official_valid_vector():
    r = decode_rawv2(VALID)
    assert r.temperature == pytest.approx(24.3)
    assert r.humidity == pytest.approx(53.49)
    assert r.pressure == pytest.approx(1000.44)
    assert (r.acceleration_x, r.acceleration_y, r.acceleration_z) == pytest.approx((0.004, -0.004, 1.036))
    assert r.voltage == pytest.approx(2.977)
    assert (r.tx_power, r.movement, r.sequence, r.mac) == (4, 66, 205, "CB:B8:33:4C:88:4F")


def test_official_unavailable_vector():
    r = decode_rawv2(bytes.fromhex("058000FFFFFFFF800080008000FFFFFFFFFFFFFFFFFFFFFF"))
    assert all(v is None for v in vars(r).values())


@pytest.mark.parametrize("hex,t,h,p,a,v,tx,m,seq", [
    ("057FFFFFFEFFFE7FFF7FFF7FFFFFDEFEFFFECBB8334C884F",163.835,163.835,1155.34,32.767,3.646,20,254,65534),
    ("058001000000008001800180010000000000CBB8334C884F",-163.835,0,500,-32.767,1.6,-40,0,0),
])
def test_official_extremes(hex,t,h,p,a,v,tx,m,seq):
    r = decode_rawv2(bytes.fromhex(hex))
    assert (r.temperature,r.humidity,r.pressure,r.acceleration_x,r.voltage) == pytest.approx((t,h,p,a,v))
    assert (r.tx_power,r.movement,r.sequence) == (tx,m,seq)


@pytest.mark.parametrize("length", range(24))
def test_truncated_packets(length):
    assert decode_rawv2(VALID[:length]) is None


def test_framing_and_company():
    assert decode_rawv2(VALID+b"\0") is None
    assert decode_rawv2(bytes([6])+VALID[1:]) is None
    assert decode_advertisement({0x0499: VALID}) == decode_rawv2(VALID)
    assert decode_advertisement({0x1234: VALID}) is None
    assert decode_advertisement({}) is None
    assert decode_advertisement({0x0499: b"\x99\x04"+VALID}) is None
