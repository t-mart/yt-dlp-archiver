"""Download collection items and update the collection cache."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import yt_dlp
from yt_dlp.utils import DownloadError

from . import gallery
from .config import Collection, Config, ConfigError

OUTPUT_TEMPLATE = "%(title).180B - %(extractor)s %(id)s.%(ext)s"


def build_argv(
    config: Config, collection: Collection, simulate: bool = False
) -> list[str]:
    """Build yt-dlp arguments without the host configuration."""
    argv = ["--ignore-config", *config.yt_dlp_options]
    argv += ["--paths", f"home:{collection.target_dir}"]
    argv += ["--output", OUTPUT_TEMPLATE]
    argv += ["--replace-in-metadata", "extractor", "^TikTok$", "tiktok"]
    argv.append("--no-download-archive")
    if simulate:
        argv.append("--simulate")
    return argv


def build_options(argv: Sequence[str]) -> dict[str, Any]:
    """Use the yt-dlp parser to build its option dictionary."""
    try:
        return dict(yt_dlp.parse_options(list(argv)).ydl_opts)
    except SystemExit as error:
        raise ConfigError("yt-dlp rejected its configured options") from error


def _collection_urls(options: dict[str, Any], url: str) -> list[str]:
    lookup = {
        **options,
        "download_archive": None,
        "extract_flat": True,
        "lazy_playlist": False,
        "noprogress": True,
        "postprocessors": [],
        "quiet": True,
        "simulate": True,
        "skip_download": True,
        "verbose": False,
    }
    try:
        with yt_dlp.YoutubeDL(lookup) as ydl:
            info = ydl.extract_info(url, download=False)
    except DownloadError as error:
        raise ConfigError(f"yt-dlp could not read collection {url}: {error}") from error
    if info is None:
        raise ConfigError(f"yt-dlp could not read collection {url}")
    entries = info.get("entries")
    if entries is None:
        item_url = info.get("webpage_url") or info.get("original_url") or url
        return [str(item_url)]
    urls: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry_url = entry.get("webpage_url") or entry.get("url")
        if isinstance(entry_url, str):
            urls.append(entry_url)
    return list(dict.fromkeys(urls))


def _read_cache(path: Path) -> set[str]:
    try:
        return set(path.read_text(encoding="utf-8").splitlines())
    except FileNotFoundError:
        return set()
    except OSError as error:
        raise ConfigError(f"cannot read cache file {path}: {error}") from error


def _append_cache(path: Path, url: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as cache:
            cache.write(f"{url}\n")
    except OSError as error:
        raise ConfigError(f"cannot update cache file {path}: {error}") from error


def _download_video(options: dict[str, Any], url: str) -> int:
    with yt_dlp.YoutubeDL(options) as ydl:
        return ydl.download([url])


def _download_item(
    config: Config,
    options: dict[str, Any],
    url: str,
    simulate: bool,
) -> int:
    source = gallery.resolve_source(url)
    if source.kind == "other":
        return _download_video(options, source.url)
    result = gallery.run_photo_job(
        config.gallery_dl_options,
        options,
        source.url,
        simulate,
    )
    if result.is_photo or result.status:
        return result.status
    return _download_video(options, source.url)


def run_collection(
    config: Config,
    collection: Collection,
    *,
    use_cache: bool,
    simulate: bool = False,
    verbose: bool = False,
    log: Callable[[str], None] = print,
) -> int:
    if not simulate:
        try:
            collection.target_dir.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise ConfigError(
                f"cannot create target directory {collection.target_dir}: {error}"
            ) from error
    options = build_options(build_argv(config, collection, simulate))

    log(f"Read collection: {collection.url}")
    urls = _collection_urls(options, collection.url)
    cached = _read_cache(collection.cache_file) if use_cache else set()
    pending = [url for url in urls if url not in cached]
    cached_count = len(cached & set(urls))
    log(f"Items: {len(urls)} total, {cached_count} cached, {len(pending)} new")

    if verbose:
        for index, url in enumerate(urls, start=1):
            log(f"Item {index}/{len(urls)}: {url}")

    status = 0
    for url in pending:
        result = _download_item(config, options, url, simulate)
        status |= result
        if result == 0 and use_cache and not simulate:
            _append_cache(collection.cache_file, url)
    return status
