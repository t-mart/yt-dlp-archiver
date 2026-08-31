"""Load the video-collection-archiver configuration."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from . import paths

COLLECTION_NAME_PATTERN = re.compile(r"[A-Za-z0-9._-]+")
TOP_LEVEL_KEYS = frozenset({"yt-dlp-options", "gallery-dl-options", "collections"})
COLLECTION_KEYS = frozenset({"url", "target-dir"})


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Collection:
    name: str
    url: str
    target_dir: Path

    @property
    def cache_file(self) -> Path:
        return paths.cache_file(self.name)


@dataclass(frozen=True)
class Config:
    yt_dlp_options: tuple[str, ...]
    gallery_dl_options: tuple[str, ...]
    collections: Mapping[str, Collection]
    source: Path

    def collection(self, name: str) -> Collection:
        try:
            return self.collections[name]
        except KeyError:
            known = ", ".join(sorted(self.collections)) or "none"
            raise ConfigError(
                f"unknown collection {name!r}. Known collections: {known}"
            ) from None


def render_flags(
    mapping: Mapping[str, Any], section: str = "options"
) -> tuple[str, ...]:
    """Convert a YAML option mapping to command-line arguments."""
    argv: list[str] = []
    for key, value in mapping.items():
        if not isinstance(key, str) or not key or key.startswith("-"):
            raise ConfigError(f"{section} option names must omit the '--' prefix")
        flag = f"--{key}"
        if value is None or value is True:
            argv.append(flag)
        elif value is False:
            argv.append(f"--no-{key}")
        elif isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, (Mapping, list, tuple)):
                    raise ConfigError(
                        f"{section} option {key!r} has an invalid list value"
                    )
                argv.extend((flag, str(item)))
        elif isinstance(value, Mapping):
            raise ConfigError(
                f"{section} must contain one global option mapping, not profiles"
            )
        else:
            argv.extend((flag, str(value)))
    return tuple(argv)


def _parse_options(
    document: Mapping[str, Any], source: Path, section: str
) -> tuple[str, ...]:
    raw = document.get(section)
    if raw is None:
        return ()
    if not isinstance(raw, Mapping):
        raise ConfigError(f"{source}: {section!r} must be a mapping")
    try:
        return render_flags(raw, section)
    except ConfigError as error:
        raise ConfigError(f"{source}: {error}") from None


def _parse_collection(name: str, raw: Any, source: Path) -> Collection:
    if not COLLECTION_NAME_PATTERN.fullmatch(name):
        raise ConfigError(
            f"{source}: collection name {name!r} is invalid. "
            "Use letters, digits, '.', '_', or '-'"
        )
    if not isinstance(raw, Mapping):
        raise ConfigError(f"{source}: collection {name!r} must be a mapping")
    unknown = sorted(set(raw) - COLLECTION_KEYS, key=str)
    if unknown:
        names = ", ".join(repr(key) for key in unknown)
        raise ConfigError(
            f"{source}: collection {name!r} has unsupported keys: {names}"
        )
    url = raw.get("url")
    if not isinstance(url, str) or not url.strip():
        raise ConfigError(f"{source}: collection {name!r} needs a nonempty 'url'")
    target_dir = raw.get("target-dir")
    if not isinstance(target_dir, (str, Path)) or not str(target_dir):
        raise ConfigError(f"{source}: collection {name!r} needs a 'target-dir'")
    return Collection(name, url, paths.expand(target_dir))


def parse(document: Any, source: Path) -> Config:
    if not isinstance(document, Mapping):
        raise ConfigError(f"{source}: top level must be a mapping")
    if "archive-jobs" in document:
        raise ConfigError(f"{source}: use 'collections', not 'archive-jobs'")
    unknown = sorted(set(document) - TOP_LEVEL_KEYS, key=str)
    if unknown:
        names = ", ".join(repr(key) for key in unknown)
        raise ConfigError(f"{source}: unsupported top-level keys: {names}")
    if "collections" not in document:
        raise ConfigError(f"{source}: top level needs a 'collections' mapping")
    raw_collections = document["collections"]
    if not isinstance(raw_collections, Mapping):
        raise ConfigError(f"{source}: 'collections' must be a mapping")
    collections = {
        str(name): _parse_collection(str(name), raw, source)
        for name, raw in raw_collections.items()
    }
    return Config(
        yt_dlp_options=_parse_options(document, source, "yt-dlp-options"),
        gallery_dl_options=_parse_options(document, source, "gallery-dl-options"),
        collections=collections,
        source=source,
    )


def load(path: Path | None = None) -> Config:
    target = path or paths.config_file()
    if not target.exists():
        raise ConfigError(f"no configuration file at {target}")
    try:
        document = yaml.safe_load(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise ConfigError(f"cannot read {target}: {error}") from error
    return parse(document, target)


def oneshot_collection(url: str, target_dir: Path) -> Collection:
    return Collection("oneshot", url, paths.expand(target_dir))
