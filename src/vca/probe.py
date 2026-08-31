"""Read media stream data with ffprobe."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class MediaError(Exception):
    pass


@dataclass(frozen=True)
class Streams:
    audio: int
    video: int

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
            "stream=codec_type:stream_disposition=attached_pic",
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
    video = [
        stream
        for stream in streams
        if stream.get("codec_type") == "video"
        and not stream.get("disposition", {}).get("attached_pic")
    ]
    return Streams(audio=len(audio), video=len(video))
