"""Yazıcıyı bulma (§5.3) ve `scan` komutu için tarama."""

import logging
from dataclasses import dataclass

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.exc import BleakError

from niim_agent.printer.errors import PrinterConnectionError, PrinterNotFound

logger = logging.getLogger(__name__)

SCAN_TIMEOUT = 8.0


@dataclass(frozen=True)
class ScanResult:
    name: str
    address: str
    rssi: int
    service_uuid_count: int


def _device_name(device: BLEDevice, adv: AdvertisementData) -> str:
    return device.name or adv.local_name or ""


def _name_matches(prefix: str, device: BLEDevice, adv: AdvertisementData) -> bool:
    return _device_name(device, adv).lower().startswith(prefix.lower())


async def find_printer(prefix: str, timeout: float = SCAN_TIMEOUT) -> BLEDevice:
    """Adı `prefix` ile başlayan yazıcıyı bulur.

    Niimbot birden fazla reklam yayınlıyor; baskı servisini taşıyan, servis UUID
    listesi boş olanı. Önce ona göre hızlı arar (ilk eşleşmede döner), olmazsa
    tam taramada yalnızca ada bakar.
    """
    def is_printer(device: BLEDevice, adv: AdvertisementData) -> bool:
        return _name_matches(prefix, device, adv) and not adv.service_uuids

    try:
        device = await BleakScanner.find_device_by_filter(is_printer, timeout=timeout)
        if device is not None:
            logger.info("Yazıcı bulundu: %s (%s)", device.name, device.address)
            return device

        logger.info("Hızlı taramada yazıcı bulunamadı; tam tarama yapılıyor")
        found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    except (BleakError, OSError) as e:
        raise PrinterConnectionError(f"Bluetooth taraması başarısız: {e}") from e

    names = set()
    for device, adv in found.values():
        if _name_matches(prefix, device, adv):
            logger.info("Yazıcı bulundu (tam tarama): %s (%s)", device.name, device.address)
            return device
        if name := _device_name(device, adv):
            names.add(name)
    seen = ", ".join(sorted(names)) or "yok"
    raise PrinterNotFound(f"{prefix.upper()} yazıcı bulunamadı. Görülen cihazlar: {seen}")


async def scan(timeout: float = SCAN_TIMEOUT) -> list[ScanResult]:
    """Yakındaki BLE cihazlarını, sinyal gücüne göre sıralı döndürür."""
    try:
        found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    except (BleakError, OSError) as e:
        raise PrinterConnectionError(f"Bluetooth taraması başarısız: {e}") from e
    results = [
        ScanResult(_device_name(device, adv), device.address, adv.rssi, len(adv.service_uuids))
        for device, adv in found.values()
    ]
    return sorted(results, key=lambda r: r.rssi, reverse=True)
