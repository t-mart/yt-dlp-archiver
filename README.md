# yt-dlp-archiver

Download remote video sources into local directories. Helpful for archiving
sources of content that update frequently: TikTok collections, YouTube
channels/playlists, etc. Most helpful when run automatically, such as on a
systemd timer, which this program can install for you.

Uses embedded [yt-dlp](https://github.com/yt-dlp/yt-dlp) with it's
`--download-archive` flag to only download new items.

To fix a TikTok bug, this program also identifies and fixes downloads that have
no audio track repairs them in place.

## Install

```nushell
uv tool install --editable .
```

`ffmpeg` and `ffprobe` must be on `PATH`.

## Configure

Since this program is designed to be run repeatedly on the same set of URLs, it
uses a YAML config file to define jobs.

Create a file at `~/.config/yt-dlp-archiver/config.yaml` and define your options and jobs. Example:

```yaml
yt-dlp-options:
  firefox:
    sub-langs: "en.*"
    sponsorblock-mark: "all"
    embed-subs:
    embed-thumbnail:
    embed-metadata:
    remote-components: "ejs:github"
    cookies-from-browser: "firefox"

archive-jobs:
  tiktok-watch-on-desktop:
    url: <some video collection URL that yt-dlp can read>
    target-dir: ~/desktop
    options: firefox
    timer-oncalendar: "*-*-* 01:00:00"
    timer-randomized-delay: 30m
```

`yt-dlp-options` maps a set name to yt-dlp command line flags. Drop the `--`
prefix. Every yt-dlp flag works, so the yt-dlp documentation applies directly.

| YAML value    | Command line      |
| ------------- | ----------------- |
| `key:`        | `--key`           |
| `key: value`  | `--key value`     |
| `key: true`   | `--key`           |
| `key: false`  | `--no-key`        |
| `key: [a, b]` | `--key a --key b` |

A job's `options` takes one set name or a list of set names. Later names win.

Job names accept letters, digits, `.`, `_` and `-`. The name becomes the systemd
instance name.

The host `~/.config/yt-dlp/config` file is ignored, so a run is reproducible.

## Use

```nushell
yt-dlp-archiver list
yt-dlp-archiver show --job tiktok-watch-on-desktop
yt-dlp-archiver run --job tiktok-watch-on-desktop
yt-dlp-archiver run --all
yt-dlp-archiver run --job tiktok-watch-on-desktop --dry-run
```

Run an ad-hoc URL without a job from a config file:

```nushell
yt-dlp-archiver run --url https://example.com/video --target-dir ~/desktop --options firefox
```

`show` prints the resolved settings and the equivalent `yt-dlp` command line.

## Verify and repair

There is a process in this program that can fix previously-downloaded files that
have no audio track (likely from TikTok).

```nushell
yt-dlp-archiver verify --job tiktok-watch-on-desktop
yt-dlp-archiver verify --job tiktok-watch-on-desktop --repair
```

`verify` probes every media file in the target directory and reports the files
with no audio track. It exits non-zero when it finds one.

`verify --repair` fixes them in place. It reads the source URL from the embedded
metadata, downloads only an audio-bearing format, then muxes. The existing video
stream stays untouched. Files that already have audio are not modified.

## systemd

```nushell
yt-dlp-archiver systemd install --all
yt-dlp-archiver systemd status
yt-dlp-archiver systemd uninstall --job tiktok-watch-on-desktop
```

`install` writes three kinds of file into `~/.config/systemd/user`:

```
yt-dlp-archiver@.service                      shared template
yt-dlp-archiver@.timer                        shared template
yt-dlp-archiver@<job>.timer.d/schedule.conf   per-job schedule
```

`install` is idempotent. Run it again to update the units after a config change.
Use `--prune` to remove installed jobs that left the config. Use `--no-enable`
to write the files without calling `systemctl`.

A job with no `timer-oncalendar` gets no timer. Run it by hand.

Every generated file starts with `# Managed by yt-dlp-archiver. Do not edit.`
`uninstall` removes only files that carry this line.

Inspect a job:

```nushell
systemctl --user list-timers "yt-dlp-archiver@*"
journalctl --user --unit "yt-dlp-archiver@tiktok-watch-on-desktop.service" --lines 50
```

## Shell completion

Shell completion is provided by
[carapace](https://github.com/carapace-sh/carapace).

`yt-dlp-archiver completions carapace` prints a carapace spec on stdout. The
command reads the live command tree, so the spec stays correct after a change to
the CLI.

One spec serves every shell that carapace supports: bash, zsh, fish, nushell,
elvish, powershell, tcsh, xonsh and oil.

These values complete from your own data:

| Flag           | Candidates                      |
| -------------- | ------------------------------- |
| `--job`        | job names from your config file |
| `--options`    | option set names from that file |
| `--config`     | files                           |
| `--target-dir` | directories                     |

### Install the completion

```bash
mkdir -p ~/.config/carapace/specs
yt-dlp-archiver completions carapace > ~/.config/carapace/specs/yt-dlp-archiver.yaml
```

Then open a new shell to take effect.

Regenerate the spec after each upgrade of yt-dlp-archiver.

## Paths

| Purpose          | Path                                                   |
| ---------------- | ------------------------------------------------------ |
| Config           | `$XDG_CONFIG_HOME/yt-dlp-archiver/config.yaml`         |
| Download archive | `$XDG_STATE_HOME/yt-dlp-archiver/<job-name>.txt`       |
| systemd units    | `$XDG_CONFIG_HOME/systemd/user`                        |
| Completion spec  | `$XDG_CONFIG_HOME/carapace/specs/yt-dlp-archiver.yaml` |

## Develop

```nushell
uv run pytest
uv run ruff check src tests
uv run ruff format src tests
uv run ty check src tests
```
