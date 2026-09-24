import pytest

from niim_agent.printer.errors import PacketError
from niim_agent.printer.packet import Packet, RequestCode

RC = RequestCode

# Ek B: NiimPrintX'in NiimbotPacket.to_bytes() koduyla üretilmiş vektörler.
VECTORS = [
    (RC.HEARTBEAT, "01", "55 55 DC 01 01 DC AA AA"),
    (RC.CONNECT, "01", "03 55 55 C1 01 01 C1 AA AA"),
    (RC.PRINTER_STATUS_DATA, "01", "55 55 A5 01 01 A5 AA AA"),
    (RC.SET_LABEL_TYPE, "01", "55 55 23 01 01 23 AA AA"),
    (RC.SET_LABEL_DENSITY, "03", "55 55 21 01 03 23 AA AA"),
    (RC.GET_PRINT_STATUS, "01", "55 55 A3 01 01 A3 AA AA"),
    (RC.END_PAGE_PRINT, "01", "55 55 E3 01 01 E3 AA AA"),
    (RC.END_PRINT, "01", "55 55 F3 01 01 F3 AA AA"),
    (RC.START_PRINT, "01", "55 55 01 01 01 01 AA AA"),
    (RC.SET_DIMENSION, "01 40 00 60", "55 55 13 04 01 40 00 60 36 AA AA"),
    (RC.START_PRINT, "00 01 00 00 00 00 00 01 00",
     "55 55 01 09 00 01 00 00 00 00 00 01 00 08 AA AA"),
    (RC.START_PRINT, "00 03 00 00 00 00 00 01 00",
     "55 55 01 09 00 03 00 00 00 00 00 01 00 0A AA AA"),
    (RC.SET_DIMENSION, "01 40 00 60 00 01 00 00 00 00 00 00 00",
     "55 55 13 0D 01 40 00 60 00 01 00 00 00 00 00 00 00 3E AA AA"),
]


@pytest.mark.parametrize(("code", "data", "expected"), VECTORS)
def test_to_bytes_matches_vectors(code, data, expected):
    assert Packet(code, bytes.fromhex(data)).to_bytes() == bytes.fromhex(expected)


@pytest.mark.parametrize(("code", "data", "expected"),
                         [v for v in VECTORS if v[0] != RC.CONNECT])
def test_from_bytes_round_trip(code, data, expected):
    packet = Packet.from_bytes(bytes.fromhex(expected))
    assert packet == Packet(code, bytes.fromhex(data))


def test_connect_reply_uses_normal_frame():
    reply = Packet.from_bytes(bytes.fromhex("55 55 C1 01 01 C1 AA AA"))
    assert reply == Packet(RC.CONNECT, b"\x01")


def test_from_bytes_accepts_bytearray():
    # bleak bildirimleri bytearray olarak gelir.
    assert Packet.from_bytes(bytearray.fromhex("55 55 DC 01 01 DC AA AA")).type == RC.HEARTBEAT


@pytest.mark.parametrize("raw", [
    "54 55 DC 01 01 DC AA AA",  # başlangıç işareti
    "55 55 DC 01 01 DC AA AB",  # bitiş işareti
    "55 55 DC 01 01 DD AA AA",  # checksum
    "55 55 DC 02 01 DC AA AA",  # uzunluk alanı
    "55 55 DC 01 01 00 DC AA AA",  # fazla bayt
    "55 55 AA AA",  # çok kısa
])
def test_from_bytes_rejects_bad_packets(raw):
    with pytest.raises(PacketError):
        Packet.from_bytes(bytes.fromhex(raw))


def test_request_codes_match_spec():
    assert {c.name: c.value for c in RequestCode} == {
        "START_PRINT": 0x01,
        "START_PAGE_PRINT": 0x03,
        "SET_DIMENSION": 0x13,
        "SET_QUANTITY": 0x15,
        "GET_RFID": 0x1A,
        "ALLOW_PRINT_CLEAR": 0x20,
        "SET_LABEL_DENSITY": 0x21,
        "SET_LABEL_TYPE": 0x23,
        "GET_INFO": 0x40,
        "IMAGE_ROW": 0x85,
        "GET_PRINT_STATUS": 0xA3,
        "PRINTER_STATUS_DATA": 0xA5,
        "CONNECT": 0xC1,
        "HEARTBEAT": 0xDC,
        "END_PAGE_PRINT": 0xE3,
        "END_PRINT": 0xF3,
    }
