"""Job execution and verification."""

from __future__ import annotations

import shlex
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yt_dlp

from . import gallery, probe
from .config import Config, Job
from .repair import AudioRepairPP, fetch_formats, repair_file


def build_argv(
    config: Config, job: Job, extra: Sequence[str] = (), simulate: bool = False
) -> list[str]:
    """Command line for the job. '--ignore-config' keeps the run reproducible."""
    argv = ["--ignore-config", *config.yt_dlp_argv_for(job)]
    argv += ["--paths", f"home:{job.target_dir}"]
    argv += ["--download-archive", str(job.archive_file)]
    if simulate:
        argv.append("--simulate")
    argv += list(extra)
    return argv


def build_options(argv: Sequence[str]) -> dict[str, Any]:
    """Translate the command line with yt-dlp's own parser.

    This keeps the config in yt-dlp's documented flag vocabulary and builds the
    full post-processor chain for --embed-subs, --embed-thumbnail,
    --embed-metadata and --sponsorblock-mark.
    """
    return dict(yt_dlp.parse_options(list(argv)).ydl_opts)


def command_line(config: Config, job: Job, simulate: bool = False) -> str:
    argv = build_argv(config, job, simulate=simulate)
    return " ".join(shlex.quote(part) for part in ["yt-dlp", *argv, job.url])


def gallery_command_line(config: Config, job: Job) -> str:
    return gallery.command_line(config.gallery_dl_argv_for(job), job.url)


def _prepare(job: Job) -> None:
    job.target_dir.mkdir(parents=True, exist_ok=True)
    job.archive_file.parent.mkdir(parents=True, exist_ok=True)


def run_job(
    config: Config, job: Job, simulate: bool = False, extra: Sequence[str] = ()
) -> int:
    _prepare(job)
    options = build_options(build_argv(config, job, extra=extra, simulate=simulate))
    source = gallery.resolve_source(job.url)
    if source.kind == "photo":
        return gallery.run_photo_job(
            job,
            config.gallery_dl_argv_for(job),
            options,
            source.url,
            simulate,
        )
    with yt_dlp.YoutubeDL(options) as ydl:
        ydl.add_post_processor(AudioRepairPP(), when="post_process")
        return ydl.download([source.url])


@dataclass(frozen=True)
class Finding:
    path: Path
    has_audio: bool
    repaired: bool = False
    detail: str = ""
    audio_required: bool = True

    @property
    def needs_audio(self) -> bool:
        return self.audio_required and not self.has_audio


def media_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in probe.MEDIA_SUFFIXES
    )


def verify(
    config: Config,
    job: Job,
    do_repair: bool = False,
    log: Any = lambda _: None,
) -> list[Finding]:
    """Probe every file in the target directory. Repair the silent ones in place.

    Repair never re-downloads the video. It reads the source URL from the
    embedded metadata, fetches only an audio-bearing format, then muxes.
    """
    options = build_options(build_argv(config, job))
    findings: list[Finding] = []

    for path in media_files(job.target_dir):
        streams = probe.probe(path)
        if streams.has_audio:
            findings.append(Finding(path, True))
            continue
        source_url = probe.source_url(path)
        if source_url and gallery.is_photo_url(source_url):
            findings.append(
                Finding(
                    path,
                    False,
                    detail="audio is optional for a photo slideshow",
                    audio_required=False,
                )
            )
            continue
        if not do_repair:
            findings.append(Finding(path, False, detail="no audio track"))
            continue

        url = source_url
        if not url:
            findings.append(Finding(path, False, detail="no source URL in metadata"))
            continue

        log(f"{path.name}: no audio track. Repairing from {url}")
        try:
            formats = fetch_formats(options, url)
            outcome = repair_file(
                params=options,
                url=url,
                media_path=path,
                formats=formats,
                downloaded_format_id=None,
                downloaded_vcodec=probe.video_codec(path),
                log=log,
            )
        except Exception as error:  # noqa: BLE001 - report and continue
            findings.append(Finding(path, False, detail=str(error)))
            continue
        findings.append(
            Finding(path, outcome.repaired, outcome.repaired, outcome.reason)
        )

    return findings


def jobs_for(config: Config, names: Iterable[str] | None, every: bool) -> list[Job]:
    if every:
        return list(config.jobs.values())
    return [config.job(name) for name in (names or ())]
