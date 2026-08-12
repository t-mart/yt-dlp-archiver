"""Command line interface."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from . import completions as completions_module
from . import config as config_module
from . import paths, runner, units
from .config import Config, ConfigError, Job

app = typer.Typer(
    help="Archive remote video sources on a schedule, with a guaranteed audio track.",
    no_args_is_help=True,
    add_completion=False,
)
systemd_app = typer.Typer(
    help="Generate and manage systemd user units.", no_args_is_help=True
)
app.add_typer(systemd_app, name="systemd")
completions_app = typer.Typer(
    help="Generate shell completion definitions.", no_args_is_help=True
)
app.add_typer(completions_app, name="completions")

ConfigOption = Annotated[
    Path | None,
    typer.Option("--config", help="Path to config.yaml.", show_default=False),
]
JobOption = Annotated[
    str | None,
    typer.Option("--job", help="Job name from the config.", show_default=False),
]


def _echo(message: str) -> None:
    typer.echo(message)


def _fail(message: str) -> typer.Exit:
    typer.secho(f"error: {message}", fg=typer.colors.RED, err=True)
    return typer.Exit(code=2)


def _load(path: Path | None) -> Config:
    try:
        return config_module.load(path)
    except ConfigError as error:
        raise _fail(str(error)) from None


def _select(cfg: Config, job: str | None, every: bool) -> list[Job]:
    if every and job:
        raise _fail("use --job or --all, not both")
    if not every and not job:
        raise _fail("give --job <name> or --all")
    try:
        return runner.jobs_for(cfg, [job] if job else None, every)
    except ConfigError as error:
        raise _fail(str(error)) from None


@app.command()
def run(
    config: ConfigOption = None,
    job: JobOption = None,
    all_jobs: Annotated[bool, typer.Option("--all", help="Run every job.")] = False,
    url: Annotated[str | None, typer.Option("--url", help="Ad-hoc source URL.")] = None,
    target_dir: Annotated[
        Path | None, typer.Option("--target-dir", help="Ad-hoc download directory.")
    ] = None,
    options: Annotated[
        str | None, typer.Option("--options", help="Option set name for an ad-hoc run.")
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Simulate. Download nothing.")
    ] = False,
) -> None:
    """Download new items for one job, every job, or an ad-hoc URL."""
    if url:
        if not target_dir:
            raise _fail("--url needs --target-dir")
        cfg = (
            _load(config)
            if config or paths.config_file().exists()
            else Config({}, {}, Path("-"))
        )
        jobs = [config_module.ad_hoc_job(url, target_dir, [options] if options else [])]
    else:
        cfg = _load(config)
        jobs = _select(cfg, job, all_jobs)

    failures = 0
    for item in jobs:
        _echo(f"==> {item.name}")
        try:
            code = runner.run_job(cfg, item, simulate=dry_run)
        except ConfigError as error:
            raise _fail(str(error)) from None
        if code:
            failures += 1
            typer.secho(
                f"{item.name}: finished with errors", fg=typer.colors.RED, err=True
            )
    if failures:
        raise typer.Exit(code=1)


@app.command()
def verify(
    config: ConfigOption = None,
    job: JobOption = None,
    all_jobs: Annotated[bool, typer.Option("--all", help="Verify every job.")] = False,
    repair: Annotated[
        bool, typer.Option("--repair", help="Mux audio into files that have none.")
    ] = False,
) -> None:
    """Probe archived files. Report or repair a missing audio track."""
    cfg = _load(config)
    broken = 0
    for item in _select(cfg, job, all_jobs):
        _echo(f"==> {item.name} ({item.target_dir})")
        try:
            findings = runner.verify(cfg, item, do_repair=repair, log=_echo)
        except ConfigError as error:
            raise _fail(str(error)) from None
        silent = [f for f in findings if not f.has_audio]
        fixed = [f for f in findings if f.repaired]
        for finding in silent:
            typer.secho(
                f"  no audio: {finding.path.name} ({finding.detail})",
                fg=typer.colors.YELLOW,
            )
        broken += len(silent)
        _echo(
            f"  {len(findings)} files, {len(silent)} without audio, {len(fixed)} repaired"
        )
    # 'broken' counts the files that still lack audio after any repair.
    if broken:
        raise typer.Exit(code=1)


@app.command("list")
def list_jobs(config: ConfigOption = None) -> None:
    """List the configured jobs."""
    cfg = _load(config)
    if not cfg.jobs:
        _echo("no jobs configured")
        return
    for item in cfg.jobs.values():
        schedule = item.timer_oncalendar or "no timer"
        _echo(
            f"{item.name}\n  url      {item.url}\n  target   {item.target_dir}\n  schedule {schedule}"
        )


@app.command()
def show(
    config: ConfigOption = None,
    job: JobOption = None,
) -> None:
    """Show the resolved settings and the equivalent yt-dlp command."""
    cfg = _load(config)
    if not job:
        raise _fail("give --job <name>")
    try:
        item = cfg.job(job)
    except ConfigError as error:
        raise _fail(str(error)) from None
    _echo(f"job        {item.name}")
    _echo(f"url        {item.url}")
    _echo(f"target-dir {item.target_dir}")
    _echo(f"archive    {item.archive_file}")
    _echo(f"options    {', '.join(item.options) or 'none'}")
    _echo(f"schedule   {item.timer_oncalendar or 'no timer'}")
    _echo(f"service    {units.instance_name(item.name, 'service')}")
    _echo("")
    _echo(runner.command_line(cfg, item))


@completions_app.command("carapace")
def completions_carapace() -> None:
    """Print a carapace spec. carapace serves nushell, bash, zsh, fish and more."""
    typer.echo(completions_module.render_carapace(app), nl=False)


@app.command("_complete", hidden=True)
def complete_values(
    what: Annotated[str, typer.Argument(help="Candidate set: jobs or option-sets.")],
    config: ConfigOption = None,
) -> None:
    """Print completion candidates as 'value<TAB>description' lines."""
    # A completer must never fail loudly. Print nothing when the config is bad.
    try:
        cfg = config_module.load(config)
    except ConfigError, OSError:
        return
    if what == "jobs":
        for item in cfg.jobs.values():
            typer.echo(f"{item.name}\t{item.target_dir}")
    elif what == "option-sets":
        for name in cfg.option_sets:
            typer.echo(name)


@systemd_app.command("install")
def systemd_install(
    config: ConfigOption = None,
    job: JobOption = None,
    all_jobs: Annotated[bool, typer.Option("--all", help="Install every job.")] = False,
    prune: Annotated[
        bool,
        typer.Option("--prune", help="Remove installed jobs that left the config."),
    ] = False,
    enable: Annotated[
        bool,
        typer.Option(
            "--enable/--no-enable", help="Reload systemd and start the timers."
        ),
    ] = True,
) -> None:
    """Write the unit templates and the per-job schedule, then enable the timers."""
    cfg = _load(config)
    jobs = _select(cfg, job, all_jobs)
    for change in units.install(jobs):
        _echo(f"{change.action:<10} {change.target}")

    if prune:
        orphans = [name for name in units.installed_instances() if name not in cfg.jobs]
        for change in units.uninstall(orphans):
            _echo(f"{change.action:<10} {change.target}")
        for name in orphans:
            units.systemctl("disable", "--now", units.instance_name(name, "timer"))

    if not enable:
        _echo("skipped: systemctl daemon-reload and enable")
        return
    units.systemctl("daemon-reload")
    for item in jobs:
        if not item.timer_oncalendar:
            typer.secho(
                f"{item.name}: no timer-oncalendar, timer not enabled",
                fg=typer.colors.YELLOW,
            )
            continue
        timer = units.instance_name(item.name, "timer")
        result = units.systemctl("enable", "--now", timer)
        if result.returncode:
            typer.secho(
                f"{timer}: {result.stderr.strip()}", fg=typer.colors.RED, err=True
            )
        else:
            _echo(f"enabled    {timer}")


@systemd_app.command("uninstall")
def systemd_uninstall(
    config: ConfigOption = None,
    job: JobOption = None,
    all_jobs: Annotated[
        bool, typer.Option("--all", help="Uninstall every job.")
    ] = False,
    enable: Annotated[
        bool, typer.Option("--enable/--no-enable", help="Call systemctl.")
    ] = True,
) -> None:
    """Stop the timers and remove the generated units."""
    cfg = _load(config)
    names = [item.name for item in _select(cfg, job, all_jobs)]
    if enable:
        for name in names:
            units.systemctl("disable", "--now", units.instance_name(name, "timer"))
    remaining = [n for n in units.installed_instances() if n not in names]
    for change in units.uninstall(names, drop_templates=not remaining):
        _echo(f"{change.action:<10} {change.target}")
    if enable:
        units.systemctl("daemon-reload")


@systemd_app.command("status")
def systemd_status(config: ConfigOption = None) -> None:
    """Show the timer state for every installed job."""
    installed = units.installed_instances()
    if not installed:
        _echo("no units installed")
        return
    result = units.systemctl(
        "list-timers", "--all", "--no-pager", f"{units.PREFIX}@*.timer"
    )
    _echo(result.stdout.strip() or result.stderr.strip())


def main() -> None:
    app()
