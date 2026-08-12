"""Configuration loading and yt-dlp flag rendering."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from . import paths

JOB_NAME_PATTERN = re.compile(r"[A-Za-z0-9._-]+")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Job:
    name: str
    url: str
    target_dir: Path
    options: tuple[str, ...]
    timer_oncalendar: str | None
    timer_randomized_delay: str | None

    @property
    def archive_file(self) -> Path:
        return paths.archive_file(self.name)


@dataclass(frozen=True)
class Config:
    option_sets: Mapping[str, tuple[str, ...]]
    jobs: Mapping[str, Job]
    source: Path

    def job(self, name: str) -> Job:
        try:
            return self.jobs[name]
        except KeyError:
            known = ", ".join(sorted(self.jobs)) or "none"
            raise ConfigError(f"unknown job {name!r}. Known jobs: {known}") from None

    def argv_for(self, job: Job) -> tuple[str, ...]:
        """Flags from the job's option sets, in declaration order."""
        argv: list[str] = []
        for set_name in job.options:
            try:
                argv.extend(self.option_sets[set_name])
            except KeyError:
                known = ", ".join(sorted(self.option_sets)) or "none"
                raise ConfigError(
                    f"job {job.name!r} wants option set {set_name!r}. Known sets: {known}"
                ) from None
        return tuple(argv)


def render_flags(mapping: Mapping[str, Any]) -> tuple[str, ...]:
    """Turn a YAML option mapping into yt-dlp command line arguments."""
    argv: list[str] = []
    for key, value in mapping.items():
        flag = f"--{key}"
        if value is None or value is True:
            argv.append(flag)
        elif value is False:
            argv.append(f"--no-{key}")
        elif isinstance(value, (list, tuple)):
            for item in value:
                argv.extend((flag, str(item)))
        else:
            argv.extend((flag, str(value)))
    return tuple(argv)


def _as_option_names(value: Any, job_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    raise ConfigError(f"job {job_name!r}: 'options' must be a name or a list of names")


def _parse_job(name: str, raw: Any) -> Job:
    if not JOB_NAME_PATTERN.fullmatch(name):
        raise ConfigError(
            f"job name {name!r} is invalid. Use only letters, digits, '.', '_' and '-'"
        )
    if not isinstance(raw, Mapping):
        raise ConfigError(f"job {name!r} must be a mapping")
    url = raw.get("url")
    if not url:
        raise ConfigError(f"job {name!r} needs a 'url'")
    target_dir = raw.get("target-dir")
    if not target_dir:
        raise ConfigError(f"job {name!r} needs a 'target-dir'")
    return Job(
        name=name,
        url=str(url),
        target_dir=paths.expand(target_dir),
        options=_as_option_names(raw.get("options"), name),
        timer_oncalendar=_opt_str(raw.get("timer-oncalendar")),
        timer_randomized_delay=_opt_str(raw.get("timer-randomized-delay")),
    )


def _opt_str(value: Any) -> str | None:
    return None if value is None else str(value)


def parse(document: Any, source: Path) -> Config:
    if document is None:
        document = {}
    if not isinstance(document, Mapping):
        raise ConfigError(f"{source}: top level must be a mapping")

    raw_sets = document.get("yt-dlp-options") or {}
    if not isinstance(raw_sets, Mapping):
        raise ConfigError(f"{source}: 'yt-dlp-options' must be a mapping")
    option_sets = {}
    for set_name, flags in raw_sets.items():
        if flags is None:
            flags = {}
        if not isinstance(flags, Mapping):
            raise ConfigError(f"{source}: option set {set_name!r} must be a mapping")
        option_sets[str(set_name)] = render_flags(flags)

    raw_jobs = document.get("archive-jobs") or {}
    if not isinstance(raw_jobs, Mapping):
        raise ConfigError(f"{source}: 'archive-jobs' must be a mapping")
    jobs = {str(name): _parse_job(str(name), raw) for name, raw in raw_jobs.items()}

    return Config(option_sets=option_sets, jobs=jobs, source=source)


def load(path: Path | None = None) -> Config:
    target = path or paths.config_file()
    if not target.exists():
        raise ConfigError(f"no config file at {target}")
    document = yaml.safe_load(target.read_text(encoding="utf-8"))
    return parse(document, target)


def ad_hoc_job(url: str, target_dir: Path, options: Sequence[str]) -> Job:
    return Job(
        name="ad-hoc",
        url=url,
        target_dir=paths.expand(target_dir),
        options=tuple(options),
        timer_oncalendar=None,
        timer_randomized_delay=None,
    )
