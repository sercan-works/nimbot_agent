"""Komut satırı (§9). M1: scan, info, test, print."""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from niim_agent import __version__, paths
from niim_agent.config import Config, ConfigError, load_config
from niim_agent.imaging import DEFAULT_ROTATE, ROTATIONS, build_test_label, prepare_image
from niim_agent.logs import setup_logging
from niim_agent.printer import (
    PrinterConnectionError,
    PrinterError,
    PrinterNotFound,
    get_model,
)
from niim_agent.printer.discovery import scan
from niim_agent.printer.models import DEFAULT_DENSITY
from niim_agent.printer.session import PrinterSession

logger = logging.getLogger("niim_agent")

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_CONFIG = 2


def _out(text: str = "") -> None:
    """Kullanıcıya çıktı. Pencere açmayan modda stdout olmayabilir (§10.2)."""
    if sys.stdout is not None:
        sys.stdout.write(text + "\n")
        sys.stdout.flush()


def _session(config: Config) -> PrinterSession:
    p = config.printer
    return PrinterSession(get_model(p.model), p.address, p.idle_disconnect, p.min_battery)


def _value(value: object) -> str:
    return "?" if value is None else str(value)


async def cmd_scan(args: argparse.Namespace, config: Config) -> int:
    logger.info("Bluetooth taranıyor…")
    results = await scan()
    if not results:
        _out("Cihaz bulunamadı.")
        return EXIT_OK

    prefix = config.printer.model
    _out(f"  {'Ad':<28} {'Adres':<36} {'RSSI':>5} {'UUID':>5}")
    for r in results:
        mark = "*" if r.name.lower().startswith(prefix) else " "
        _out(f"{mark} {r.name or '-':<28} {r.address:<36} {r.rssi:>5} {r.service_uuid_count:>5}")
    _out()
    _out(f"* adı {prefix.upper()} ile başlıyor. "
         "Baskı servisini taşıyan kaydın UUID sayısı 0 olmalı.")
    return EXIT_OK


async def cmd_info(args: argparse.Namespace, config: Config) -> int:
    session = _session(config)
    try:
        info = await session.read_info()
    finally:
        await session.close()

    hb = info.heartbeat
    rows = [
        ("Yazıcı", info.name),
        ("Adres", info.address),
        ("Seri no", info.serial),
        ("Yazılım sürümü", info.soft_version),
        ("Donanım sürümü", info.hard_version),
        ("Protokol sürümü", info.protocol),
        ("Pil", f"{hb.power_level}/4" if hb and hb.power_level is not None else None),
        ("Pil (GET_INFO)", info.battery),
    ]
    if hb is not None:
        rows.append((
            "Heartbeat",
            f"kapak={_value(hb.closing_state)} kağıt={_value(hb.paper_state)} "
            f"rfid={_value(hb.rfid_read_state)}",
        ))
    for label, value in rows:
        _out(f"{label:<16}: {_value(value)}")
    return EXIT_OK


async def cmd_test(args: argparse.Namespace, config: Config) -> int:
    image = prepare_image(build_test_label(), DEFAULT_ROTATE, get_model(config.printer.model))
    return await _print(config, image, DEFAULT_DENSITY, 1)


async def cmd_print(args: argparse.Namespace, config: Config) -> int:
    try:
        png = args.png.read_bytes()
    except OSError as e:
        logger.error("Dosya okunamadı: %s (%s)", args.png, e.strerror or e)
        return EXIT_ERROR
    try:
        image = prepare_image(png, args.rotate, get_model(config.printer.model))
    except ValueError as e:
        logger.error("%s", e)
        return EXIT_ERROR
    return await _print(config, image, args.density, args.copies)


async def _print(config: Config, image, density: int, copies: int) -> int:
    session = _session(config)
    try:
        await session.print_image(image, density, copies)
    finally:
        await session.close()
    return EXIT_OK


def _positive_int(value: str) -> int:
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError("en az 1 olmalı")
    return n


def _add_common(parser: argparse.ArgumentParser, suppress: bool) -> None:
    # Alt komutlarda SUPPRESS: "niim-agent -v scan" ile "niim-agent scan -v" ikisi de çalışsın.
    parser.add_argument("-v", "--verbose", action="store_true",
                        default=argparse.SUPPRESS if suppress else False,
                        help="BLE paket loglarını (hex) göster")
    parser.add_argument("--config", metavar="PATH",
                        default=argparse.SUPPRESS if suppress else None,
                        help="config dosyasının yolu")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="niim-agent",
        description="Buluttan etiket işi çekip Bluetooth ile Niimbot yazıcıya basan agent.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    _add_common(parser, suppress=False)
    sub = parser.add_subparsers(dest="command", required=True, metavar="KOMUT")

    p = sub.add_parser("scan", help="yakındaki BLE cihazlarını listele")
    p.set_defaults(handler=cmd_scan)
    _add_common(p, suppress=True)

    p = sub.add_parser("info", help="yazıcıya bağlanıp bilgilerini göster")
    p.set_defaults(handler=cmd_info)
    _add_common(p, suppress=True)

    p = sub.add_parser("test", help="deneme etiketi bas")
    p.set_defaults(handler=cmd_test)
    _add_common(p, suppress=True)

    p = sub.add_parser("print", help="PNG dosyasından bas")
    p.add_argument("png", type=Path, help="PNG dosyası (yatay çizilmiş)")
    p.add_argument("--rotate", type=int, choices=ROTATIONS, default=DEFAULT_ROTATE,
                   help="saat yönünde derece (varsayılan: %(default)s)")
    p.add_argument("--density", type=int, choices=range(1, 6), default=DEFAULT_DENSITY,
                   metavar="1-5",
                   help="baskı yoğunluğu; model sınırına kırpılır (varsayılan: %(default)s)")
    p.add_argument("--copies", type=_positive_int, default=1,
                   help="kopya sayısı (varsayılan: %(default)s)")
    p.set_defaults(handler=cmd_print)
    _add_common(p, suppress=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.verbose, paths.log_file())

    try:
        config = load_config(args.config)
    except ConfigError as e:
        logger.error("Yapılandırma hatası (%s):", e.path)
        for err in e.errors:
            logger.error("  - %s", err)
        return EXIT_CONFIG
    logger.debug("Config: %s", config.path or "yok, varsayılanlar kullanılıyor")

    try:
        return asyncio.run(args.handler(args, config))
    except PrinterError as e:
        logger.error("%s", e)
        if isinstance(e, PrinterNotFound | PrinterConnectionError):
            logger.error("Yazıcının açık ve yakında olduğundan, Bluetooth'un açık olduğundan ve "
                         "Niimbot telefon uygulamasının yazıcıya bağlı olmadığından emin olun.")
        return EXIT_ERROR
    except KeyboardInterrupt:
        logger.warning("İptal edildi")
        return EXIT_ERROR
    except Exception:
        logger.exception("Beklenmeyen hata")
        return EXIT_ERROR
