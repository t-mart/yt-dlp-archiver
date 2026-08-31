from pathlib import Path

import pytest

from vca.config import ConfigError, parse, render_flags

SOURCE = Path("config.yaml")


def test_render_flags_covers_each_value_form():
    argv = render_flags(
        {
            "embed-subs": None,
            "embed-thumbnail": True,
            "embed-metadata": False,
            "sub-langs": "en.*",
            "extractor-args": ["a:1", "b:2"],
        }
    )
    assert argv == (
        "--embed-subs",
        "--embed-thumbnail",
        "--no-embed-metadata",
        "--sub-langs",
        "en.*",
        "--extractor-args",
        "a:1",
        "--extractor-args",
        "b:2",
    )


def _document(**collection):
    base = {"url": "https://example.com/collection", "target-dir": "/tmp/x"}
    return {
        "yt-dlp-options": {"embed-subs": None},
        "gallery-dl-options": {"cookies-from-browser": "firefox"},
        "collections": {"demo": {**base, **collection}},
    }


def test_parse_reads_global_options_and_a_collection():
    config = parse(_document(), SOURCE)
    collection = config.collection("demo")
    assert collection.url == "https://example.com/collection"
    assert collection.target_dir == Path("/tmp/x")
    assert config.yt_dlp_options == ("--embed-subs",)
    assert config.gallery_dl_options == ("--cookies-from-browser", "firefox")


def test_target_directory_expands_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    config = parse(_document(**{"target-dir": "~/videos"}), SOURCE)
    assert config.collection("demo").target_dir == tmp_path / "videos"


def test_cache_uses_xdg_state_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    collection = parse(_document(), SOURCE).collection("demo")
    assert collection.cache_file == (
        tmp_path / "state/video-collection-archiver/demo.txt"
    )


def test_cache_defaults_to_local_state(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    collection = parse(_document(), SOURCE).collection("demo")
    assert collection.cache_file == (
        tmp_path / ".local/state/video-collection-archiver/demo.txt"
    )


def test_unknown_collection_names_the_known_collections():
    config = parse(_document(), SOURCE)
    with pytest.raises(ConfigError, match="Known collections: demo"):
        config.collection("missing")


def test_option_profiles_are_rejected():
    document = _document()
    document["yt-dlp-options"] = {"firefox": {"embed-subs": None}}
    with pytest.raises(ConfigError, match="one global option mapping, not profiles"):
        parse(document, SOURCE)


def test_old_collection_section_is_rejected():
    with pytest.raises(ConfigError, match="use 'collections', not 'archive-jobs'"):
        parse({"archive-jobs": {}}, SOURCE)


def test_timer_values_are_rejected_in_a_collection():
    with pytest.raises(ConfigError, match="unsupported keys: 'timer-oncalendar'"):
        parse(_document(**{"timer-oncalendar": "daily"}), SOURCE)


def test_unknown_top_level_keys_are_rejected():
    document = _document()
    document["unknown"] = {}
    with pytest.raises(ConfigError, match="unsupported top-level keys: 'unknown'"):
        parse(document, SOURCE)


@pytest.mark.parametrize("name", ["has space", "slash/name", "at@sign", ""])
def test_invalid_collection_names_are_rejected(name):
    document = {"collections": {name: {"url": "url", "target-dir": "/tmp"}}}
    with pytest.raises(ConfigError):
        parse(document, SOURCE)


def test_collection_needs_a_url_and_target_directory():
    with pytest.raises(ConfigError, match="needs a nonempty 'url'"):
        parse({"collections": {"demo": {"target-dir": "/tmp"}}}, SOURCE)
    with pytest.raises(ConfigError, match="needs a 'target-dir'"):
        parse({"collections": {"demo": {"url": "url"}}}, SOURCE)


@pytest.mark.parametrize("document", [None, {}, [], "text"])
def test_invalid_documents_fail(document):
    with pytest.raises(ConfigError):
        parse(document, SOURCE)
