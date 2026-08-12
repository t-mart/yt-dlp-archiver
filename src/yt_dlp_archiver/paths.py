"""XDG base directory resolution."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "yt-dlp-archiver"


def _base(env_var: str, fallback: str) -> Path:
    value = os.environ.get(env_var)
    if value:
        return Path(value)
    return Path.home() / fallback


def config_home() -> Path:
    return _base("XDG_CONFIG_HOME", ".config")


def state_home() -> Path:
    return _base("XDG_STATE_HOME", ".local/state")


def config_file() -> Path:
    return config_home() / APP_NAME / "config.yaml"


def archive_file(job_name: str) -> Path:
    return state_home() / APP_NAME / f"{job_name}.txt"


def systemd_user_dir() -> Path:
    return config_home() / "systemd" / "user"


def expand(path: str | Path) -> Path:
    return Path(os.path.expandvars(str(path))).expanduser()
