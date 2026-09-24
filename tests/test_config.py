import pytest

from niim_agent import paths
from niim_agent.config import Config, ConfigError, PrinterConfig, load_config


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.delenv(paths.CONFIG_ENV, raising=False)
    monkeypatch.setattr(paths, "default_config_path", lambda: tmp_path / "yok" / "config.toml")


def write(tmp_path, text, name="config.toml"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults_when_no_file():
    assert load_config() == Config(path=None, printer=PrinterConfig())
    assert PrinterConfig() == PrinterConfig("d110", "", 90, 0)


def test_default_location_is_used(monkeypatch, tmp_path):
    path = write(tmp_path, '[printer]\nmodel = "b21"\n')
    monkeypatch.setattr(paths, "default_config_path", lambda: path)
    assert load_config().printer.model == "b21"


def test_explicit_path_must_exist(tmp_path):
    with pytest.raises(ConfigError, match="bulunamadı"):
        load_config(tmp_path / "eksik.toml")


def test_env_var_and_flag_precedence(monkeypatch, tmp_path):
    from_env = write(tmp_path, '[printer]\nmodel = "b1"\n', "env.toml")
    from_flag = write(tmp_path, '[printer]\nmodel = "b18"\n', "flag.toml")
    monkeypatch.setenv(paths.CONFIG_ENV, str(from_env))
    assert load_config().printer.model == "b1"
    assert load_config(from_flag).printer.model == "b18"


def test_printer_section(tmp_path):
    path = write(tmp_path, """
agent_name = "ofis-mac"

[printer]
model = "D11_H"
address = " 1A2B3C4D-0000-0000-0000-000000000000 "
idle_disconnect = 120
min_battery = 1

[agent]
poll_interval = 3

[[source]]
name = "atlantis"
""")
    config = load_config(path)
    assert config.path == path
    assert config.printer == PrinterConfig(
        "d11_h", "1A2B3C4D-0000-0000-0000-000000000000", 120.0, 1
    )


def test_all_errors_reported_together(tmp_path):
    path = write(tmp_path, """
[printer]
model = "q1"
address = 5
idle_disconnect = 0
min_battery = true
min_batery = 1
""")
    with pytest.raises(ConfigError) as info:
        load_config(path)
    errors = info.value.errors
    assert len(errors) == 5
    assert any("min_batery" in e for e in errors)
    assert any("model bilinmiyor: 'q1'" in e for e in errors)
    assert any("address" in e for e in errors)
    assert any("idle_disconnect" in e for e in errors)
    assert any("min_battery 0–4" in e for e in errors)


@pytest.mark.parametrize("value", ["5", "-1", "2.5", '"2"'])
def test_min_battery_range(tmp_path, value):
    with pytest.raises(ConfigError, match="min_battery"):
        load_config(write(tmp_path, f"[printer]\nmin_battery = {value}\n"))


def test_toml_syntax_error(tmp_path):
    with pytest.raises(ConfigError, match="TOML"):
        load_config(write(tmp_path, "[printer\nmodel = "))
