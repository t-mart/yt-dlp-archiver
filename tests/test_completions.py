import yaml

from vca.cli import app
from vca.completions import carapace_spec, render_carapace


def _spec():
    return carapace_spec(app)


def _by_name(commands, name):
    return next(command for command in commands if command["name"] == name)


def test_spec_uses_the_short_cli_name():
    spec = _spec()
    assert spec["name"] == "vca"
    assert spec["description"]


def test_spec_lists_only_the_required_public_commands():
    names = {command["name"] for command in _spec()["commands"]}
    assert names == {"completions", "oneshot", "run", "systemd"}


def test_hidden_commands_are_excluded():
    assert "_complete" not in {command["name"] for command in _spec()["commands"]}


def test_value_flags_use_an_equals_suffix():
    oneshot = _by_name(_spec()["commands"], "oneshot")
    assert "--target-dir=" in oneshot["flags"]
    assert "--dry-run" in oneshot["flags"]
    assert "--dry-run=" not in oneshot["flags"]


def test_help_flag_is_present():
    run = _by_name(_spec()["commands"], "run")
    assert run["flags"]["-h"] == "Show help and exit."
    assert run["flags"]["--help"] == "Show help and exit."


def test_negative_flag_has_a_negative_description():
    systemd = _by_name(_spec()["commands"], "systemd")
    install = _by_name(systemd["commands"], "install")
    assert install["flags"]["--enable"] == "Reload and enable the timers."
    assert install["flags"]["--no-enable"] == "Do not reload and enable the timers."


def test_collection_arguments_use_dynamic_completion():
    run = _by_name(_spec()["commands"], "run")
    assert run["completion"]["positional"] == [["$(vca _complete collections)"]]
    systemd = _by_name(_spec()["commands"], "systemd")
    install = _by_name(systemd["commands"], "install")
    assert install["completion"]["positional"] == [["$(vca _complete collections)"]]


def test_path_flags_use_carapace_actions():
    run = _by_name(_spec()["commands"], "run")
    oneshot = _by_name(_spec()["commands"], "oneshot")
    assert run["completion"]["flag"]["config"] == ["$files"]
    assert oneshot["completion"]["flag"]["target-dir"] == ["$directories"]


def test_nested_subcommands_are_rendered():
    systemd = _by_name(_spec()["commands"], "systemd")
    assert {command["name"] for command in systemd["commands"]} == {
        "install",
        "status",
        "uninstall",
    }


def test_rendered_yaml_has_no_anchors():
    text = render_carapace(app)
    assert "&id" not in text
    assert "*id" not in text


def test_rendered_yaml_round_trips():
    assert yaml.safe_load(render_carapace(app)) == _spec()
