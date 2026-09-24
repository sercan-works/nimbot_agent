"""Yazıcı komutları, protokol sürümü tespiti, v1 / v4 baskı dizileri (§5.4–5.10).

NiimPrintX nimmy/printer.py'den alındı: https://github.com/labbots/NiimPrintX
(commit b987d3748784a4f001951e2cbcdba708cae2a719), GPL-3.0.
Değişiklikler: bağlantı yönetimi PrinterSession'a taşındı; protokol sürümü
tespiti ve v4 dizisi eklendi (upstream PR #55, issue #32); zaman aşımında None
yerine PrinterTimeout; komut kodları enum adıyla değil hex olarak loglanır;
offset parametreleri, get_rfid ve __del__ kaldırıldı.

§5.6–5.9'daki sabitler, bayt düzenleri ve komut sırası donanımda doğrulandı.
Değiştirmeden önce donanımda deneyin: yazıcı yanlış diziye de "başarılı" deyip
boş etiket basıyor (§5.11).
"""

import asyncio
import logging
import math
import struct
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from PIL import Image, ImageOps

from niim_agent.printer.errors import PacketError, PrinterTimeout
from niim_agent.printer.packet import InfoKey, Packet, RequestCode
from niim_agent.printer.transport import Transport

logger = logging.getLogger(__name__)

COMMAND_TIMEOUT = 10.0
ROW_DELAY = 0.01
END_PAGE_RETRY_DELAY = 0.05
STATUS_POLL_INTERVAL = 0.1
PRINT_WAIT_TIMEOUT = 60.0


@dataclass(frozen=True)
class Heartbeat:
    closing_state: int | None = None
    power_level: int | None = None  # 0–4
    paper_state: int | None = None
    rfid_read_state: int | None = None

    @classmethod
    def parse(cls, data: bytes) -> "Heartbeat":
        # Alanların yeri cevabın uzunluğuna göre değişiyor (§5.5).
        match len(data):
            case 20:
                return cls(paper_state=data[18], rfid_read_state=data[19])
            case 19:
                return cls(data[15], data[16], data[17], data[18])
            case 13:
                return cls(data[9], data[10], data[11], data[12])
            case 10:
                # rfid_read_state = [8] NiimPrintX'teki hâliyle alındı; değiştirmeyin.
                return cls(closing_state=data[8], power_level=data[9], rfid_read_state=data[8])
            case 9:
                return cls(closing_state=data[8])
            case _:
                return cls()


@dataclass(frozen=True)
class PrintStatus:
    page: int
    progress1: int
    progress2: int

    @classmethod
    def parse(cls, data: bytes) -> "PrintStatus | None":
        if len(data) < 4:
            return None
        return cls(*struct.unpack(">HBB", data[:4]))


def decode_serial(data: bytes) -> str:
    """D110 seri numarasını ASCII baytları olarak veriyor; yazdırılabiliyorsa metne çevir."""
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError:
        return data.hex()
    return text if text and text.isprintable() else data.hex()


def encode_image(image: Image.Image) -> Iterator[Packet]:
    """Her satır için bir IMAGE_ROW paketi (§5.9). Siyah piksel → bit 1 (basılır)."""
    img = ImageOps.invert(image.convert("L")).convert("1")
    for y in range(img.height):
        bits = "".join("0" if img.getpixel((x, y)) == 0 else "1" for x in range(img.width))
        row = int(bits, 2).to_bytes(math.ceil(img.width / 8), "big")
        header = struct.pack(">H3BB", y, 0, 0, 0, 1)  # satır no, 3 sayaç (hep 0), 1
        yield Packet(RequestCode.IMAGE_ROW, header + row)


class PrinterClient:
    """Tek bir bağlantı üzerindeki komutlar. Protokol sürümü bağlantı boyunca önbellekte."""

    def __init__(self, transport: Transport):
        self.transport = transport
        self.protocol: int | None = None

    async def send_command(
        self, code: int, data: bytes, timeout: float = COMMAND_TIMEOUT
    ) -> Packet:
        raw = Packet(code, data).to_bytes()
        logger.debug("→ 0x%02X  %s", code, raw.hex(" "))
        try:
            reply = await self.transport.request(raw, timeout)
        except PrinterTimeout:
            raise PrinterTimeout(
                f"Yazıcı 0x{code:02X} komutuna {timeout:g} sn içinde cevap vermedi"
            ) from None
        logger.debug("← 0x%02X  %s", code, reply.hex(" "))
        return Packet.from_bytes(reply)

    async def write_no_notify(self, code: int, data: bytes) -> None:
        raw = Packet(code, data).to_bytes()
        logger.debug("→ 0x%02X  %s  (cevap beklenmiyor)", code, raw.hex(" "))
        await self.transport.write(raw)

    async def _command(self, code: int, data: bytes) -> bool:
        """Cevabın ilk baytı. Yazıcının "01" demesi bir şey kanıtlamaz (§5.11)."""
        packet = await self.send_command(code, data)
        return bool(packet.data) and bool(packet.data[0])

    async def _command_data(self, code: int) -> bytes:
        """Cevap verisi; cevap yoksa ya da bozuksa b""."""
        try:
            return (await self.send_command(code, b"\x01")).data
        except (PrinterTimeout, PacketError) as e:
            logger.debug("0x%02X cevapsız: %s", code, e)
            return b""

    # --- bilgi ---

    async def get_info(self, key: InfoKey) -> int | float | str:
        data = (await self.send_command(RequestCode.GET_INFO, bytes((key,)))).data
        match key:
            case InfoKey.DEVICESERIAL:
                return decode_serial(data)
            case InfoKey.SOFTVERSION | InfoKey.HARDVERSION:
                return int.from_bytes(data, "big") / 100
            case _:
                return int.from_bytes(data, "big")

    async def heartbeat(self) -> Heartbeat:
        return Heartbeat.parse((await self.send_command(RequestCode.HEARTBEAT, b"\x01")).data)

    async def get_print_status(self) -> PrintStatus | None:
        """Cevap yoksa ya da 4 bayttan kısaysa None (§5.10)."""
        return PrintStatus.parse(await self._command_data(RequestCode.GET_PRINT_STATUS))

    # --- protokol sürümü (§5.6) ---

    async def detect_protocol(self) -> int:
        if self.protocol is None:
            self.protocol = await self._detect_protocol()
            logger.info("Protokol sürümü: %d", self.protocol)
        return self.protocol

    async def _detect_protocol(self) -> int:
        # İlk CONNECT'e cevap vermeyen firmware var; bir kez daha denenir.
        reply = await self._command_data(RequestCode.CONNECT)
        if not reply:
            reply = await self._command_data(RequestCode.CONNECT)
        if not reply:
            return 1

        if reply[0] == 3:  # yeni firmware, sürümünü kendisi bildiriyor
            status = await self._command_data(RequestCode.PRINTER_STATUS_DATA)
            if len(status) >= 13:
                fw = status[11] * 100 + status[12]
                logger.debug("Firmware: %d", fw)
                if 204 <= fw < 300:
                    return 3
                if 300 <= fw < 302:
                    return 4
                if fw >= 302:
                    return 5
        # reply[0] == 2: yeni firmware, eski protokol. Diğer her durum: belirlenemedi.
        return 1

    # --- baskı ---

    async def print_image(self, image: Image.Image, density: int = 3, copies: int = 1) -> None:
        if not 1 <= density <= 5:
            raise ValueError(f"Yoğunluk 1–5 arasında olmalı: {density}")
        if copies < 1:
            raise ValueError(f"Kopya sayısı en az 1 olmalı: {copies}")
        if await self.detect_protocol() >= 4:
            await self._print_v4(image, density, copies)
        else:
            await self._print_v1(image, density, copies)

    async def _print_v1(self, image: Image.Image, density: int, copies: int) -> None:
        """Eski firmware dizisi (§5.7). NiimPrintX'ten olduğu gibi; donanımda doğrulanmadı."""
        await self._command(RequestCode.SET_LABEL_DENSITY, bytes((density,)))
        await self._command(RequestCode.SET_LABEL_TYPE, b"\x01")
        await self._command(RequestCode.START_PRINT, b"\x01")
        await self._command(RequestCode.START_PAGE_PRINT, b"\x01")
        # Önce yükseklik (satır sayısı), sonra genişlik.
        await self._command(RequestCode.SET_DIMENSION,
                            struct.pack(">HH", image.height, image.width))
        await self._command(RequestCode.SET_QUANTITY, struct.pack(">H", copies))
        await self._send_rows(image)

        deadline = asyncio.get_running_loop().time() + PRINT_WAIT_TIMEOUT
        while not await self._command(RequestCode.END_PAGE_PRINT, b"\x01"):
            if asyncio.get_running_loop().time() >= deadline:
                raise PrinterTimeout("Yazıcı sayfa sonunu kabul etmedi")
            await asyncio.sleep(END_PAGE_RETRY_DELAY)

        await self._wait_printed(lambda page: page == copies)
        await self._command(RequestCode.END_PRINT, b"\x01")

    async def _print_v4(self, image: Image.Image, density: int, copies: int) -> None:
        """D110_M ve yeni firmware dizisi (§5.8). Donanımda doğrulandı; değerleri değiştirmeyin."""
        await self._command(RequestCode.SET_LABEL_TYPE, b"\x01")
        await self._command(RequestCode.SET_LABEL_DENSITY, bytes((density,)))
        # Toplam sayfa, 4 ayrılmış bayt, sayfa rengi, hız, ayrılmış bayrak.
        await self._command(RequestCode.START_PRINT,
                            struct.pack(">H7B", copies, 0, 0, 0, 0, 0, 1, 0))
        # Yem: yazıcı START_PRINT sonrasındaki ilk paketi yutuyor.
        await self.write_no_notify(RequestCode.GET_PRINT_STATUS, b"\x01")
        # Satır, sütun, kopya, kesim yüksekliği, kesim tipi, ayrılmış, hepsini gönder,
        # parça yüksekliği.
        await self._command(
            RequestCode.SET_DIMENSION,
            struct.pack(">HHHHBBBH", image.height, image.width, copies, 0, 0, 0, 0, 0),
        )
        await self._send_rows(image)
        await self._command(RequestCode.END_PAGE_PRINT, b"\x01")
        await self._wait_printed(lambda page: page >= copies)
        await self._command(RequestCode.END_PRINT, b"\x01")
        # Yem: END_PRINT sonrasındaki ilk paket de yutuluyor.
        await self.write_no_notify(RequestCode.HEARTBEAT, b"\x01")

    async def _send_rows(self, image: Image.Image) -> None:
        # Satırlar ATT onayı beklenmeden yazılır. Yanıtlı yazmada her satır bir
        # bağlantı aralığı bekliyor: 320 satır ~19 sn → yanıtsız ~3.6 sn. D110_M'de
        # donanımda doğrulandı (2026-09-25). 10 ms bekleme yazıcıyı zorlamamak için;
        # beklemesiz gönderim doğrulanmadı (macOS kuyruğu dolunca paket atabilir).
        packets = list(encode_image(image))
        logger.debug("Görsel gönderiliyor: %d×%d px, %d satır", image.width, image.height,
                     len(packets))
        for packet in packets:
            await self.transport.write_without_response(packet.to_bytes())
            await asyncio.sleep(ROW_DELAY)

    async def _wait_printed(self, done: Callable[[int], bool]) -> None:
        """GET_PRINT_STATUS ile baskının bitmesini bekler; cevapsız tur hata sayılmaz."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + PRINT_WAIT_TIMEOUT
        while True:
            status = await self.get_print_status()
            if status is not None:
                logger.debug("Baskı durumu: sayfa %d, ilerleme %d / %d",
                             status.page, status.progress1, status.progress2)
                if done(status.page):
                    return
            if loop.time() >= deadline:
                raise PrinterTimeout(
                    f"Yazıcı baskının bittiğini {PRINT_WAIT_TIMEOUT:g} sn içinde bildirmedi"
                )
            await asyncio.sleep(STATUS_POLL_INTERVAL)
