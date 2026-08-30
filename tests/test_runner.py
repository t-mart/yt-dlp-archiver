from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from yt_dlp_archiver import runner
from yt_dlp_archiver.config import parse

DOCUMENT = {
    "yt-dlp-options": {
        "firefox": {
            "sub-langs": "en.*",
            "sponsorblock-mark": "all",
            "embed-subs": None,
            "embed-thumbnail": None,
            "embed-metadata": None,
            "cookies-from-browser": "firefox",
        }
    },
    "gallery-dl-options": {
        "firefox": {"cookies-from-browser": "firefox"},
    },
    "archive-jobs": {
        "demo": {
            "url": "https://example.com/v",
            "target-dir": "/tmp/dl",
            "yt-dlp-options": "firefox",
            "gallery-dl-options": "firefox",
        }
    },
}


def _job():
    config = parse(DOCUMENT, Path("config.yaml"))
    return config, config.job("demo")


def test_argv_pins_the_paths_and_archive(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    config, job = _job()
    argv = runner.build_argv(config, job)
    assert argv[0] == "--ignore-config", "the host yt-dlp config must not leak in"
    assert "--paths" in argv and f"home:{job.target_dir}" in argv
    archive = argv[argv.index("--download-archive") + 1]
    assert archive.endswith("yt-dlp-archiver/demo.txt")


def test_argv_adds_simulate_for_a_dry_run():
    config, job = _job()
    assert "--simulate" in runner.build_argv(config, job, simulate=True)
    assert "--simulate" not in runner.build_argv(config, job)


def test_options_translate_to_the_expected_postprocessors():
    """parse_options is not a documented API, so pin the behaviour we rely on."""
    config, job = _job()
    options = runner.build_options(runner.build_argv(config, job))
    keys = [pp["key"] for pp in options["postprocessors"]]
    assert "SponsorBlock" in keys
    assert "FFmpegEmbedSubtitle" in keys
    assert "FFmpegMetadata" in keys
    assert "EmbedThumbnail" in keys
    assert options["subtitleslangs"] == ["en.*"]
    assert options["writesubtitles"] is True
    assert options["writethumbnail"] is True
    assert options["cookiesfrombrowser"] == ("firefox", None, None, None)


def test_command_line_is_shell_quoted():
    config, job = _job()
    line = runner.command_line(config, job)
    assert line.startswith("yt-dlp ")
    assert "'en.*'" in line, "a glob must be quoted so the shell does not expand it"
    assert line.endswith(job.url)


def test_gallery_command_line_uses_gallery_options():
    config, job = _job()
    line = runner.gallery_command_line(config, job)
    assert line.startswith("gallery-dl --config-ignore ")
    assert "--cookies-from-browser firefox" in line
    assert line.endswith(job.url)


def test_mixed_tiktok_collection_routes_each_entry(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    collection = "https://www.tiktok.com/@someone/collection/saved-123"
    photo = "https://www.tiktok.com/@someone/video/111"
    video = "https://www.tiktok.com/@someone/video/222"
    config = parse(
        {"archive-jobs": {"mixed": {"url": collection, "target-dir": str(tmp_path)}}},
        Path("config.yaml"),
    )
    downloads = []

    class YoutubeDL:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def add_post_processor(self, *_args, **_kwargs):
            return None

        def extract_info(self, url, download):
            assert url == collection
            assert download is False
            assert self.options["download_archive"] is None
            assert self.options["extract_flat"] is True
            return {"entries": [{"url": photo}, {"url": video}]}

        def download(self, urls):
            downloads.extend(urls)
            return 0

    monkeypatch.setattr(runner, "build_options", lambda _: {})
    monkeypatch.setattr(runner.yt_dlp, "YoutubeDL", YoutubeDL)
    gallery_urls = []

    def run_photo(_job, _flags, _options, url, _simulate):
        gallery_urls.append(url)
        return SimpleNamespace(status=0, is_photo=url == photo)

    monkeypatch.setattr(runner.gallery, "run_photo_job", run_photo)

    assert runner.run_job(config, config.job("mixed")) == 0
    assert gallery_urls == [photo, video]
    assert downloads == [video]


def test_media_files_filters_by_suffix(tmp_path):
    (tmp_path / "a.mp4").touch()
    (tmp_path / "b.mkv").touch()
    (tmp_path / "c.vtt").touch()
    (tmp_path / "d.png").touch()
    assert [p.name for p in runner.media_files(tmp_path)] == ["a.mp4", "b.mkv"]


def test_media_files_tolerates_a_missing_directory(tmp_path):
    assert runner.media_files(tmp_path / "absent") == []


def test_verify_accepts_a_silent_photo_post(monkeypatch, tmp_path):
    config, job = _job()
    job = replace(job, target_dir=tmp_path)
    slideshow = tmp_path / "photo.mkv"
    slideshow.touch()
    monkeypatch.setattr(
        runner.probe, "probe", lambda _: runner.probe.Streams(0, 1, None)
    )
    monkeypatch.setattr(
        runner.probe,
        "source_url",
        lambda _: "https://www.tiktok.com/@someone/photo/123456789",
    )

    findings = runner.verify(config, job)

    assert len(findings) == 1
    assert not findings[0].needs_audio


def test_jobs_for_all_returns_every_job():
    config, _ = _job()
    assert [j.name for j in runner.jobs_for(config, None, every=True)] == ["demo"]
