from pathlib import Path

import pytest

from niim_agent import __version__
from niim_agent.cli import build_parser


@pytest.mark.parametrize("argv", [["-v", "scan"], ["scan", "-v"]])
def test_common_flags_before_or_after_command(argv):
    assert build_parser().parse_args(argv).verbose is True


def test_config_flag_after_command():
    args = build_parser().parse_args(["info", "--config", "x.toml"])
    assert (args.config, args.verbose) == ("x.toml", False)


def test_print_defaults():
    args = build_parser().parse_args(["print", "etiket.png"])
    assert (args.png, args.rotate, args.density, args.copies) == (Path("etiket.png"), 270, 3, 1)


@pytest.mark.parametrize("argv", [
    ["print", "a.png", "--rotate", "45"],
    ["print", "a.png", "--density", "6"],
    ["print", "a.png", "--copies", "0"],
    [],
])
def test_invalid_arguments(argv):
    with pytest.raises(SystemExit) as info:
        build_parser().parse_args(argv)
    assert info.value.code == 2


def test_version(capsys):
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--version"])
    assert __version__ in capsys.readouterr().out
