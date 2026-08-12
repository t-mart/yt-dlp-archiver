from pathlib import Path

import pytest

from yt_dlp_archiver.config import ConfigError, parse, render_flags

SOURCE = Path("config.yaml")


def test_render_flags_covers_every_value_form():
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


def test_render_flags_keeps_declaration_order():
    assert render_flags({"b": None, "a": None}) == ("--b", "--a")


def _document(**job):
    base = {"url": "https://example.com/v", "target-dir": "/tmp/x"}
    return {
        "yt-dlp-options": {"set-a": {"embed-subs": None}},
        "archive-jobs": {"j": {**base, **job}},
    }


def test_parse_reads_a_job():
    config = parse(_document(options="set-a", **{"timer-oncalendar": "daily"}), SOURCE)
    job = config.job("j")
    assert job.url == "https://example.com/v"
    assert job.target_dir == Path("/tmp/x")
    assert job.options == ("set-a",)
    assert job.timer_oncalendar == "daily"


def test_options_accepts_a_list():
    config = parse(_document(options=["set-a", "set-a"]), SOURCE)
    assert config.argv_for(config.job("j")) == ("--embed-subs", "--embed-subs")


def test_options_may_be_absent():
    config = parse(_document(), SOURCE)
    assert config.argv_for(config.job("j")) == ()


def test_target_dir_expands_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    config = parse(_document(**{"target-dir": "~/videos"}), SOURCE)
    assert config.job("j").target_dir == tmp_path / "videos"


def test_unknown_job_names_the_known_ones():
    config = parse(_document(), SOURCE)
    with pytest.raises(ConfigError, match="Known jobs: j"):
        config.job("nope")


def test_unknown_option_set_is_reported():
    config = parse(_document(options="missing"), SOURCE)
    with pytest.raises(ConfigError, match="Known sets: set-a"):
        config.argv_for(config.job("j"))


@pytest.mark.parametrize("name", ["has space", "slash/name", "at@sign", ""])
def test_invalid_job_names_are_rejected(name):
    document = {"archive-jobs": {name: {"url": "u", "target-dir": "/tmp"}}}
    with pytest.raises(ConfigError):
        parse(document, SOURCE)


def test_job_needs_url_and_target_dir():
    with pytest.raises(ConfigError, match="needs a 'url'"):
        parse({"archive-jobs": {"j": {"target-dir": "/tmp"}}}, SOURCE)
    with pytest.raises(ConfigError, match="needs a 'target-dir'"):
        parse({"archive-jobs": {"j": {"url": "u"}}}, SOURCE)


def test_empty_document_is_valid():
    config = parse(None, SOURCE)
    assert config.jobs == {}
