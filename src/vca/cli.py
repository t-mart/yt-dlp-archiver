"""Command-line interface for video-collection-archiver."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Annotated

import typer

from . import completions as completions_module
from . import config as config_module
from . import runner, units
from .config import Collection, Config, ConfigError

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

app = typer.Typer(
    help="Archive video collections with yt-dlp and gallery-dl.",
    no_args_is_help=True,
    add_completion=False,
    context_settings=CONTEXT_SETTINGS,
)
systemd_app = typer.Typer(
    help="Manage systemd user units.",
    no_args_is_help=True,
    context_settings=CONTEXT_SETTINGS,
)
app.add_typer(systemd_app, name="systemd")
completions_app = typer.Typer(
    help="Generate shell completion definitions.",
    no_args_is_help=True,
    context_settings=CONTEXT_SETTINGS,
)
app.add_typer(completions_app, name="completions")

ConfigOption = Annotated[
    Path | None,
    typer.Option("--config", help="Read this configuration file."),
]
CollectionArgument = Annotated[
    str,
    typer.Argument(help="Collection name from the configuration."),
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


def _collection(config: Config, name: str) -> Collection:
    try:
        return config.collection(name)
    except ConfigError as error:
        raise _fail(str(error)) from None


def _select(config: Config, name: str | None, every: bool) -> list[Collection]:
    if every and name:
        raise _fail("Specify COLLECTION_NAME or --all, not both")
    if not every and not name:
        raise _fail("Specify COLLECTION_NAME or --all")
    if every:
        selected = list(config.collections.values())
    else:
        assert name is not None
        selected = [_collection(config, name)]
    if not selected:
        raise _fail("The configuration contains no collections")
    return selected


def _show_configuration(
    config: Config, collection: Collection, *, use_cache: bool
) -> None:
    cache = str(collection.cache_file) if use_cache else "disabled"
    yt_dlp_options = shlex.join(config.yt_dlp_options) or "none"
    gallery_dl_options = shlex.join(config.gallery_dl_options) or "none"
    _echo("Configuration:")
    _echo(f"  file:               {config.source}")
    _echo(f"  collection:         {collection.name}")
    _echo(f"  URL:                {collection.url}")
    _echo(f"  target directory:   {collection.target_dir}")
    _echo(f"  cache:              {cache}")
    _echo(f"  yt-dlp options:     {yt_dlp_options}")
    _echo(f"  gallery-dl options: {gallery_dl_options}")
    _echo(f"  filename:           {runner.OUTPUT_TEMPLATE}")


def _run(
    config: Config,
    collection: Collection,
    use_cache: bool,
    dry_run: bool,
    verbose: bool,
) -> None:
    _show_configuration(config, collection, use_cache=use_cache)
    try:
        status = runner.run_collection(
            config,
            collection,
            use_cache=use_cache,
            simulate=dry_run,
            verbose=verbose,
            log=_echo,
        )
    except ConfigError as error:
        raise _fail(str(error)) from None
    if status:
        raise typer.Exit(code=1)


@app.command()
def run(
    collection_name: CollectionArgument,
    config_file: ConfigOption = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", "-n", help="Show work without downloads.")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", help="Print every collection item URL.")
    ] = False,
) -> None:
    """Download new items from a configured collection."""
    config = _load(config_file)
    _run(config, _collection(config, collection_name), True, dry_run, verbose)


@app.command()
def oneshot(
    collection_url: Annotated[str, typer.Argument(help="Collection URL.")],
    target_dir: Annotated[
        Path, typer.Option("--target-dir", help="Write downloads to this directory.")
    ],
    config_file: ConfigOption = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", "-n", help="Show work without downloads.")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", help="Print every collection item URL.")
    ] = False,
) -> None:
    """Download a collection without a cache or systemd units."""
    config = _load(config_file)
    collection = config_module.oneshot_collection(collection_url, target_dir)
    _run(config, collection, False, dry_run, verbose)


@completions_app.command("carapace")
def completions_carapace() -> None:
    """Print a carapace completion spec."""
    typer.echo(completions_module.render_carapace(app), nl=False)


@app.command("_complete", hidden=True)
def complete_values(
    what: Annotated[str, typer.Argument(help="Completion candidate set.")],
    config_file: ConfigOption = None,
) -> None:
    """Print completion candidates as value and description pairs."""
    try:
        config = config_module.load(config_file)
    except ConfigError, OSError:
        return
    if what == "collections":
        for collection in config.collections.values():
            typer.echo(f"{collection.name}\t{collection.target_dir}")


@systemd_app.command("install")
def systemd_install(
    on_calendar: Annotated[
        str, typer.Option("--on-calendar", help="Set the systemd OnCalendar value.")
    ],
    collection_name: Annotated[
        str | None,
        typer.Argument(help="Collection name from the configuration."),
    ] = None,
    config_file: ConfigOption = None,
    all_collections: Annotated[
        bool, typer.Option("--all", help="Install every collection.")
    ] = False,
    randomized_delay: Annotated[
        str | None,
        typer.Option(
            "--randomized-delay", help="Set the systemd RandomizedDelaySec value."
        ),
    ] = None,
    prune: Annotated[
        bool,
        typer.Option("--prune", help="Remove units absent from the configuration."),
    ] = False,
    enable: Annotated[
        bool,
        typer.Option("--enable/--no-enable", help="Reload and enable the timers."),
    ] = True,
) -> None:
    """Create the systemd units and set their schedule."""
    config = _load(config_file)
    collections = _select(config, collection_name, all_collections)
    names = [collection.name for collection in collections]
    for change in units.install(names, on_calendar, randomized_delay):
        _echo(f"{change.action:<10} {change.target}")

    if prune:
        orphans = [
            name
            for name in units.installed_instances()
            if name not in config.collections
        ]
        for change in units.uninstall(orphans):
            _echo(f"{change.action:<10} {change.target}")
        for name in orphans:
            units.systemctl("disable", "--now", units.instance_name(name, "timer"))

    if not enable:
        _echo("Skipped systemctl reload and timer enablement.")
        return
    units.systemctl("daemon-reload")
    for name in names:
        timer = units.instance_name(name, "timer")
        result = units.systemctl("enable", "--now", timer)
        if result.returncode:
            typer.secho(
                f"{timer}: {result.stderr.strip()}", fg=typer.colors.RED, err=True
            )
        else:
            _echo(f"enabled    {timer}")


@systemd_app.command("uninstall")
def systemd_uninstall(
    collection_name: Annotated[
        str | None,
        typer.Argument(help="Collection name from the configuration."),
    ] = None,
    config_file: ConfigOption = None,
    all_collections: Annotated[
        bool, typer.Option("--all", help="Uninstall every collection.")
    ] = False,
    disable: Annotated[
        bool,
        typer.Option("--disable/--no-disable", help="Stop and disable the timers."),
    ] = True,
) -> None:
    """Stop the timers and remove their systemd units."""
    config = _load(config_file)
    names = [
        collection.name
        for collection in _select(config, collection_name, all_collections)
    ]
    if disable:
        for name in names:
            units.systemctl("disable", "--now", units.instance_name(name, "timer"))
    remaining = [name for name in units.installed_instances() if name not in names]
    for change in units.uninstall(names, drop_templates=not remaining):
        _echo(f"{change.action:<10} {change.target}")
    if disable:
        units.systemctl("daemon-reload")


@systemd_app.command("status")
def systemd_status() -> None:
    """Show the state of each installed timer."""
    if not units.installed_instances():
        _echo("No units are installed.")
        return
    result = units.systemctl(
        "list-timers", "--all", "--no-pager", f"{units.PREFIX}@*.timer"
    )
    _echo(result.stdout.strip() or result.stderr.strip())
    if result.returncode:
        raise typer.Exit(code=result.returncode)


def main() -> None:
    app()
