"""Test yardımcıları: yazılan paketleri kaydeden sahte transport."""

from niim_agent.printer.errors import PrinterTimeout
from niim_agent.printer.packet import CONNECT_PREFIX, HEAD, Packet, RequestCode

Reply = bytes | None  # None: cevap yok (zaman aşımı)


def decode(raw: bytes) -> Packet:
    """Yazılan paketi çözer; CONNECT'in 0x03 önekini atar."""
    if raw.startswith(CONNECT_PREFIX + HEAD):
        raw = raw[1:]
    return Packet.from_bytes(raw)


def frame(type_: int, data: bytes) -> bytes:
    """Cevap paketi. Cevaplar normal çerçevede gelir, CONNECT'inki de."""
    return Packet(type_, data).to_bytes().removeprefix(CONNECT_PREFIX)


class FakeTransport:
    """request() için komut koduna göre hazır cevap verir, yazılan her paketi kaydeder.

    replies[kod] bayt ise her seferinde o döner; liste ise sırayla tüketilir, son
    eleman tekrarlanır. None cevap yok demektir (PrinterTimeout). Tanımsız
    kodlara b"\\x01" döner.
    """

    def __init__(self, replies: dict[int, Reply | list[Reply]] | None = None):
        self.replies = {code: list(r) if isinstance(r, list) else r
                        for code, r in (replies or {}).items()}
        # ("request" | "write" | "write_nr", ham bayt); write_nr = yanıtsız yazma
        self.sent: list[tuple[str, bytes]] = []
        self.is_connected = True

    @property
    def packets(self) -> list[tuple[str, Packet]]:
        return [(kind, decode(raw)) for kind, raw in self.sent]

    def raw_requests(self, code: int) -> list[bytes]:
        return [raw for kind, raw in self.sent if kind == "request" and decode(raw).type == code]

    def trace(self) -> list[tuple[str, int]]:
        """(tür, kod) dizisi; art arda gelen IMAGE_ROW'lar ("rows", adet) olarak toplanır."""
        out: list[tuple[str, int]] = []
        for kind, packet in self.packets:
            if packet.type == RequestCode.IMAGE_ROW:
                assert kind == "write_nr", "görsel satırları yanıtsız gönderilmeli"
                if out and out[-1][0] == "rows":
                    out[-1] = ("rows", out[-1][1] + 1)
                else:
                    out.append(("rows", 1))
            else:
                out.append((kind, packet.type))
        return out

    async def request(self, data: bytes, timeout: float) -> bytes:
        self.sent.append(("request", data))
        code = decode(data).type
        reply = self._next_reply(code)
        if reply is None:
            raise PrinterTimeout("cevap yok")
        return frame(code, reply)

    async def write(self, data: bytes) -> None:
        self.sent.append(("write", data))

    async def write_without_response(self, data: bytes) -> None:
        self.sent.append(("write_nr", data))

    def _next_reply(self, code: int) -> Reply:
        reply = self.replies.get(code, b"\x01")
        if isinstance(reply, list):
            return reply.pop(0) if len(reply) > 1 else reply[0]
        return reply
