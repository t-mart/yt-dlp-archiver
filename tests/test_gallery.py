from __future__ import annotations

import json
import subprocess
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from yt_dlp_archiver import gallery, probe, runner
from yt_dlp_archiver.config import parse


def _ffmpeg(*args: str) -> None:
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", *args],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def slideshow_sources(tmp_path: Path) -> tuple[list[Path], Path]:
    first = tmp_path / "01.jpg"
    second = tmp_path / "02.jpg"
    audio = tmp_path / "00.mp3"
    _ffmpeg("-f", "lavfi", "-i", "color=red:size=64x80", "-frames:v", "1", str(first))
    _ffmpeg("-f", "lavfi", "-i", "color=blue:size=64x82", "-frames:v", "1", str(second))
    _ffmpeg("-f", "lavfi", "-i", "sine=frequency=440", "-t", "1", str(audio))
    return [first, second], audio


def _metadata() -> dict[str, str]:
    return {
        "id": "123456789",
        "user": "someone",
        "desc": "A title #one #two",
    }


def test_explicit_photo_url_needs_no_request():
    def fail(_: str) -> str:
        raise AssertionError("the resolver must not run")

    url = "https://www.tiktok.com/@someone/photo/123456789"
    assert gallery.resolve_source(url, resolver=fail) == gallery.Source(url, "photo")


def test_short_url_uses_its_redirect_target():
    short = "https://www.tiktok.com/t/short/"
    photo = "https://www.tiktok.com/@someone/photo/123456789?_r=1"
    assert gallery.resolve_source(short, resolver=lambda _: photo) == gallery.Source(
        photo, "photo"
    )


def test_video_and_unrelated_urls_stay_with_yt_dlp():
    video = "https://www.tiktok.com/@someone/video/123456789"
    assert gallery.resolve_source(video).kind == "video"
    collection = "https://www.tiktok.com/@someone/collection/saved-123456789"
    assert gallery.resolve_source(collection).kind == "collection"
    assert gallery.resolve_source("https://example.com/watch/1").kind == "other"


def test_browser_cookie_option_matches_gallery_dl_tuple():
    assert gallery._cookies("firefox") == ("firefox", "", "", "", "")
    assert gallery._cookies("firefox/.tiktok.com:work::Personal") == (
        "firefox",
        "work",
        "",
        "Personal",
        ".tiktok.com",
    )


def test_archived_photo_still_matches_gallery_dl():
    class Base:
        def __init__(self, _url, _parent=None):
            self.pred_post = lambda *_: True

        def _init(self):
            return None

        def handle_directory(self, _metadata):
            return None

    download = gallery._collector(Base, {"123456789"})("unused")
    download._init()

    assert not download.pred_post("", {"id": "123456789", "post_type": "image"})
    assert download.is_photo


def test_mux_keeps_one_jpeg_packet_per_image(slideshow_sources, tmp_path):
    images, audio = slideshow_sources
    destination = tmp_path / "result.mkv"
    source_url = "https://www.tiktok.com/@someone/photo/123456789"
    gallery.mux_slideshow(images, audio, destination, _metadata(), source_url)

    streams = probe.probe(destination)
    assert streams.video == 1
    assert streams.has_audio

    packets = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "packet=duration_time,size:stream=avg_frame_rate",
            "-of",
            "json",
            str(destination),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    video = json.loads(packets.stdout)
    video_packets = video["packets"]
    sizes = [int(packet["size"]) for packet in video_packets]
    assert sizes == [path.stat().st_size for path in images]
    assert [float(packet["duration_time"]) for packet in video_packets] == [5.0, 5.0]
    assert video["streams"][0]["avg_frame_rate"] == "1/5"

    details = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_chapters",
            "-show_entries",
            "format=duration:format_tags=comment,media_type",
            "-of",
            "json",
            str(destination),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(details.stdout)
    assert len(data["chapters"]) == 2
    assert data["format"]["tags"]["COMMENT"] == source_url
    assert data["format"]["tags"]["MEDIA_TYPE"] == "tiktok-photo"


def test_mux_accepts_a_photo_post_without_audio(slideshow_sources, tmp_path):
    images, _ = slideshow_sources
    destination = tmp_path / "silent.mkv"
    gallery.mux_slideshow(
        images,
        None,
        destination,
        _metadata(),
        "https://www.tiktok.com/@someone/photo/123456789",
    )
    streams = probe.probe(destination)
    assert streams.video == 1
    assert not streams.has_audio
    duration = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(destination),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert float(duration.stdout) == pytest.approx(10, abs=0.1)


def test_photo_filename_uses_the_yt_dlp_template(tmp_path):
    options = {
        "paths": {"home": str(tmp_path)},
        "outtmpl": {"default": "%(title)s [%(id)s].%(ext)s"},
        "quiet": True,
    }
    destination = gallery._destination(
        options,
        _metadata(),
        "https://www.tiktok.com/@someone/photo/123456789",
    )
    assert destination == tmp_path / "A title #one #two [123456789].mkv"


def test_runner_routes_a_photo_to_gallery_dl(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    document = {
        "gallery-dl-options": {"firefox": {"cookies-from-browser": "firefox"}},
        "archive-jobs": {
            "demo": {
                "url": "https://www.tiktok.com/t/short/",
                "target-dir": str(tmp_path),
                "gallery-dl-options": "firefox",
            }
        },
    }
    config = parse(document, Path("config.yaml"))
    job = replace(config.job("demo"), name="photo-test")
    resolved = "https://www.tiktok.com/@someone/photo/123456789"
    monkeypatch.setattr(
        gallery, "resolve_source", lambda _: gallery.Source(resolved, "photo")
    )
    called = {}

    def run_photo(*args):
        called["args"] = args
        return SimpleNamespace(status=7, is_photo=True)

    monkeypatch.setattr(gallery, "run_photo_job", run_photo)
    assert runner.run_job(config, job) == 7
    assert called["args"][3] == resolved
    assert called["args"][1] == ("--cookies-from-browser", "firefox")


def test_photo_job_records_only_a_complete_mux(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    config = parse(
        {
            "archive-jobs": {
                "demo": {
                    "url": "https://www.tiktok.com/@someone/video/123456789",
                    "target-dir": str(tmp_path),
                }
            }
        },
        Path("config.yaml"),
    )
    job = config.job("demo")
    metadata = {
        **_metadata(),
        "post_type": "image",
        "imagePost": {"images": [{}, {}]},
    }
    applied = []

    class Download:
        def __init__(self, url, parent=None):
            self.url = url
            self.pred_post = lambda *_: True

        def _init(self):
            return None

        def handle_directory(self, _metadata):
            return None

        def run(self):
            self._init()
            if self.pred_post("", metadata):
                self.handle_directory(metadata)
            return 0

    fake_config = SimpleNamespace(
        apply=lambda settings: (applied.extend(settings), nullcontext())[1]
    )
    fake_job = SimpleNamespace(DownloadJob=Download, SimulationJob=Download)
    monkeypatch.setattr(gallery, "gallery_config", fake_config)
    monkeypatch.setattr(gallery, "gallery_job", fake_job)
    monkeypatch.setattr(gallery, "gallery_option", SimpleNamespace())
    monkeypatch.setattr(gallery, "_gallery_settings", lambda *_: [])
    images = [tmp_path / "01.jpg", tmp_path / "02.jpg"]
    monkeypatch.setattr(gallery, "_post_files", lambda _: (images, None))
    destination = tmp_path / "A title [123456789].mkv"
    monkeypatch.setattr(gallery, "_destination", lambda *_: destination)
    monkeypatch.setattr(
        gallery,
        "mux_slideshow",
        lambda *_: destination.touch(),
    )

    result = gallery.run_photo_job(job, (), {}, job.url)

    assert result.status == 0
    assert result.is_photo
    assert destination.exists()
    assert job.gallery_archive_file.read_text() == "123456789\n"
    assert any(path == () and key == "base-directory" for path, key, _ in applied)
    assert (("extractor", "tiktok"), "videos", False) in applied
