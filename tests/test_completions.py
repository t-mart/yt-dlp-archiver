import yaml

from yt_dlp_archiver.cli import app
from yt_dlp_archiver.completions import carapace_spec, render_carapace


def _spec():
    return carapace_spec(app)


def _by_name(commands, name):
    return next(c for c in commands if c["name"] == name)


def test_spec_names_the_program():
    spec = _spec()
    assert spec["name"] == "yt-dlp-archiver"
    assert spec["description"]


def test_spec_lists_the_public_commands():
    names = {c["name"] for c in _spec()["commands"]}
    assert names == {"completions", "list", "run", "show", "systemd", "verify"}


def test_hidden_commands_are_excluded():
    """The candidate provider is an implementation detail, not a user command."""
    assert "_complete" not in {c["name"] for c in _spec()["commands"]}


def test_value_flags_take_an_equals_suffix():
    run = _by_name(_spec()["commands"], "run")
    assert "--job=" in run["flags"]
    assert "--url=" in run["flags"]
    # A boolean flag must not take a value.
    assert "--all" in run["flags"]
    assert "--all=" not in run["flags"]


def test_help_flag_is_present():
    run = _by_name(_spec()["commands"], "run")
    assert run["flags"]["--help"] == "Show help and exit."


def test_negative_flag_gets_a_negated_description():
    install = _by_name(_by_name(_spec()["commands"], "systemd")["commands"], "install")
    assert install["flags"]["--enable"] == "Reload systemd and start the timers."
    assert (
        install["flags"]["--no-enable"] == "Do not reload systemd and start the timers."
    )


def test_job_flag_completes_from_the_config():
    run = _by_name(_spec()["commands"], "run")
    assert run["completion"]["flag"]["job"] == ["$(yt-dlp-archiver _complete jobs)"]
    assert run["completion"]["flag"]["options"] == [
        "$(yt-dlp-archiver _complete option-sets)"
    ]


def test_path_flags_use_carapace_builtins():
    run = _by_name(_spec()["commands"], "run")
    assert run["completion"]["flag"]["config"] == ["$files"]
    assert run["completion"]["flag"]["target-dir"] == ["$directories"]


def test_nested_subcommands_are_rendered():
    systemd = _by_name(_spec()["commands"], "systemd")
    assert {c["name"] for c in systemd["commands"]} == {
        "install",
        "uninstall",
        "status",
    }
    uninstall = _by_name(systemd["commands"], "uninstall")
    assert uninstall["completion"]["flag"]["job"] == [
        "$(yt-dlp-archiver _complete jobs)"
    ]


def test_rendered_yaml_has_no_anchors():
    """carapace reads the file directly, so keep it plain and readable."""
    text = render_carapace(app)
    assert "&id" not in text
    assert "*id" not in text


def test_rendered_yaml_round_trips():
    assert yaml.safe_load(render_carapace(app)) == _spec()
