from __future__ import annotations

import json
import subprocess
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from vca import gallery, probe, runner
from vca.config import parse


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
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "anullsrc=sample_rate=48000:channel_layout=stereo:d=0.2",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000:duration=0.6",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=sample_rate=48000:channel_layout=stereo:d=0.2",
        "-filter_complex",
        "[1:a]aformat=channel_layouts=stereo[tone];[0:a][tone][2:a]concat=n=3:v=0:a=1",
        str(audio),
    )
    return [first, second], audio


def _metadata() -> dict[str, str]:
    return {
        "id": "123456789",
        "user": "someone",
        "desc": "A title #one #two",
    }


def _stream_duration(path: Path, stream: int) -> float:
    details = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            f"a:{stream}",
            "-show_packets",
            "-show_entries",
            "packet=pts_time,duration_time",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    packets = json.loads(details.stdout)["packets"]
    return max(
        float(packet["pts_time"]) + float(packet["duration_time"]) for packet in packets
    )


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


def test_collector_selects_only_photo_posts():
    class Base:
        def __init__(self, _url, _parent=None):
            self.pred_post = lambda *_: True

        def _init(self):
            return None

        def handle_directory(self, _metadata):
            return None

    download = gallery._collector(Base)("unused")
    download._init()

    assert download.pred_post("", {"id": "123456789", "post_type": "image"})
    assert not download.pred_post("", {"id": "2", "post_type": "video"})
    assert download.is_photo


def test_mux_creates_a_standard_slideshow_with_original_media(
    slideshow_sources, tmp_path
):
    images, audio = slideshow_sources
    destination = tmp_path / "result.mkv"
    source_url = "https://www.tiktok.com/@someone/photo/123456789"
    gallery.mux_slideshow(images, audio, destination, _metadata(), source_url)

    streams = probe.probe(destination)
    assert streams.video == 1
    assert streams.audio == 2

    details = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-count_packets",
            "-show_streams",
            "-show_chapters",
            "-show_format",
            "-of",
            "json",
            str(destination),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(details.stdout)
    video = next(
        stream for stream in data["streams"] if stream["codec_type"] == "video"
    )
    audio_streams = [
        stream for stream in data["streams"] if stream["codec_type"] == "audio"
    ]
    playback_audio, original_audio = audio_streams
    attached_images = [
        stream
        for stream in data["streams"]
        if stream.get("disposition", {}).get("attached_pic")
    ]
    attachments = [
        stream for stream in data["streams"] if stream["codec_type"] == "attachment"
    ]

    assert video["codec_name"] == "h264"
    assert video["avg_frame_rate"] == "30/1"
    assert int(video["nb_read_packets"]) == 300
    assert playback_audio["codec_name"] == "aac"
    assert playback_audio["disposition"]["default"] == 1
    assert playback_audio["tags"]["title"] == "Slideshow audio (looped)"
    assert original_audio["codec_name"] == "mp3"
    assert original_audio["disposition"]["default"] == 0
    assert original_audio["tags"]["title"] == "Original audio"
    assert [stream["tags"]["filename"] for stream in attached_images] == [
        "01.jpg",
        "02.jpg",
    ]
    assert [stream["tags"]["filename"] for stream in attachments] == [
        "00.mp3",
    ]
    assert [stream["tags"]["mimetype"] for stream in attached_images] == [
        "image/jpeg",
        "image/jpeg",
    ]
    assert [stream["tags"]["mimetype"] for stream in attachments] == [
        "audio/mpeg",
    ]

    keyframes = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-skip_frame",
            "nokey",
            "-show_frames",
            "-show_entries",
            "frame=best_effort_timestamp_time",
            "-of",
            "json",
            str(destination),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    keyframe_times = [
        float(frame["best_effort_timestamp_time"])
        for frame in json.loads(keyframes.stdout)["frames"]
    ]
    assert keyframe_times == pytest.approx([0.0, 5.0], abs=0.02)

    assert len(data["chapters"]) == 2
    assert data["format"]["tags"]["COMMENT"] == gallery.SLIDESHOW_COMMENT
    assert data["format"]["tags"]["SOURCE_URL"] == source_url
    assert data["format"]["tags"]["MEDIA_TYPE"] == "tiktok-photo"

    for index, original in enumerate(images, start=1):
        extracted = tmp_path / f"attachment-{index}{original.suffix}"
        _ffmpeg(
            "-i",
            str(destination),
            "-map",
            f"0:v:{index}",
            "-frames:v",
            "1",
            "-c",
            "copy",
            str(extracted),
        )
        assert extracted.read_bytes() == original.read_bytes()

    extracted_audio = tmp_path / "attachment.mp3"
    _ffmpeg(
        "-dump_attachment:t:0",
        str(extracted_audio),
        "-i",
        str(destination),
        "-map",
        "0:v:0",
        "-f",
        "null",
        "-",
    )
    assert extracted_audio.read_bytes() == audio.read_bytes()

    silence = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "info",
            "-i",
            str(destination),
            "-map",
            "0:a:0",
            "-af",
            "silencedetect=noise=-45dB:d=0.05",
            "-f",
            "null",
            "-",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "silence_duration" not in silence.stderr


def test_mux_keeps_audio_that_is_longer_than_the_slideshow(slideshow_sources, tmp_path):
    images, _ = slideshow_sources
    audio = tmp_path / "long.mp3"
    destination = tmp_path / "long.mkv"
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000:duration=12",
        str(audio),
    )

    gallery.mux_slideshow(
        images,
        audio,
        destination,
        _metadata(),
        "https://www.tiktok.com/@someone/photo/123456789",
    )

    assert _stream_duration(destination, 0) == pytest.approx(10, abs=0.1)
    assert _stream_duration(destination, 1) == pytest.approx(12, abs=0.1)


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
        "outtmpl": {"default": runner.OUTPUT_TEMPLATE},
        "quiet": True,
    }
    destination = gallery._destination(
        options,
        _metadata(),
        "https://www.tiktok.com/@someone/photo/123456789",
    )
    assert destination == tmp_path / "A title #one #two - tiktok 123456789.mkv"


def test_photo_job_creates_a_complete_mux(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    config = parse(
        {
            "collections": {
                "demo": {
                    "url": "https://www.tiktok.com/@someone/video/123456789",
                    "target-dir": str(tmp_path),
                }
            }
        },
        Path("config.yaml"),
    )
    collection = config.collection("demo")
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

    result = gallery.run_photo_job((), {}, collection.url)

    assert result.status == 0
    assert result.is_photo
    assert destination.exists()
    assert not collection.cache_file.exists()
    assert any(path == () and key == "base-directory" for path, key, _ in applied)
    assert (("extractor", "tiktok"), "videos", False) in applied
