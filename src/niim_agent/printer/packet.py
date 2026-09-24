"""Niimbot paket çerçevesi ve komut kodları (§5.1, §5.4).

NiimPrintX nimmy/packet.py ve nimmy/printer.py'deki enum'lardan alındı:
https://github.com/labbots/NiimPrintX (commit b987d3748784a4f001951e2cbcdba708cae2a719), GPL-3.0.
Değişiklikler: CONNECT öneki ve PRINTER_STATUS_DATA / CONNECT kodları eklendi,
assert yerine PacketError.
"""

from dataclasses import dataclass
from enum import IntEnum

from niim_agent.printer.errors import PacketError

HEAD = b"\x55\x55"
TAIL = b"\xaa\xaa"
CONNECT_PREFIX = b"\x03"


class RequestCode(IntEnum):
    START_PRINT = 0x01
    START_PAGE_PRINT = 0x03
    SET_DIMENSION = 0x13
    SET_QUANTITY = 0x15
    GET_RFID = 0x1A
    ALLOW_PRINT_CLEAR = 0x20
    SET_LABEL_DENSITY = 0x21
    SET_LABEL_TYPE = 0x23
    GET_INFO = 0x40
    IMAGE_ROW = 0x85
    GET_PRINT_STATUS = 0xA3
    PRINTER_STATUS_DATA = 0xA5
    CONNECT = 0xC1
    HEARTBEAT = 0xDC
    END_PAGE_PRINT = 0xE3
    END_PRINT = 0xF3


class InfoKey(IntEnum):
    DENSITY = 1
    PRINTSPEED = 2
    LABELTYPE = 3
    LANGUAGETYPE = 6
    AUTOSHUTDOWNTIME = 7
    DEVICETYPE = 8
    SOFTVERSION = 9
    BATTERY = 10
    DEVICESERIAL = 11
    HARDVERSION = 12


def _checksum(type_: int, data: bytes) -> int:
    checksum = type_ ^ len(data)
    for b in data:
        checksum ^= b
    return checksum


@dataclass(frozen=True)
class Packet:
    type: int
    data: bytes

    def to_bytes(self) -> bytes:
        raw = bytes(
            (*HEAD, self.type, len(self.data), *self.data, _checksum(self.type, self.data), *TAIL)
        )
        # Tek istisna: CONNECT paketinin başına 0x03 eklenir (§5.1).
        if self.type == RequestCode.CONNECT:
            return CONNECT_PREFIX + raw
        return raw

    @classmethod
    def from_bytes(cls, raw: bytes) -> "Packet":
        raw = bytes(raw)
        if len(raw) < 7 or raw[:2] != HEAD or raw[-2:] != TAIL:
            raise PacketError(f"Geçersiz paket çerçevesi: {raw.hex(' ')}")
        type_, len_ = raw[2], raw[3]
        if len(raw) != len_ + 7:
            raise PacketError(f"Paket uzunluğu tutmuyor ({len_} bayt veri): {raw.hex(' ')}")
        data = raw[4 : 4 + len_]
        if _checksum(type_, data) != raw[4 + len_]:
            raise PacketError(f"Paket checksum hatası: {raw.hex(' ')}")
        return cls(type_, data)

    def __repr__(self) -> str:
        return f"Packet(0x{self.type:02X}, {self.data.hex(' ')})"
