"""Download TikTok photo posts and store them as Matroska slideshows."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import yt_dlp
from gallery_dl import config as gallery_config
from gallery_dl import job as gallery_job
from gallery_dl import option as gallery_option

from . import probe
from .config import ConfigError, Job

SLIDE_SECONDS = 5
JPEG_SUFFIXES = frozenset({".jpg", ".jpeg"})
AUDIO_SUFFIXES = frozenset({".aac", ".flac", ".m4a", ".mp3", ".ogg", ".opus"})


@dataclass(frozen=True)
class Source:
    url: str
    kind: Literal["photo", "video", "other"]


def _tiktok_host(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host if host == "tiktok.com" or host.endswith(".tiktok.com") else ""


def is_photo_url(url: str) -> bool:
    return bool(_tiktok_host(url) and "/photo/" in urlsplit(url).path)


def _kind(url: str) -> Literal["photo", "video", "other"]:
    if not _tiktok_host(url):
        return "other"
    path = urlsplit(url).path
    if "/photo/" in path:
        return "photo"
    if "/video/" in path:
        return "video"
    return "other"


def _needs_redirect(url: str) -> bool:
    host = _tiktok_host(url)
    path = urlsplit(url).path
    return host in {"vm.tiktok.com", "vt.tiktok.com"} or path.startswith("/t/")


def follow_redirects(url: str, open_url: Callable[..., Any] = urlopen) -> str:
    request = Request(
        url,
        headers={
            "Range": "bytes=0-0",
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "Chrome/128.0 Safari/537.36"
            ),
        },
    )
    try:
        with open_url(request, timeout=30) as response:
            return str(response.geturl())
    except OSError as error:
        raise ConfigError(f"could not resolve {url}: {error}") from error


def resolve_source(
    url: str, resolver: Callable[[str], str] = follow_redirects
) -> Source:
    resolved = resolver(url) if _needs_redirect(url) else url
    return Source(resolved, _kind(resolved))


def command_line(flags: Sequence[str], url: str) -> str:
    argv = ["gallery-dl", "--config-ignore", *flags, url]
    return " ".join(shlex.quote(part) for part in argv)


def _cookies(value: str) -> tuple[str, str | None, str, str, str]:
    browser, _, profile = value.partition(":")
    browser, _, keyring = browser.partition("+")
    browser, _, domain = browser.partition("/")
    if profile.startswith(":"):
        container = profile[1:]
        profile = None
    else:
        profile, _, container = profile.partition("::")
    return browser, profile, keyring, container, domain


def _gallery_settings(flags: Sequence[str]) -> list[tuple[Any, str, Any]]:
    parser = gallery_option.build_parser()
    try:
        args = parser.parse_args(list(flags))
    except SystemExit as error:
        raise ConfigError("gallery-dl rejected its configured options") from error

    settings = list(args.options)
    if args.filename:
        filename = "{filename}.{extension}" if args.filename == "/O" else args.filename
        settings.append(((), "filename", filename))
    if args.directory is not None:
        settings.extend((((), "base-directory", args.directory), ((), "directory", ())))
    if args.postprocessors:
        settings.append(((), "postprocessors", args.postprocessors))
    if args.abort:
        settings.append(((), "skip", "abort:" + args.abort))
    if args.terminate:
        settings.append(((), "skip", "terminate:" + args.terminate))
    if args.cookies_from_browser:
        settings.append(((), "cookies", _cookies(args.cookies_from_browser)))
    if args.options_pp:
        settings.append(((), "postprocessor-options", args.options_pp))
    return settings


def _collector(base: type[Any], archived: set[str]) -> type[Any]:
    class Collector(base):
        def __init__(self, url: Any, parent: Any = None):
            super().__init__(url, parent)
            self.posts: dict[str, dict[str, Any]] = {}

        def _init(self) -> None:
            super()._init()
            predicate = self.pred_post

            def select(url: str, metadata: dict[str, Any]) -> bool:
                post_id = str(metadata.get("id", ""))
                if metadata.get("post_type") != "image" or post_id in archived:
                    return False
                return bool(predicate(url, metadata))

            self.pred_post = select

        def handle_directory(self, metadata: dict[str, Any]) -> None:
            self.posts[str(metadata["id"])] = metadata.copy()
            super().handle_directory(metadata)

    return Collector


def _read_archive(path: Path) -> set[str]:
    try:
        return set(path.read_text(encoding="utf-8").splitlines())
    except FileNotFoundError:
        return set()


def _record_archive(path: Path, post_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as archive:
        archive.write(post_id + "\n")


def _yt_dlp_info(metadata: dict[str, Any], source_url: str) -> dict[str, Any]:
    post_id = str(metadata["id"])
    user = str(metadata.get("user") or "")
    title = str(
        metadata.get("title") or metadata.get("desc") or f"TikTok photo #{post_id}"
    )
    info: dict[str, Any] = {
        "id": post_id,
        "title": title,
        "description": str(metadata.get("desc") or title),
        "ext": "mkv",
        "webpage_url": source_url,
        "original_url": source_url,
        "extractor": "TikTok",
        "extractor_key": "TikTok",
        "uploader": user,
        "uploader_id": user,
        "channel": user,
    }
    date = metadata.get("date")
    if isinstance(date, datetime):
        info["timestamp"] = int(date.timestamp())
    return info


def _destination(
    options: dict[str, Any], metadata: dict[str, Any], source_url: str
) -> Path:
    with yt_dlp.YoutubeDL(options) as ydl:
        path = Path(ydl.prepare_filename(_yt_dlp_info(metadata, source_url)))
    return path.with_suffix(".mkv")


def _ffmetadata(metadata: dict[str, Any], source_url: str, image_count: int) -> str:
    def escape(value: Any) -> str:
        text = " ".join(str(value).splitlines())
        for character in ("\\", "=", ";", "#"):
            text = text.replace(character, "\\" + character)
        return text

    post_id = str(metadata["id"])
    title = metadata.get("title") or metadata.get("desc") or f"TikTok photo #{post_id}"
    lines = [
        ";FFMETADATA1",
        f"title={escape(title)}",
        f"artist={escape(metadata.get('user') or '')}",
        f"comment={escape(source_url)}",
        "media_type=tiktok-photo",
    ]
    for index in range(image_count):
        start = index * SLIDE_SECONDS * 1000
        end = (index + 1) * SLIDE_SECONDS * 1000
        lines.extend(
            (
                "[CHAPTER]",
                "TIMEBASE=1/1000",
                f"START={start}",
                f"END={end}",
                f"title=Image {index + 1}",
            )
        )
    return "\n".join(lines) + "\n"


def mux_slideshow(
    images: Sequence[Path],
    audio: Path | None,
    destination: Path,
    metadata: dict[str, Any],
    source_url: str,
) -> None:
    if not images:
        raise ConfigError(f"TikTok photo {metadata['id']} has no images")
    unsupported = [
        path.name for path in images if path.suffix.lower() not in JPEG_SUFFIXES
    ]
    if unsupported:
        names = ", ".join(unsupported)
        raise ConfigError(f"TikTok photo {metadata['id']} has non-JPEG images: {names}")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ConfigError("ffmpeg is not on PATH")

    work = images[0].parent
    concat = work / "slides.ffconcat"
    concat_lines = ["ffconcat version 1.0"]
    for image in images:
        concat_lines.extend(
            (
                f"file {image.name}",
                f"option framerate 1/{SLIDE_SECONDS}",
                f"duration {SLIDE_SECONDS}",
            )
        )
    concat.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")

    chapters = work / "chapters.ffmeta"
    chapters.write_text(
        _ffmetadata(metadata, source_url, len(images)), encoding="utf-8"
    )

    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(
        prefix=f".{destination.stem}-", dir=destination.parent
    ) as temp:
        staged = Path(temp) / "slideshow.mkv"
        argv = [
            ffmpeg,
            "-nostdin",
            "-y",
            "-v",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat),
        ]
        metadata_input = 1
        if audio:
            argv.extend(("-stream_loop", "-1", "-i", str(audio)))
            metadata_input = 2
        argv.extend(("-f", "ffmetadata", "-i", str(chapters), "-map", "0:v:0"))
        if audio:
            argv.extend(("-map", "1:a:0"))
        argv.extend(
            (
                "-map_metadata",
                str(metadata_input),
                "-map_chapters",
                str(metadata_input),
                "-c",
                "copy",
                "-r",
                f"1/{SLIDE_SECONDS}",
            )
        )
        if audio:
            argv.extend(("-t", str(len(images) * SLIDE_SECONDS)))
        argv.extend(("-f", "matroska", str(staged)))
        result = subprocess.run(argv, capture_output=True, text=True, check=False)
        if result.returncode:
            raise ConfigError(f"ffmpeg failed: {result.stderr.strip()}")
        try:
            streams = probe.probe(staged)
        except probe.MediaError as error:
            raise ConfigError(str(error)) from error
        if streams.video != 1 or (audio and not streams.has_audio):
            raise ConfigError("ffmpeg created an incomplete slideshow")
        os.replace(staged, destination)


def _post_files(directory: Path) -> tuple[list[Path], Path | None]:
    files = sorted(path for path in directory.iterdir() if path.is_file())
    images = [path for path in files if path.suffix.lower() in JPEG_SUFFIXES]
    audio = [path for path in files if path.suffix.lower() in AUDIO_SUFFIXES]
    if len(audio) > 1:
        raise ConfigError(f"gallery-dl created multiple audio files in {directory}")
    return images, audio[0] if audio else None


def run_photo_job(
    job_config: Job,
    flags: Sequence[str],
    yt_dlp_options: dict[str, Any],
    source_url: str,
    simulate: bool = False,
) -> int:
    archived = _read_archive(job_config.gallery_archive_file)

    with TemporaryDirectory(prefix="yt-dlp-archiver-gallery-") as temp:
        root = Path(temp)
        settings = _gallery_settings(flags)
        settings.extend(
            (
                ((), "base-directory", str(root)),
                ((), "directory", ("{id}",)),
                ((), "filename", "{num:>02}.{extension}"),
                ((), "archive", None),
                ((), "input", False),
                (("extractor", "tiktok"), "photos", True),
                (("extractor", "tiktok"), "audio", True),
                (("extractor", "tiktok"), "videos", False),
                (("extractor", "tiktok"), "covers", False),
                (("extractor", "tiktok"), "subtitles", False),
            )
        )
        base = gallery_job.SimulationJob if simulate else gallery_job.DownloadJob
        collector_type = _collector(base, archived)
        with gallery_config.apply(settings):
            download = collector_type(source_url)
            status = download.run()

        if simulate or status:
            return status

        for post_id, metadata in download.posts.items():
            try:
                images, audio = _post_files(root / post_id)
                expected = len(metadata.get("imagePost", {}).get("images", ()))
                if expected and len(images) != expected:
                    raise ConfigError(
                        f"TikTok photo {post_id} has {len(images)} of {expected} images"
                    )
                destination = _destination(yt_dlp_options, metadata, source_url)
                if not destination.exists():
                    mux_slideshow(images, audio, destination, metadata, source_url)
                    print(f"[gallery-dl] Muxed {destination}")
                _record_archive(job_config.gallery_archive_file, post_id)
            except (ConfigError, OSError) as error:
                print(f"[gallery-dl] error: {error}")
                status |= 1
        return status
