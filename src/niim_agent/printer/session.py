"""PrinterSession (§7.2): bağlantı ömrü, tek kilit, pil kontrolü."""

import asyncio
import logging
import time
from collections.abc import Awaitable
from dataclasses import dataclass

from bleak.backends.device import BLEDevice
from PIL import Image

from niim_agent.printer.client import Heartbeat, PrinterClient
from niim_agent.printer.discovery import find_printer
from niim_agent.printer.errors import (
    LowBattery,
    PacketError,
    PrinterConnectionError,
    PrinterNotFound,
    PrinterTimeout,
)
from niim_agent.printer.models import PrinterModel
from niim_agent.printer.packet import InfoKey
from niim_agent.printer.transport import BleakTransport

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PrinterInfo:
    name: str
    address: str
    protocol: int
    serial: str | None
    soft_version: float | None
    hard_version: float | None
    battery: int | None  # GET_INFO BATTERY, ham değer
    heartbeat: Heartbeat | None


class PrinterSession:
    """Yazıcıya tek kapı: bağlantıyı işler arasında açık tutar, her erişimi
    self.lock altında yapar.

    ensure() ve close() kilidi kendileri almaz; print_image() ve read_info() alır.
    """

    def __init__(self, model: PrinterModel, address: str = "", idle_disconnect: float = 90,
                 min_battery: int = 0):
        self.model = model
        self.address = address
        self.idle_disconnect = idle_disconnect
        self.min_battery = min_battery
        self.lock = asyncio.Lock()
        self.battery: int | None = None  # son okunan heartbeat power_level (0–4)
        self._transport: BleakTransport | None = None
        self._client: PrinterClient | None = None
        self._device: BLEDevice | None = None  # bu süreçte bulunan cihaz
        self._last_used = 0.0

    @property
    def connected(self) -> bool:
        return self._transport is not None and self._transport.is_connected

    @property
    def name(self) -> str:
        return self._transport.name if self._transport else ""

    @property
    def protocol(self) -> int | None:
        return self._client.protocol if self._client else None

    async def ensure(self) -> PrinterClient:
        """Bağlı bir istemci döndürür; gerekirse bağlanır."""
        if self._client is not None and self.connected:
            self._last_used = time.monotonic()
            return self._client
        await self.close()
        self._transport = await self._open()
        self._client = PrinterClient(self._transport)
        self._last_used = time.monotonic()
        return self._client

    async def _open(self) -> BleakTransport:
        if self.address:
            return await BleakTransport.connect(self.address)
        if self._device is not None:
            try:
                return await BleakTransport.connect(self._device)
            except (PrinterConnectionError, PrinterNotFound) as e:
                logger.info("Bilinen cihaza bağlanılamadı (%s); yeniden taranıyor", e)
                self._device = None
        device = await find_printer(self.model.name)
        transport = await BleakTransport.connect(device)
        self._device = device
        return transport

    async def close(self) -> None:
        if self._transport is not None:
            await self._transport.disconnect()
            logger.info("Yazıcı bağlantısı kapatıldı")
        self._transport = None
        self._client = None

    async def close_if_idle(self) -> None:
        """idle_disconnect süresince kullanılmayan bağlantıyı kapatır. Yazıcı kendi
        kendine uykuya geçiyor; bağlantıyı asılı bırakmayın."""
        if (
            self._transport is not None
            and not self.lock.locked()
            and time.monotonic() - self._last_used >= self.idle_disconnect
        ):
            logger.info("Yazıcı %g sn boşta kaldı", self.idle_disconnect)
            await self.close()

    async def print_image(self, image: Image.Image, density: int | None = None,
                          copies: int = 1) -> None:
        """ensure() → pil kontrolü → sürüm tespiti → baskı."""
        clamped = self.model.clamp_density(density)
        if density and density != clamped:
            logger.info("Yoğunluk %d → %d (%s sınırı)", density, clamped, self.model.name.upper())
        copies = max(1, copies)

        async with self.lock:
            client = await self.ensure()
            await self._check_battery(client)
            protocol = await client.detect_protocol()
            logger.info("Basılıyor: %d×%d px, yoğunluk %d, %d kopya, protokol %d",
                        image.width, image.height, clamped, copies, protocol)
            started = time.monotonic()
            await client.print_image(image, clamped, copies)
            self._last_used = time.monotonic()
        logger.info("Baskı tamamlandı (%.1f sn)", self._last_used - started)

    async def _check_battery(self, client: PrinterClient) -> None:
        try:
            level = (await client.heartbeat()).power_level
        except (PrinterTimeout, PacketError) as e:
            logger.debug("Heartbeat alınamadı: %s", e)
            level = None
        if level is None:
            logger.info("Pil seviyesi okunamadı; baskıya devam ediliyor")
            return
        self.battery = level
        if self.min_battery > 0 and level <= self.min_battery:
            raise LowBattery(
                f"Pil seviyesi {level}/4; min_battery = {self.min_battery} olduğu için basılmadı"
            )
        if level <= 1:
            logger.warning("Pil zayıf: %d/4", level)

    async def read_info(self) -> PrinterInfo:
        async with self.lock:
            client = await self.ensure()
            protocol = await client.detect_protocol()
            serial = await _optional(client.get_info(InfoKey.DEVICESERIAL))
            soft = await _optional(client.get_info(InfoKey.SOFTVERSION))
            hard = await _optional(client.get_info(InfoKey.HARDVERSION))
            battery = await _optional(client.get_info(InfoKey.BATTERY))
            heartbeat = await _optional(client.heartbeat())
            self._last_used = time.monotonic()
        if heartbeat is not None and heartbeat.power_level is not None:
            self.battery = heartbeat.power_level
        address = self._transport.address if self._transport else ""
        return PrinterInfo(self.name, address, protocol, serial, soft, hard, battery, heartbeat)


async def _optional[T](call: Awaitable[T]) -> T | None:
    """Bilgi sorgularında cevapsız kalan alanı None yapar; diğerleri sürer."""
    try:
        return await call
    except (PrinterTimeout, PacketError) as e:
        logger.warning("%s", e)
        return None
