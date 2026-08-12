"""ffprobe and ffmpeg helpers."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

MEDIA_SUFFIXES = frozenset({".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".flv"})


class MediaError(Exception):
    pass


@dataclass(frozen=True)
class Streams:
    audio: int
    video: int
    audio_bitrate: int | None

    @property
    def has_audio(self) -> bool:
        return self.audio > 0


def _require(binary: str) -> str:
    found = shutil.which(binary)
    if not found:
        raise MediaError(f"{binary} is not on PATH. Install ffmpeg")
    return found


def probe(path: Path) -> Streams:
    """Count the real streams in a file. Metadata from the site is not trusted."""
    result = subprocess.run(
        [
            _require("ffprobe"),
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,bit_rate",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise MediaError(f"ffprobe failed on {path}: {result.stderr.strip()}")

    streams = json.loads(result.stdout or "{}").get("streams", [])
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    video = [s for s in streams if s.get("codec_type") == "video"]
    bitrate = None
    if audio:
        try:
            bitrate = int(audio[0]["bit_rate"])
        except KeyError, TypeError, ValueError:
            bitrate = None
    return Streams(audio=len(audio), video=len(video), audio_bitrate=bitrate)


def has_audio(path: Path) -> bool:
    return probe(path).has_audio


def video_codec(path: Path) -> str | None:
    """First video codec, named the way yt-dlp names it in a format dictionary."""
    result = subprocess.run(
        [
            _require("ffprobe"),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    streams = json.loads(result.stdout or "{}").get("streams", [])
    if not streams:
        return None
    name = streams[0].get("codec_name")
    return {"hevc": "h265", "avc1": "h264"}.get(name, name)


def mux_audio(video_source: Path, audio_source: Path, destination: Path) -> None:
    """Copy every stream of video_source plus the first audio stream of audio_source.

    '-map 0' keeps subtitles and the embedded thumbnail. Nothing is re-encoded.
    """
    result = subprocess.run(
        [
            _require("ffmpeg"),
            "-y",
            "-v",
            "error",
            "-i",
            str(video_source),
            "-i",
            str(audio_source),
            "-map",
            "0",
            "-map",
            "1:a:0",
            "-c",
            "copy",
            "-map_metadata",
            "0",
            "-movflags",
            "+faststart",
            str(destination),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise MediaError(f"ffmpeg mux failed: {result.stderr.strip()}")


def source_url(path: Path) -> str | None:
    """Read the source URL that --embed-metadata writes into the comment tag."""
    result = subprocess.run(
        [
            _require("ffprobe"),
            "-v",
            "error",
            "-show_entries",
            "format_tags=comment,purl",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    tags = json.loads(result.stdout or "{}").get("format", {}).get("tags", {})
    for key in ("purl", "comment"):
        value = tags.get(key)
        if value and str(value).startswith("http"):
            return str(value)
    return None
