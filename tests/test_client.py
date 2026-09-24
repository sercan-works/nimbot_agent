import logging

import pytest
from fakes import FakeTransport
from PIL import Image

from niim_agent.printer import client as client_module
from niim_agent.printer.client import Heartbeat, PrinterClient, PrintStatus
from niim_agent.printer.errors import PrinterTimeout
from niim_agent.printer.packet import InfoKey, RequestCode

RC = RequestCode
REQ, WRITE = "request", "write"


@pytest.fixture(autouse=True)
def no_delays(monkeypatch):
    monkeypatch.setattr(client_module, "ROW_DELAY", 0)
    monkeypatch.setattr(client_module, "END_PAGE_RETRY_DELAY", 0)
    monkeypatch.setattr(client_module, "STATUS_POLL_INTERVAL", 0)


def status_data(fw: int) -> bytes:
    """PRINTER_STATUS_DATA cevabı: firmware data[11] * 100 + data[12]."""
    data = bytearray(13)
    data[11], data[12] = divmod(fw, 100)
    return bytes(data)


def page(n: int) -> bytes:
    return n.to_bytes(2, "big") + b"\x64\x64"


V4 = {RC.CONNECT: b"\x03", RC.PRINTER_STATUS_DATA: status_data(301)}
V1 = {RC.CONNECT: b"\x02"}

# 40×12 mm etiketin yazıcıya giden hâli: 96 px genişlik × 320 px yükseklik.
LABEL = Image.new("L", (96, 320), 255)


# --- protokol sürümü (§5.6) ---

@pytest.mark.parametrize(("replies", "expected"), [
    (V4, 4),
    (V1, 1),
    ({RC.CONNECT: None}, 1),
    ({RC.CONNECT: b"\x03", RC.PRINTER_STATUS_DATA: status_data(250)}, 3),
    ({RC.CONNECT: b"\x03", RC.PRINTER_STATUS_DATA: status_data(302)}, 5),
    ({RC.CONNECT: b"\x03", RC.PRINTER_STATUS_DATA: status_data(204)}, 3),
    ({RC.CONNECT: b"\x03", RC.PRINTER_STATUS_DATA: status_data(203)}, 1),
    ({RC.CONNECT: b"\x03", RC.PRINTER_STATUS_DATA: None}, 1),
    ({RC.CONNECT: b"\x03", RC.PRINTER_STATUS_DATA: bytes(12)}, 1),
    ({RC.CONNECT: b""}, 1),
])
async def test_detect_protocol(replies, expected):
    assert await PrinterClient(FakeTransport(replies)).detect_protocol() == expected


async def test_connect_is_retried_once_then_gives_up():
    transport = FakeTransport({RC.CONNECT: None})
    assert await PrinterClient(transport).detect_protocol() == 1
    assert transport.trace() == [(REQ, RC.CONNECT), (REQ, RC.CONNECT)]


async def test_second_connect_answer_is_used():
    transport = FakeTransport({**V4, RC.CONNECT: [None, b"\x03"]})
    assert await PrinterClient(transport).detect_protocol() == 4


async def test_connect_packet_has_prefix_and_protocol_is_cached():
    transport = FakeTransport(V4)
    client = PrinterClient(transport)
    await client.detect_protocol()
    assert transport.raw_requests(RC.CONNECT) == [bytes.fromhex("03 55 55 C1 01 01 C1 AA AA")]
    assert transport.raw_requests(RC.PRINTER_STATUS_DATA) == [
        bytes.fromhex("55 55 A5 01 01 A5 AA AA")
    ]
    sent = len(transport.sent)
    assert await client.detect_protocol() == 4
    assert len(transport.sent) == sent


# --- v4 dizisi (§5.8) ---

async def test_v4_sequence():
    transport = FakeTransport({**V4, RC.GET_PRINT_STATUS: page(1)})
    await PrinterClient(transport).print_image(LABEL, density=3, copies=1)

    assert transport.trace() == [
        (REQ, RC.CONNECT),
        (REQ, RC.PRINTER_STATUS_DATA),
        (REQ, RC.SET_LABEL_TYPE),
        (REQ, RC.SET_LABEL_DENSITY),
        (REQ, RC.START_PRINT),
        (WRITE, RC.GET_PRINT_STATUS),  # yem
        (REQ, RC.SET_DIMENSION),
        ("rows", 320),
        (REQ, RC.END_PAGE_PRINT),
        (REQ, RC.GET_PRINT_STATUS),
        (REQ, RC.END_PRINT),
        (WRITE, RC.HEARTBEAT),  # yem
    ]
    assert transport.raw_requests(RC.SET_LABEL_TYPE) == [bytes.fromhex("55 55 23 01 01 23 AA AA")]
    assert transport.raw_requests(RC.SET_LABEL_DENSITY) == [
        bytes.fromhex("55 55 21 01 03 23 AA AA")
    ]
    assert transport.raw_requests(RC.START_PRINT) == [
        bytes.fromhex("55 55 01 09 00 01 00 00 00 00 00 01 00 08 AA AA")
    ]
    assert transport.raw_requests(RC.SET_DIMENSION) == [
        bytes.fromhex("55 55 13 0D 01 40 00 60 00 01 00 00 00 00 00 00 00 3E AA AA")
    ]
    codes = {packet.type for _, packet in transport.packets}
    assert RC.START_PAGE_PRINT not in codes
    assert RC.SET_QUANTITY not in codes


async def test_v4_copies_go_into_start_print_and_dimension():
    transport = FakeTransport({**V4, RC.GET_PRINT_STATUS: [page(1), page(2), page(3)]})
    await PrinterClient(transport).print_image(LABEL, density=3, copies=3)

    assert transport.raw_requests(RC.START_PRINT) == [
        bytes.fromhex("55 55 01 09 00 03 00 00 00 00 00 01 00 0A AA AA")
    ]
    [dimension] = [p for _, p in transport.packets if p.type == RC.SET_DIMENSION]
    assert dimension.data == bytes.fromhex("01 40 00 60 00 03 00 00 00 00 00 00 00")
    # Görsel bir kez gider; sayfa 3 olana kadar beklenir.
    assert ("rows", 320) in transport.trace()
    assert len(transport.raw_requests(RC.GET_PRINT_STATUS)) == 3


async def test_v4_status_wait_tolerates_missing_and_short_replies():
    transport = FakeTransport({**V4, RC.GET_PRINT_STATUS: [None, b"\x00\x00", page(0), page(1)]})
    await PrinterClient(transport).print_image(LABEL, density=3, copies=1)
    assert len(transport.raw_requests(RC.GET_PRINT_STATUS)) == 4
    assert transport.trace()[-2:] == [(REQ, RC.END_PRINT), (WRITE, RC.HEARTBEAT)]


async def test_v4_status_wait_times_out(monkeypatch):
    monkeypatch.setattr(client_module, "PRINT_WAIT_TIMEOUT", 0.05)
    monkeypatch.setattr(client_module, "STATUS_POLL_INTERVAL", 0.01)
    transport = FakeTransport({**V4, RC.GET_PRINT_STATUS: page(0)})
    with pytest.raises(PrinterTimeout, match="baskının bittiğini"):
        await PrinterClient(transport).print_image(LABEL, density=3, copies=1)
    assert (REQ, RC.END_PRINT) not in transport.trace()


# --- v1 dizisi (§5.7) ---

async def test_v1_sequence():
    transport = FakeTransport({**V1, RC.GET_PRINT_STATUS: page(1)})
    await PrinterClient(transport).print_image(LABEL, density=3, copies=1)

    assert transport.trace() == [
        (REQ, RC.CONNECT),
        (REQ, RC.SET_LABEL_DENSITY),
        (REQ, RC.SET_LABEL_TYPE),
        (REQ, RC.START_PRINT),
        (REQ, RC.START_PAGE_PRINT),
        (REQ, RC.SET_DIMENSION),
        (REQ, RC.SET_QUANTITY),
        ("rows", 320),
        (REQ, RC.END_PAGE_PRINT),
        (REQ, RC.GET_PRINT_STATUS),
        (REQ, RC.END_PRINT),
    ]
    assert transport.raw_requests(RC.START_PRINT) == [bytes.fromhex("55 55 01 01 01 01 AA AA")]
    assert transport.raw_requests(RC.SET_DIMENSION) == [
        bytes.fromhex("55 55 13 04 01 40 00 60 36 AA AA")
    ]
    [quantity] = [p for _, p in transport.packets if p.type == RC.SET_QUANTITY]
    assert quantity.data == b"\x00\x01"


async def test_v1_repeats_end_page_until_accepted():
    transport = FakeTransport({
        **V1,
        RC.END_PAGE_PRINT: [b"\x00", b"\x00", b"\x01"],
        RC.GET_PRINT_STATUS: [page(0), page(2)],
    })
    await PrinterClient(transport).print_image(LABEL, density=2, copies=2)
    assert len(transport.raw_requests(RC.END_PAGE_PRINT)) == 3
    assert len(transport.raw_requests(RC.GET_PRINT_STATUS)) == 2


async def test_print_rejects_bad_arguments():
    client = PrinterClient(FakeTransport(V4))
    with pytest.raises(ValueError):
        await client.print_image(LABEL, density=6)
    with pytest.raises(ValueError):
        await client.print_image(LABEL, copies=0)


# --- cevap çözme (§5.4, §5.5, §5.10) ---

@pytest.mark.parametrize(("length", "expected"), [
    (20, Heartbeat(None, None, 118, 119)),
    (19, Heartbeat(115, 116, 117, 118)),
    (13, Heartbeat(109, 110, 111, 112)),
    (10, Heartbeat(108, 109, None, 108)),
    (9, Heartbeat(108, None, None, None)),
    (4, Heartbeat()),
])
def test_heartbeat_parse(length, expected):
    data = bytes(100 + i for i in range(length))  # data[i] == 100 + i
    assert Heartbeat.parse(data) == expected


async def test_heartbeat_command():
    transport = FakeTransport({RC.HEARTBEAT: bytes(10) + b"\x03\x01\x00"})  # 13 bayt, pil [10]
    assert (await PrinterClient(transport).heartbeat()).power_level == 3
    assert transport.raw_requests(RC.HEARTBEAT) == [bytes.fromhex("55 55 DC 01 01 DC AA AA")]


def test_print_status_parse():
    assert PrintStatus.parse(b"\x00\x02\x10\x20\xff") == PrintStatus(2, 16, 32)
    assert PrintStatus.parse(b"\x00\x02\x10") is None


@pytest.mark.parametrize(("key", "reply", "expected"), [
    (InfoKey.DEVICESERIAL, bytes.fromhex("47423239323530303135"), "GB29250015"),
    (InfoKey.DEVICESERIAL, b"\x01\xfe", "01fe"),
    (InfoKey.SOFTVERSION, (301).to_bytes(2, "big"), 3.01),
    (InfoKey.HARDVERSION, (512).to_bytes(2, "big"), 5.12),
    (InfoKey.BATTERY, b"\x03", 3),
])
async def test_get_info(key, reply, expected):
    transport = FakeTransport({RC.GET_INFO: reply})
    assert await PrinterClient(transport).get_info(key) == expected
    [(_, request)] = transport.packets
    assert request.data == bytes((key,))


async def test_timeout_names_the_command():
    client = PrinterClient(FakeTransport({RC.HEARTBEAT: None}))
    with pytest.raises(PrinterTimeout, match="0xDC"):
        await client.heartbeat()


async def test_unknown_code_is_logged_as_hex(caplog):
    # NiimPrintX enum adıyla loglayıp bilinmeyen kodda ValueError fırlatıyordu (§5.2).
    caplog.set_level(logging.DEBUG, logger="niim_agent")
    await PrinterClient(FakeTransport()).send_command(0x99, b"\x01")
    assert "0x99" in caplog.text
