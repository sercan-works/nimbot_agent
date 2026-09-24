"""Yapılandırma (§8): TOML okuma, doğrulama, varsayılanlar.

M1 yalnızca [printer] bölümünü okur; diğer bölümler sonraki kilometre taşlarında.
"""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from niim_agent import paths
from niim_agent.printer.models import MODELS


class ConfigError(Exception):
    """Yapılandırma hataları; hepsi tek listede (§8)."""

    def __init__(self, errors: list[str], path: Path | None = None):
        super().__init__("\n".join(errors))
        self.errors = errors
        self.path = path


@dataclass(frozen=True)
class PrinterConfig:
    model: str = "d110"
    address: str = ""  # boş = ada göre tara; dolu = doğrudan bağlan (platforma özel)
    idle_disconnect: float = 90
    min_battery: int = 0  # 0 = engelleme yok; 1–4 = bu seviye ve altında basma


@dataclass(frozen=True)
class Config:
    path: Path | None  # None: config dosyası yok, varsayılanlar kullanılıyor
    printer: PrinterConfig = field(default_factory=PrinterConfig)


def resolve_path(cli_path: str | Path | None = None) -> tuple[Path, bool]:
    """Sıra: --config, NIIM_AGENT_CONFIG, varsayılan konum. İkinci değer: yol açıkça verildi mi."""
    if cli_path:
        return Path(cli_path).expanduser(), True
    if env := os.environ.get(paths.CONFIG_ENV):
        return Path(env).expanduser(), True
    return paths.default_config_path(), False


def load_config(cli_path: str | Path | None = None) -> Config:
    path, explicit = resolve_path(cli_path)
    if not path.exists():
        if explicit:
            raise ConfigError([f"Config dosyası bulunamadı: {path}"], path)
        return Config(path=None)
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError([f"TOML sözdizimi hatası: {e}"], path) from e
    except OSError as e:
        raise ConfigError([f"Config dosyası okunamadı: {e}"], path) from e

    errors: list[str] = []
    printer = _parse_printer(data.get("printer", {}), errors)
    if errors:
        raise ConfigError(errors, path)
    return Config(path=path, printer=printer)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _parse_printer(section: Any, errors: list[str]) -> PrinterConfig:
    defaults = PrinterConfig()
    if not isinstance(section, dict):
        errors.append("[printer] bir tablo olmalı")
        return defaults

    for key in sorted(set(section) - {"model", "address", "idle_disconnect", "min_battery"}):
        errors.append(f"[printer] bilinmeyen anahtar: {key}")

    model = section.get("model", defaults.model)
    if not isinstance(model, str) or model.lower() not in MODELS:
        errors.append(f"[printer] model bilinmiyor: {model!r} (bilinenler: {', '.join(MODELS)})")
        model = defaults.model

    address = section.get("address", defaults.address)
    if not isinstance(address, str):
        errors.append(f"[printer] address metin olmalı: {address!r}")
        address = defaults.address

    idle = section.get("idle_disconnect", defaults.idle_disconnect)
    if not (_is_int(idle) or isinstance(idle, float)) or idle <= 0:
        errors.append(f"[printer] idle_disconnect pozitif bir sayı (sn) olmalı: {idle!r}")
        idle = defaults.idle_disconnect

    min_battery = section.get("min_battery", defaults.min_battery)
    if not _is_int(min_battery) or not 0 <= min_battery <= 4:
        errors.append(f"[printer] min_battery 0–4 arasında bir tam sayı olmalı: {min_battery!r}")
        min_battery = defaults.min_battery

    return PrinterConfig(model.lower(), address.strip(), float(idle), min_battery)
