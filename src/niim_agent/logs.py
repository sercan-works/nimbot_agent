"""Logging kurulumu: konsol (varsa) + dönen log dosyası."""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

FILE_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
CONSOLE_FORMAT = "%(asctime)s %(levelname)-7s %(message)s"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 3


def setup_logging(verbose: bool = False, log_file: Path | None = None) -> None:
    """Kök logger'ı kurar. verbose=True BLE paket loglarını (hex) DEBUG'da açar.

    Pencere açmayan modda (Windows, pythonw) sys.stderr None olabilir; o zaman
    yalnızca dosyaya yazılır (§10.2).
    """
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)

    if sys.stderr is not None:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(logging.Formatter(CONSOLE_FORMAT, datefmt="%H:%M:%S"))
        root.addHandler(console)

    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(
                log_file, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
            )
        except OSError as e:
            logging.getLogger(__name__).warning("Log dosyası açılamadı (%s): %s", log_file, e)
        else:
            handler.setFormatter(logging.Formatter(FILE_FORMAT))
            root.addHandler(handler)

    # bleak'in kendi DEBUG logları çok gürültülü; paket logları bizim logger'larımızdan gelir.
    logging.getLogger("bleak").setLevel(logging.WARNING)
