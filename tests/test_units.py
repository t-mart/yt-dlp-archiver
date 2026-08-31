from pathlib import Path

from vca import units


def test_instance_names_use_the_full_project_name():
    assert (
        units.instance_name("alpha", "service")
        == "video-collection-archiver@alpha.service"
    )
    assert (
        units.instance_name("alpha", "timer") == "video-collection-archiver@alpha.timer"
    )


def test_service_unit_runs_the_short_cli_name():
    text = units.service_unit(Path("/usr/bin/vca"))
    assert "ExecStart=/usr/bin/vca run %i" in text
    assert text.startswith(units.MARKER)
    assert text.count("%") == text.count("%i") == 2


def test_timer_template_contains_the_install_section():
    text = units.timer_unit()
    assert "WantedBy=timers.target" in text
    assert "Persistent=true" in text
    assert "OnCalendar" not in text


def test_dropin_uses_command_line_schedule_values():
    text = units.schedule_dropin("*-*-* 01:00:00", "30m")
    assert "OnCalendar=*-*-* 01:00:00" in text
    assert "RandomizedDelaySec=30m" in text


def test_install_writes_templates_and_dropins(tmp_path):
    units.install(
        ["alpha", "beta"],
        "daily",
        "30m",
        root=tmp_path,
        executable=Path("/usr/bin/vca"),
    )
    assert (tmp_path / "video-collection-archiver@.service").exists()
    assert (tmp_path / "video-collection-archiver@.timer").exists()
    assert (
        tmp_path / "video-collection-archiver@alpha.timer.d" / "schedule.conf"
    ).exists()
    beta = tmp_path / "video-collection-archiver@beta.timer.d" / "schedule.conf"
    assert "OnCalendar=daily" in beta.read_text(encoding="utf-8")


def test_install_is_idempotent(tmp_path):
    arguments = (["alpha"], "daily")
    units.install(*arguments, root=tmp_path, executable=Path("/usr/bin/vca"))
    changes = units.install(*arguments, root=tmp_path, executable=Path("/usr/bin/vca"))
    assert {change.action for change in changes} == {"unchanged"}


def test_install_updates_a_changed_schedule(tmp_path):
    units.install(["alpha"], "daily", root=tmp_path, executable=Path("/usr/bin/vca"))
    changes = units.install(
        ["alpha"], "hourly", root=tmp_path, executable=Path("/usr/bin/vca")
    )
    actions = {change.target.name: change.action for change in changes}
    assert actions["schedule.conf"] == "updated"


def test_installed_instances_reports_collection_names(tmp_path):
    units.install(["alpha"], "daily", root=tmp_path, executable=Path("/usr/bin/vca"))
    assert units.installed_instances(root=tmp_path) == ["alpha"]


def test_uninstall_removes_only_managed_files(tmp_path):
    units.install(["alpha"], "daily", root=tmp_path, executable=Path("/usr/bin/vca"))
    foreign = tmp_path / "video-collection-archiver@alpha.timer.d" / "schedule.conf"
    foreign.write_text("[Timer]\nOnCalendar=hourly\n", encoding="utf-8")
    units.uninstall(["alpha"], root=tmp_path)
    assert foreign.exists()


def test_uninstall_removes_templates_when_requested(tmp_path):
    units.install(["alpha"], "daily", root=tmp_path, executable=Path("/usr/bin/vca"))
    units.uninstall(["alpha"], root=tmp_path, drop_templates=True)
    assert not (tmp_path / "video-collection-archiver@.service").exists()
    assert not (tmp_path / "video-collection-archiver@alpha.timer.d").exists()
