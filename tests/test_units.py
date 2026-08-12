from pathlib import Path

from yt_dlp_archiver import units
from yt_dlp_archiver.config import parse

DOCUMENT = {
    "archive-jobs": {
        "alpha": {
            "url": "https://example.com/a",
            "target-dir": "/tmp/a",
            "timer-oncalendar": "*-*-* 01:00:00",
            "timer-randomized-delay": "30m",
        },
        "beta": {"url": "https://example.com/b", "target-dir": "/tmp/b"},
    }
}


def _config():
    return parse(DOCUMENT, Path("config.yaml"))


def test_instance_names_follow_the_template_convention():
    assert units.instance_name("alpha", "service") == "yt-dlp-archiver@alpha.service"
    assert units.instance_name("alpha", "timer") == "yt-dlp-archiver@alpha.timer"


def test_service_unit_holds_the_job_as_an_instance():
    text = units.service_unit(Path("/usr/bin/yt-dlp-archiver"))
    assert "ExecStart=/usr/bin/yt-dlp-archiver run --job %i" in text
    assert text.startswith(units.MARKER)
    # Job data never enters the template, so '%i' is the only specifier and no
    # value needs the '%%' escape that a literal URL would need.
    assert text.count("%") == text.count("%i") == 2


def test_timer_template_carries_the_install_section():
    text = units.timer_unit()
    assert "WantedBy=timers.target" in text
    assert "Persistent=true" in text
    # The schedule lives in the per-instance drop-in.
    assert "OnCalendar" not in text


def test_dropin_holds_the_schedule():
    job = _config().job("alpha")
    text = units.schedule_dropin(job)
    assert "OnCalendar=*-*-* 01:00:00" in text
    assert "RandomizedDelaySec=30m" in text


def test_install_writes_templates_and_dropins(tmp_path):
    jobs = list(_config().jobs.values())
    units.install(jobs, root=tmp_path, executable=Path("/usr/bin/yt-dlp-archiver"))
    assert (tmp_path / "yt-dlp-archiver@.service").exists()
    assert (tmp_path / "yt-dlp-archiver@.timer").exists()
    assert (tmp_path / "yt-dlp-archiver@alpha.timer.d" / "schedule.conf").exists()
    # beta has no timer-oncalendar, so it gets no drop-in.
    assert not (tmp_path / "yt-dlp-archiver@beta.timer.d").exists()


def test_install_is_idempotent(tmp_path):
    jobs = list(_config().jobs.values())
    units.install(jobs, root=tmp_path, executable=Path("/usr/bin/x"))
    changes = units.install(jobs, root=tmp_path, executable=Path("/usr/bin/x"))
    assert {c.action for c in changes} == {"unchanged"}


def test_install_updates_a_changed_unit(tmp_path):
    jobs = list(_config().jobs.values())
    units.install(jobs, root=tmp_path, executable=Path("/usr/bin/old"))
    changes = units.install(jobs, root=tmp_path, executable=Path("/usr/bin/new"))
    actions = {c.target.name: c.action for c in changes}
    assert actions["yt-dlp-archiver@.service"] == "updated"


def test_installed_instances_reports_job_names(tmp_path):
    units.install(list(_config().jobs.values()), root=tmp_path, executable=Path("/x"))
    assert units.installed_instances(root=tmp_path) == ["alpha"]


def test_uninstall_removes_only_managed_files(tmp_path):
    units.install(list(_config().jobs.values()), root=tmp_path, executable=Path("/x"))
    foreign = tmp_path / "yt-dlp-archiver@alpha.timer.d" / "schedule.conf"
    foreign.write_text("[Timer]\nOnCalendar=hourly\n", encoding="utf-8")
    units.uninstall(["alpha"], root=tmp_path)
    assert foreign.exists(), "a file without the marker must survive"


def test_uninstall_clears_templates_when_asked(tmp_path):
    units.install(list(_config().jobs.values()), root=tmp_path, executable=Path("/x"))
    units.uninstall(["alpha"], root=tmp_path, drop_templates=True)
    assert not (tmp_path / "yt-dlp-archiver@.service").exists()
    assert not (tmp_path / "yt-dlp-archiver@alpha.timer.d").exists()
