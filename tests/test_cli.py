from pathlib import Path

import pytest
from typer.testing import CliRunner

from vca import cli

runner = CliRunner()


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(
        """yt-dlp-options:
  embed-metadata:
gallery-dl-options:
  cookies-from-browser: firefox
collections:
  demo:
    url: https://www.tiktok.com/@user/collection/demo-1
    target-dir: ~/Downloads/demo
""",
        encoding="utf-8",
    )
    return path


def test_run_uses_a_collection_argument_and_prints_configuration(monkeypatch, tmp_path):
    config = _config(tmp_path)
    calls = []

    def run_collection(_config, collection, **options):
        calls.append((collection.name, options))
        return 0

    monkeypatch.setattr(cli.runner, "run_collection", run_collection)
    result = runner.invoke(
        cli.app, ["run", "demo", "--verbose", "--config", str(config)]
    )

    assert result.exit_code == 0
    assert "Configuration:" in result.stdout
    assert "yt-dlp options:     --embed-metadata" in result.stdout
    assert "gallery-dl options: --cookies-from-browser firefox" in result.stdout
    assert calls == [
        (
            "demo",
            {
                "use_cache": True,
                "simulate": False,
                "verbose": True,
                "log": cli._echo,
            },
        )
    ]


def test_oneshot_disables_the_cache(monkeypatch, tmp_path):
    config = _config(tmp_path)
    calls = []

    def run_collection(_config, collection, **options):
        calls.append((collection.url, collection.target_dir, options))
        return 0

    monkeypatch.setattr(cli.runner, "run_collection", run_collection)
    result = runner.invoke(
        cli.app,
        [
            "oneshot",
            "https://example.com/collection",
            "--target-dir",
            str(tmp_path / "target"),
            "--config",
            str(config),
        ],
    )

    assert result.exit_code == 0
    assert "cache:              disabled" in result.stdout
    assert calls[0][2]["use_cache"] is False


@pytest.mark.parametrize("command", ["list", "show", "verify"])
def test_removed_commands_are_not_available(command):
    result = runner.invoke(cli.app, [command])
    assert result.exit_code == 2
    assert "No such command" in result.output


def test_systemd_install_passes_the_command_line_schedule(monkeypatch, tmp_path):
    config = _config(tmp_path)
    calls = []

    def install(names, on_calendar, randomized_delay):
        calls.append((names, on_calendar, randomized_delay))
        return []

    monkeypatch.setattr(cli.units, "install", install)
    result = runner.invoke(
        cli.app,
        [
            "systemd",
            "install",
            "demo",
            "--on-calendar",
            "daily",
            "--randomized-delay",
            "30m",
            "--no-enable",
            "--config",
            str(config),
        ],
    )

    assert result.exit_code == 0
    assert calls == [(["demo"], "daily", "30m")]


def test_short_help_flag_works():
    result = runner.invoke(cli.app, ["run", "-h"])
    assert result.exit_code == 0
    assert "Download new items" in result.stdout
