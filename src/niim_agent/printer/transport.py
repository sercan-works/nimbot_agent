"""BLE katmanı (§5.2): bleak sarmalayıcı.

NiimPrintX nimmy/bluetooth.py ve PrinterClient'in bağlantı / karakteristik
kısmından alındı: https://github.com/labbots/NiimPrintX
(commit b987d3748784a4f001951e2cbcdba708cae2a719), GPL-3.0.
Değişiklikler: bağlantı kararı is_connected ile (bleak >= 1.0'da connect() None
döner); zaman aşımında None yerine PrinterTimeout; bildirim zaman aşımında da
kapatılır (CoreBluetooth ikinci start_notify'da ValueError fırlatıyor);
loguru yerine logging.
"""

import asyncio
import logging
from typing import Protocol

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.exc import BleakDeviceNotFoundError, BleakError

from niim_agent.printer.errors import (
    PrinterConnectionError,
    PrinterError,
    PrinterNotFound,
    PrinterTimeout,
)

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT = 10.0
REQUIRED_PROPERTIES = ("read", "write-without-response", "notify")


class Transport(Protocol):
    """PrinterClient'in kullandığı arayüz; testlerde FakeTransport bunu uygular."""

    @property
    def is_connected(self) -> bool: ...

    async def request(self, data: bytes, timeout: float) -> bytes:
        """Paketi yazar ve ilk bildirimi döndürür. Süre dolarsa PrinterTimeout."""
        ...

    async def write(self, data: bytes) -> None:
        """Paketi yazar, cevap beklemez."""
        ...


def find_characteristic(services) -> BleakGATTCharacteristic | None:
    """Tam olarak bir karakteristiği olan ve o karakteristiği read,
    write-without-response ve notify destekleyen servisi seçer."""
    for service in services:
        chars = service.characteristics
        if len(chars) == 1 and all(p in chars[0].properties for p in REQUIRED_PROPERTIES):
            return chars[0]
    return None


class BleakTransport:
    def __init__(self, client: BleakClient, characteristic: BleakGATTCharacteristic,
                 device: BLEDevice | None, address: str, name: str):
        self._client = client
        self._char = characteristic
        # response= verilmezse bleak aynı seçimi yapıyor ama artık uyarı veriyor.
        self._write_response = "write" in characteristic.properties
        self.device = device
        self.address = address
        self.name = name

    @classmethod
    async def connect(cls, target: BLEDevice | str) -> "BleakTransport":
        """target: taramadan gelen BLEDevice ya da platforma özel adres (§5.3)."""
        client = BleakClient(target, timeout=CONNECT_TIMEOUT)
        try:
            await client.connect()
        except BleakDeviceNotFoundError as e:
            raise PrinterNotFound(f"{target} adresli yazıcı bulunamadı") from e
        except (BleakError, TimeoutError, OSError) as e:
            raise PrinterConnectionError(f"Yazıcıya bağlanılamadı: {e or type(e).__name__}") from e
        if not client.is_connected:
            raise PrinterConnectionError("Yazıcıya bağlanılamadı")

        char = find_characteristic(client.services)
        if char is None:
            await _quiet_disconnect(client)
            raise PrinterError("Bluetooth karakteristiği bulunamadı")

        if isinstance(target, BLEDevice):
            device, address, name = target, target.address, target.name or target.address
        else:
            device, address, name = None, target, target
        logger.info("Yazıcıya bağlanıldı: %s", name)
        logger.debug("Karakteristik: %s %s", char.uuid, char.properties)
        return cls(client, char, device, address, name)

    @property
    def is_connected(self) -> bool:
        return self._client.is_connected

    async def request(self, data: bytes, timeout: float) -> bytes:
        # NiimPrintX'teki sıra korunuyor: start_notify → yaz → ilk bildirim → stop_notify.
        reply: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()

        def on_notify(_sender, payload: bytearray) -> None:
            if not reply.done():
                reply.set_result(bytes(payload))

        try:
            await self._client.start_notify(self._char, on_notify)
            try:
                await self._write(data)
                return await asyncio.wait_for(reply, timeout)
            except TimeoutError:
                raise PrinterTimeout("Yazıcı cevap vermedi") from None
            finally:
                await self._stop_notify()
        except (BleakError, OSError) as e:
            raise PrinterConnectionError(f"Bluetooth hatası: {e}") from e

    async def write(self, data: bytes) -> None:
        try:
            await self._write(data)
        except (BleakError, OSError) as e:
            raise PrinterConnectionError(f"Bluetooth hatası: {e}") from e

    async def disconnect(self) -> None:
        await _quiet_disconnect(self._client)

    async def _write(self, data: bytes) -> None:
        await self._client.write_gatt_char(self._char, data, response=self._write_response)

    async def _stop_notify(self) -> None:
        try:
            await self._client.stop_notify(self._char)
        except Exception as e:  # bağlantı koptuysa bildirim zaten kapanmıştır
            logger.debug("stop_notify başarısız: %s", e)


async def _quiet_disconnect(client: BleakClient) -> None:
    try:
        await client.disconnect()
    except Exception as e:
        logger.debug("Bağlantı kapatılırken hata: %s", e)
