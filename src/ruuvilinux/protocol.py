"""RAWv2 implementation from Ruuvi's official format 5 specification.

Bleak strips the two company-ID bytes: manufacturer_data[0x0499] is a
24-byte payload, unlike CoreBluetooth's company-prefixed manufacturer field.
https://docs.ruuvi.com/communication/bluetooth-advertisements/data-format-5-rawv2
"""
from dataclasses import dataclass
import struct

COMPANY_ID = 0x0499

@dataclass(frozen=True)
class Reading:
    temperature: float | None
    humidity: float | None
    pressure: float | None  # hPa
    acceleration_x: float | None  # g
    acceleration_y: float | None
    acceleration_z: float | None
    voltage: float | None  # V
    tx_power: int | None
    movement: int | None
    sequence: int | None
    mac: str | None


def decode_rawv2(payload: bytes) -> Reading | None:
    if len(payload) != 24 or payload[0] != 5:
        return None
    t, h, p, x, y, z, power, movement, sequence = struct.unpack(
        ">hHHhhhHBH", payload[1:18])
    battery, tx = power >> 5, power & 31
    mac_bytes = payload[18:24]
    signed = lambda v, scale: None if v == -32768 else v / scale
    return Reading(
        signed(t, 200), None if h == 65535 else h / 400,
        None if p == 65535 else (p + 50000) / 100,
        signed(x, 1000), signed(y, 1000), signed(z, 1000),
        None if battery == 2047 else (battery + 1600) / 1000,
        None if tx == 31 else tx * 2 - 40,
        None if movement == 255 else movement,
        None if sequence == 65535 else sequence,
        None if mac_bytes == b"\xff" * 6 else ":".join(f"{b:02X}" for b in mac_bytes),
    )


def decode_advertisement(manufacturer_data: dict[int, bytes]) -> Reading | None:
    payload = manufacturer_data.get(COMPANY_ID)
    return decode_rawv2(payload) if payload is not None else None
