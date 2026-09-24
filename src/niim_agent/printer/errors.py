"""Yazıcı katmanının hataları. Mesajlar kullanıcıya gösterilir (Türkçe)."""


class PrinterError(Exception):
    """Yazıcıyla ilgili her hatanın tabanı."""


class PrinterNotFound(PrinterError):
    """Taramada yazıcı bulunamadı."""


class PrinterConnectionError(PrinterError):
    """Bluetooth kullanılamıyor, bağlantı kurulamadı ya da koptu."""


class PrinterTimeout(PrinterError):
    """Yazıcı bir komuta süresinde cevap vermedi."""


class PacketError(PrinterError):
    """Yazıcıdan bozuk paket geldi."""


class LowBattery(PrinterError):
    """Pil, yapılandırmadaki min_battery sınırında ya da altında."""
