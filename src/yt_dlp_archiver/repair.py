"""Recover a missing audio track.

Sites can report an audio codec on a format that carries no audio stream.
TikTok does this on its H.265 formats. yt-dlp trusts the report and merges
nothing, so the output file has no sound. Only the downloaded bytes tell the
truth, so probe the result and repair it.
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from yt_dlp import YoutubeDL
from yt_dlp.postprocessor import PostProcessor
from yt_dlp.utils import PostProcessingError

from . import probe

MIRROR_SUFFIX = re.compile(r"-\d+$")
MAX_CANDIDATES = 2


def mirror_key(format_id: str) -> str:
    """Collapse CDN mirrors. TikTok serves '-0' and '-1' with identical content."""
    return MIRROR_SUFFIX.sub("", format_id)


def repair_candidates(
    formats: Sequence[Mapping[str, Any]],
    downloaded_format_id: str | None,
    downloaded_vcodec: str | None,
) -> list[Mapping[str, Any]]:
    """Order the formats that could supply the missing audio.

    Audio-only formats come first, because they are the cheapest true source.
    Then formats from a different video codec family, because the family that
    was downloaded is the one that lied. Highest bitrate wins inside each tier:
    sites tie audio quality to the video rung, and 'abr' is usually absent.
    """
    excluded = mirror_key(downloaded_format_id) if downloaded_format_id else None
    seen: set[str] = set()
    candidates = []
    for fmt in formats:
        format_id = fmt.get("format_id")
        if not format_id or fmt.get("acodec") == "none":
            continue
        key = mirror_key(format_id)
        if key == excluded or key in seen:
            continue
        seen.add(key)
        candidates.append(fmt)

    def rank(fmt: Mapping[str, Any]) -> tuple[int, float]:
        audio_only = fmt.get("vcodec") in (None, "none")
        if audio_only:
            tier, rate = 0, fmt.get("abr") or fmt.get("tbr")
        else:
            tier = 1 if fmt.get("vcodec") != downloaded_vcodec else 2
            rate = fmt.get("tbr")
        # An absent bitrate sorts last inside its tier.
        return (tier, -rate if rate is not None else 1.0)

    return sorted(candidates, key=rank)


@dataclass(frozen=True)
class Outcome:
    repaired: bool
    reason: str
    format_id: str | None = None
    audio_bitrate: int | None = None


def child_params(
    params: Mapping[str, Any], format_id: str, outdir: Path
) -> dict[str, Any]:
    """Parent options minus everything that writes output or records history."""
    child = dict(params)
    child.update(
        {
            "format": format_id,
            "postprocessors": [],
            "progress_hooks": [],
            "post_hooks": [],
            "download_archive": None,
            "writesubtitles": False,
            "writeautomaticsub": False,
            "writethumbnail": False,
            "write_all_thumbnails": False,
            "writeinfojson": False,
            "writedescription": False,
            "writeannotations": False,
            "outtmpl": {"default": str(outdir / "%(id)s.%(format_id)s.%(ext)s")},
            "paths": {},
            "simulate": False,
            "overwrites": True,
            "break_on_existing": False,
            "match_filter": None,
            "noplaylist": True,
            "quiet": True,
            "noprogress": True,
            "no_warnings": True,
        }
    )
    child.pop("final_ext", None)
    return child


def fetch_formats(params: Mapping[str, Any], url: str) -> list[Mapping[str, Any]]:
    lookup = dict(params)
    lookup.update(
        {
            "postprocessors": [],
            "progress_hooks": [],
            "post_hooks": [],
            "download_archive": None,
            "simulate": True,
            "skip_download": True,
            "quiet": True,
            "noprogress": True,
            "no_warnings": True,
            "noplaylist": True,
            "match_filter": None,
        }
    )
    with YoutubeDL(lookup) as ydl:
        info = ydl.extract_info(url, download=False)
    return list((info or {}).get("formats") or [])


def _download_format(
    params: Mapping[str, Any], url: str, format_id: str, outdir: Path
) -> Path | None:
    with YoutubeDL(child_params(params, format_id, outdir)) as ydl:
        info = ydl.extract_info(url, download=True)
    for entry in (info or {}).get("requested_downloads") or []:
        filepath = entry.get("filepath")
        if filepath and Path(filepath).exists():
            return Path(filepath)
    return None


def repair_file(
    params: Mapping[str, Any],
    url: str,
    media_path: Path,
    formats: Sequence[Mapping[str, Any]],
    downloaded_format_id: str | None,
    downloaded_vcodec: str | None,
    log: Callable[[str], None] = lambda _: None,
    max_candidates: int = MAX_CANDIDATES,
) -> Outcome:
    """Mux audio from another format into media_path. The video stays untouched."""
    candidates = repair_candidates(formats, downloaded_format_id, downloaded_vcodec)
    if not candidates:
        return Outcome(False, "no other format is available")

    for fmt in candidates[:max_candidates]:
        format_id = str(fmt["format_id"])
        log(f"trying format {format_id} as the audio source")
        with TemporaryDirectory(prefix="yt-dlp-archiver-") as tmp:
            try:
                source = _download_format(params, url, format_id, Path(tmp))
            except Exception as error:  # noqa: BLE001 - try the next candidate
                log(f"format {format_id} did not download: {error}")
                continue
            if source is None:
                log(f"format {format_id} produced no file")
                continue
            streams = probe.probe(source)
            if not streams.has_audio:
                log(f"format {format_id} also has no audio")
                continue

            # Stage beside the target so the replace is atomic and same-filesystem.
            staged = media_path.with_name(
                f".{media_path.name}.repair{media_path.suffix}"
            )
            try:
                probe.mux_audio(media_path, source, staged)
                shutil.move(str(staged), str(media_path))
            finally:
                staged.unlink(missing_ok=True)
            return Outcome(True, "audio muxed", format_id, streams.audio_bitrate)

    return Outcome(False, "no candidate format carries audio; the source is silent")


class AudioRepairPP(PostProcessor):
    """Verify the download and repair it before yt-dlp records the archive.

    yt-dlp writes the archive entry only after post-processing succeeds. Raising
    here therefore keeps a broken video out of the archive, and the next run
    retries it.
    """

    def __init__(self, downloader=None, max_candidates: int = MAX_CANDIDATES):
        super().__init__(downloader)
        self.max_candidates = max_candidates

    def run(self, information):
        info = information
        filepath = info.get("filepath")
        if not filepath:
            return [], info
        media_path = Path(filepath)
        if not media_path.exists():
            return [], info

        # A probe failure must abort this item. yt-dlp records the archive entry
        # only after post-processing succeeds, so raising keeps an unverified
        # file out of the archive and the next run retries it.
        try:
            streams = probe.probe(media_path)
        except probe.MediaError as error:
            raise PostProcessingError(
                f"cannot probe {media_path.name}: {error}"
            ) from error

        if streams.has_audio:
            return [], info
        if streams.video == 0:
            return [], info

        name = media_path.name
        self.to_screen(f"{name}: no audio track. The site reported one. Repairing")

        params = dict(self._downloader.params) if self._downloader else {}
        url = info.get("webpage_url") or info.get("original_url")
        if not url:
            self.report_warning(f"{name}: no source URL, cannot repair")
            return [], info

        try:
            formats = info.get("formats") or fetch_formats(params, url)
            outcome = repair_file(
                params=params,
                url=url,
                media_path=media_path,
                formats=formats,
                downloaded_format_id=info.get("format_id"),
                downloaded_vcodec=info.get("vcodec"),
                log=self.to_screen,
                max_candidates=self.max_candidates,
            )
        except probe.MediaError as error:
            raise PostProcessingError(f"cannot repair {name}: {error}") from error
        if outcome.repaired:
            rate = (
                f" at {outcome.audio_bitrate // 1000} kbps"
                if outcome.audio_bitrate
                else ""
            )
            self.to_screen(f"{name}: audio restored from {outcome.format_id}{rate}")
        else:
            # Accept a silent source, otherwise the job never terminates.
            self.report_warning(f"{name}: {outcome.reason}")
        return [], info
