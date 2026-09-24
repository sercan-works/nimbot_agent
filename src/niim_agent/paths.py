"""Config, log ve state dizinleri (§8). Esas olan platformdirs'in döndürdüğüdür."""

from pathlib import Path

import platformdirs

APP_NAME = "niim-agent"
CONFIG_ENV = "NIIM_AGENT_CONFIG"


def config_dir() -> Path:
    return Path(platformdirs.user_config_dir(APP_NAME, appauthor=False))


def default_config_path() -> Path:
    return config_dir() / "config.toml"


def log_dir() -> Path:
    return Path(platformdirs.user_log_dir(APP_NAME, appauthor=False))


def log_file() -> Path:
    return log_dir() / "agent.log"


def state_dir() -> Path:
    return Path(platformdirs.user_state_dir(APP_NAME, appauthor=False))
