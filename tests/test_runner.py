from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from vca import gallery, runner
from vca.config import parse

DOCUMENT = {
    "yt-dlp-options": {
        "sub-langs": "en.*",
        "sponsorblock-mark": "all",
        "embed-subs": None,
        "embed-thumbnail": None,
        "embed-metadata": None,
        "cookies-from-browser": "firefox",
    },
    "gallery-dl-options": {"cookies-from-browser": "firefox"},
    "collections": {
        "demo": {
            "url": "https://www.tiktok.com/@user/collection/demo-1",
            "target-dir": "/tmp/downloads",
        }
    },
}


def _collection():
    config = parse(DOCUMENT, Path("config.yaml"))
    return config, config.collection("demo")


def test_argv_pins_the_path_and_filename():
    config, collection = _collection()
    argv = runner.build_argv(config, collection)
    assert argv[0] == "--ignore-config"
    assert argv[argv.index("--paths") + 1] == f"home:{collection.target_dir}"
    assert argv[argv.index("--output") + 1] == runner.OUTPUT_TEMPLATE
    metadata_index = argv.index("--replace-in-metadata")
    assert argv[metadata_index + 1 : metadata_index + 4] == [
        "extractor",
        "^TikTok$",
        "tiktok",
    ]
    assert "--no-download-archive" in argv


def test_argv_adds_simulation_for_a_dry_run():
    config, collection = _collection()
    assert "--simulate" in runner.build_argv(config, collection, simulate=True)
    assert "--simulate" not in runner.build_argv(config, collection)


def test_options_create_the_configured_postprocessors():
    config, collection = _collection()
    options = runner.build_options(runner.build_argv(config, collection))
    keys = [postprocessor["key"] for postprocessor in options["postprocessors"]]
    assert "SponsorBlock" in keys
    assert "FFmpegEmbedSubtitle" in keys
    assert "FFmpegMetadata" in keys
    assert "EmbedThumbnail" in keys
    assert options["subtitleslangs"] == ["en.*"]
    assert options["cookiesfrombrowser"] == ("firefox", None, None, None)


def test_tiktok_filename_normalizes_the_platform_and_limits_the_title(tmp_path):
    config, collection = _collection()
    collection = replace(collection, target_dir=tmp_path)
    options = runner.build_options(runner.build_argv(config, collection))
    options["quiet"] = True
    info = {
        "title": "å" * 200,
        "id": "123",
        "ext": "mp4",
        "extractor": "TikTok",
    }
    with runner.yt_dlp.YoutubeDL(options) as downloader:
        info, _ = downloader.pre_process(info)
        filename = Path(downloader.prepare_filename(info)).name
    assert filename == f"{'å' * 90} - tiktok 123.mp4"


def test_collection_urls_prefers_webpage_urls_and_removes_duplicates(monkeypatch):
    class YoutubeDL:
        def __init__(self, options):
            assert options["extract_flat"] is True
            assert options["skip_download"] is True

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def extract_info(self, url, download):
            assert url == "collection"
            assert download is False
            return {
                "entries": [
                    {"webpage_url": "page", "url": "media"},
                    {"webpage_url": "page"},
                    {"url": "fallback"},
                ]
            }

    monkeypatch.setattr(runner.yt_dlp, "YoutubeDL", YoutubeDL)
    assert runner._collection_urls({}, "collection") == ["page", "fallback"]


def test_single_item_input_becomes_one_item(monkeypatch):
    class YoutubeDL:
        def __init__(self, _options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def extract_info(self, _url, download):
            assert download is False
            return {"webpage_url": "https://example.com/item"}

    monkeypatch.setattr(runner.yt_dlp, "YoutubeDL", YoutubeDL)
    assert runner._collection_urls({}, "input") == ["https://example.com/item"]


def test_run_filters_the_cache_and_records_each_success(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    config, collection = _collection()
    collection = replace(collection, target_dir=tmp_path / "downloads")
    cached = "https://www.tiktok.com/@user/video/1"
    photo = "https://www.tiktok.com/@user/video/2"
    video = "https://www.tiktok.com/@user/video/3"
    failed = "https://www.tiktok.com/@user/video/4"
    collection.cache_file.parent.mkdir(parents=True)
    collection.cache_file.write_text(f"{cached}\n", encoding="utf-8")

    monkeypatch.setattr(runner, "build_options", lambda _argv: {})
    monkeypatch.setattr(
        runner,
        "_collection_urls",
        lambda _options, _url: [cached, photo, video, failed],
    )
    monkeypatch.setattr(
        gallery, "resolve_source", lambda url: gallery.Source(url, "video")
    )
    inspected = []

    def run_photo(_flags, _options, url, _simulate):
        inspected.append(url)
        return SimpleNamespace(status=0, is_photo=url == photo)

    downloaded = []

    def download_video(_options, url):
        downloaded.append(url)
        return 1 if url == failed else 0

    monkeypatch.setattr(gallery, "run_photo_job", run_photo)
    monkeypatch.setattr(runner, "_download_video", download_video)

    status = runner.run_collection(
        config, collection, use_cache=True, log=lambda _message: None
    )

    assert status == 1
    assert inspected == [photo, video, failed]
    assert downloaded == [video, failed]
    assert collection.cache_file.read_text(encoding="utf-8").splitlines() == [
        cached,
        photo,
        video,
    ]


def test_dry_run_does_not_create_a_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    config, collection = _collection()
    collection = replace(collection, target_dir=tmp_path / "downloads")
    monkeypatch.setattr(runner, "build_options", lambda _argv: {})
    monkeypatch.setattr(runner, "_collection_urls", lambda _options, _url: ["item"])
    monkeypatch.setattr(runner, "_download_item", lambda *_args: 0)

    assert (
        runner.run_collection(
            config,
            collection,
            use_cache=True,
            simulate=True,
            log=lambda _message: None,
        )
        == 0
    )
    assert not collection.cache_file.exists()
    assert not collection.target_dir.exists()


def test_oneshot_ignores_an_existing_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    config, collection = _collection()
    collection = replace(collection, target_dir=tmp_path / "downloads")
    collection.cache_file.parent.mkdir(parents=True)
    collection.cache_file.write_text("item\n", encoding="utf-8")
    monkeypatch.setattr(runner, "build_options", lambda _argv: {})
    monkeypatch.setattr(runner, "_collection_urls", lambda _options, _url: ["item"])
    downloaded = []
    monkeypatch.setattr(
        runner,
        "_download_item",
        lambda *_args: downloaded.append("item") or 0,
    )

    assert (
        runner.run_collection(
            config, collection, use_cache=False, log=lambda _message: None
        )
        == 0
    )
    assert downloaded == ["item"]
    assert collection.cache_file.read_text(encoding="utf-8") == "item\n"
