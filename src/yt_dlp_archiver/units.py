"""systemd user unit generation.

One template pair serves every job. The instance name is the job name, so the
URL never enters a unit file and the '%' escape problem disappears. A
per-instance drop-in carries the schedule.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import paths
from .config import Job

MARKER = "# Managed by yt-dlp-archiver. Do not edit."
PREFIX = "yt-dlp-archiver"
SERVICE_TEMPLATE = f"{PREFIX}@.service"
TIMER_TEMPLATE = f"{PREFIX}@.timer"


def service_unit(executable: Path) -> str:
    return f"""{MARKER}
[Unit]
Description=yt-dlp archive job %i
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart={executable} run --job %i
TimeoutStartSec=6h
Nice=10
IOSchedulingClass=idle
"""


def timer_unit() -> str:
    return f"""{MARKER}
[Unit]
Description=Schedule for yt-dlp archive job %i

[Timer]
Persistent=true
AccuracySec=1m

[Install]
WantedBy=timers.target
"""


def schedule_dropin(job: Job) -> str:
    lines = [MARKER, "[Timer]"]
    if job.timer_oncalendar:
        lines.append(f"OnCalendar={job.timer_oncalendar}")
    if job.timer_randomized_delay:
        lines.append(f"RandomizedDelaySec={job.timer_randomized_delay}")
    return "\n".join(lines) + "\n"


def instance_name(job_name: str, suffix: str) -> str:
    return f"{PREFIX}@{job_name}.{suffix}"


def dropin_dir(root: Path, job_name: str) -> Path:
    return root / f"{instance_name(job_name, 'timer')}.d"


def executable_path() -> Path:
    found = shutil.which(PREFIX)
    if found:
        return Path(found).resolve()
    return Path.home() / ".local" / "bin" / PREFIX


@dataclass(frozen=True)
class Change:
    action: str
    target: Path


def _write(path: Path, content: str, changes: list[Change]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == content:
        changes.append(Change("unchanged", path))
        return
    action = "updated" if path.exists() else "created"
    path.write_text(content, encoding="utf-8")
    changes.append(Change(action, path))


def _managed(path: Path) -> bool:
    try:
        return path.read_text(encoding="utf-8").startswith(MARKER)
    except OSError:
        return False


def install(
    jobs: list[Job], root: Path | None = None, executable: Path | None = None
) -> list[Change]:
    target = root or paths.systemd_user_dir()
    changes: list[Change] = []
    _write(
        target / SERVICE_TEMPLATE,
        service_unit(executable or executable_path()),
        changes,
    )
    _write(target / TIMER_TEMPLATE, timer_unit(), changes)
    for job in jobs:
        if not job.timer_oncalendar:
            continue
        _write(
            dropin_dir(target, job.name) / "schedule.conf",
            schedule_dropin(job),
            changes,
        )
    return changes


def uninstall(
    job_names: list[str], root: Path | None = None, drop_templates: bool = False
) -> list[Change]:
    target = root or paths.systemd_user_dir()
    changes: list[Change] = []
    for name in job_names:
        directory = dropin_dir(target, name)
        conf = directory / "schedule.conf"
        if conf.exists() and _managed(conf):
            conf.unlink()
            changes.append(Change("removed", conf))
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
            changes.append(Change("removed", directory))
    if drop_templates:
        for name in (SERVICE_TEMPLATE, TIMER_TEMPLATE):
            path = target / name
            if path.exists() and _managed(path):
                path.unlink()
                changes.append(Change("removed", path))
    return changes


def installed_instances(root: Path | None = None) -> list[str]:
    target = root or paths.systemd_user_dir()
    if not target.is_dir():
        return []
    prefix, suffix = f"{PREFIX}@", ".timer.d"
    return sorted(
        entry.name[len(prefix) : -len(suffix)]
        for entry in target.iterdir()
        if entry.is_dir()
        and entry.name.startswith(prefix)
        and entry.name.endswith(suffix)
    )


def systemctl(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["systemctl", "--user", *args], capture_output=True, text=True, check=check
    )
