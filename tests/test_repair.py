"""Tests for the missing audio fix.

The fixtures are generated with ffmpeg, so they need no network access.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from yt_dlp.utils import PostProcessingError

from yt_dlp_archiver import probe
from yt_dlp_archiver.repair import (
    AudioRepairPP,
    child_params,
    mirror_key,
    repair_candidates,
)


def _make(path: Path, *streams: str) -> Path:
    args = ["ffmpeg", "-v", "error", "-y"]
    for spec in streams:
        args += ["-f", "lavfi", "-i", spec]
    args += ["-t", "1", str(path)]
    subprocess.run(args, check=True, capture_output=True)
    return path


@pytest.fixture(scope="module")
def with_audio(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("media") / "both.mp4"
    return _make(path, "testsrc=size=64x64:rate=10", "sine=frequency=440")


@pytest.fixture(scope="module")
def without_audio(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("media") / "video.mp4"
    return _make(path, "testsrc=size=64x64:rate=10")


def test_probe_detects_audio(with_audio, without_audio):
    assert probe.probe(with_audio).has_audio
    assert not probe.probe(without_audio).has_audio
    assert probe.probe(without_audio).video == 1


def test_mux_audio_restores_the_track(with_audio, without_audio, tmp_path):
    out = tmp_path / "fixed.mp4"
    probe.mux_audio(without_audio, with_audio, out)
    result = probe.probe(out)
    assert result.has_audio
    assert result.video == 1


def test_probe_rejects_a_missing_file(tmp_path):
    with pytest.raises(probe.MediaError):
        probe.probe(tmp_path / "absent.mp4")


@pytest.mark.parametrize(
    ("format_id", "expected"),
    [("bytevc1_1080p_812562-0", "bytevc1_1080p_812562"), ("download", "download")],
)
def test_mirror_key_collapses_cdn_mirrors(format_id, expected):
    assert mirror_key(format_id) == expected


# The real TikTok format list for video 7653695564026023182. Every entry claims
# acodec=aac, but only the h264 entries actually carry audio.
TIKTOK_FORMATS = [
    {"format_id": "download", "vcodec": "h264", "acodec": "aac", "tbr": None},
    {"format_id": "h264_540p_427264-0", "vcodec": "h264", "acodec": "aac", "tbr": 427},
    {"format_id": "h264_540p_427264-1", "vcodec": "h264", "acodec": "aac", "tbr": 427},
    {
        "format_id": "bytevc1_540p_463399-0",
        "vcodec": "h265",
        "acodec": "aac",
        "tbr": 463,
    },
    {
        "format_id": "h264_720p_1210205-0",
        "vcodec": "h264",
        "acodec": "aac",
        "tbr": 1210,
    },
    {
        "format_id": "h264_720p_1210205-1",
        "vcodec": "h264",
        "acodec": "aac",
        "tbr": 1210,
    },
    {
        "format_id": "bytevc1_720p_435796-0",
        "vcodec": "h265",
        "acodec": "aac",
        "tbr": 435,
    },
    {
        "format_id": "bytevc1_1080p_812562-0",
        "vcodec": "h265",
        "acodec": "aac",
        "tbr": 812,
    },
    {
        "format_id": "bytevc1_1080p_812562-1",
        "vcodec": "h265",
        "acodec": "aac",
        "tbr": 812,
    },
]


def _ranked():
    return [
        f["format_id"]
        for f in repair_candidates(TIKTOK_FORMATS, "bytevc1_1080p_812562-1", "h265")
    ]


def test_best_candidate_carries_the_best_audio():
    # h264_720p has 64 kbps audio. h264_540p and 'download' have 32 kbps.
    # Picking the cheapest download would pick the worst audio.
    assert _ranked()[0] == "h264_720p_1210205-0"


def test_candidates_prefer_the_other_codec_family():
    ranked = _ranked()
    h264 = [f for f in ranked if f.startswith(("h264", "download"))]
    h265 = [f for f in ranked if f.startswith("bytevc1")]
    assert ranked[: len(h264)] == h264, (
        "every h264 format must precede every h265 format"
    )
    assert h265, "same-family formats stay available as a fallback"


def test_candidates_exclude_the_downloaded_format_and_its_mirror():
    assert "bytevc1_1080p_812562-0" not in _ranked()
    assert "bytevc1_1080p_812562-1" not in _ranked()


def test_candidates_drop_duplicate_mirrors():
    ranked = _ranked()
    assert "h264_720p_1210205-0" in ranked
    assert "h264_720p_1210205-1" not in ranked
    assert len(ranked) == len({mirror_key(f) for f in ranked})


def test_absent_bitrate_sorts_last_in_its_tier():
    ranked = _ranked()
    assert ranked.index("download") == max(
        i for i, f in enumerate(ranked) if not f.startswith("bytevc1")
    )


def test_audio_only_formats_win():
    formats = [
        *TIKTOK_FORMATS,
        {"format_id": "audio", "vcodec": "none", "acodec": "aac", "abr": 128},
    ]
    ranked = repair_candidates(formats, "bytevc1_1080p_812562-1", "h265")
    assert ranked[0]["format_id"] == "audio"


def test_formats_without_audio_are_skipped():
    formats = [{"format_id": "v", "vcodec": "h264", "acodec": "none", "tbr": 900}]
    assert repair_candidates(formats, None, "h265") == []


def test_child_params_disable_output_and_history(tmp_path):
    parent = {
        "download_archive": "/state/job.txt",
        "writesubtitles": True,
        "writethumbnail": True,
        "postprocessors": [{"key": "EmbedThumbnail"}],
        "cookiesfrombrowser": ("firefox", None, None, None),
    }
    child = child_params(parent, "h264_720p", tmp_path)
    assert child["download_archive"] is None, (
        "a repair download must not touch the archive"
    )
    assert child["postprocessors"] == []
    assert child["writesubtitles"] is False
    assert child["writethumbnail"] is False
    assert child["format"] == "h264_720p"
    # Transport settings must survive, otherwise the repair download loses auth.
    assert child["cookiesfrombrowser"] == ("firefox", None, None, None)


def test_postprocessor_ignores_a_file_that_has_audio(with_audio):
    changed, info = AudioRepairPP().run({"filepath": str(with_audio)})
    assert changed == []
    assert info["filepath"] == str(with_audio)


def test_postprocessor_ignores_a_missing_filepath():
    assert AudioRepairPP().run({})[0] == []


def test_postprocessor_raises_when_the_file_cannot_be_probed(tmp_path):
    """A raise keeps the item out of the download archive, so it retries."""
    corrupt = tmp_path / "corrupt.mp4"
    corrupt.write_bytes(b"this is not a media file")
    with pytest.raises(PostProcessingError):
        AudioRepairPP().run({"filepath": str(corrupt)})
