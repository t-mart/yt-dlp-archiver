# yt-dlp-archiver

Download remote media collections into local directories. This program supports
sources such as TikTok collections and YouTube channels.

The program embeds [yt-dlp](https://github.com/yt-dlp/yt-dlp) for videos. It
embeds [gallery-dl](https://github.com/mikf/gallery-dl) for TikTok photo posts.
Download archives prevent duplicate downloads.

The program can also repair video downloads that have no audio track.

## Install

```nushell
uv tool install git+https://github.com/t-mart/yt-dlp-archiver.git
```

`ffmpeg` and `ffprobe` must be on `PATH`.

## Configure

Since this program is designed to be run repeatedly on the same set of URLs, it
uses a YAML config file to define jobs.

Create a file at `~/.config/yt-dlp-archiver/config.yaml` and define your options
and jobs. Example:

```yaml
yt-dlp-options:
  firefox: # a name for the options
    # example options, see below for syntax
    sub-langs: "en.*"
    sponsorblock-mark: "all"
    embed-subs:
    embed-thumbnail:
    embed-metadata:
    remote-components: "ejs:github"
    cookies-from-browser: "firefox"

gallery-dl-options:
  firefox:
    cookies-from-browser: "firefox"

archive-jobs:
  some-collection: # a name for the job
    url: <some media URL> # what to download
    target-dir: ~/desktop # where to put the downloaded files
    yt-dlp-options: firefox # reference a yt-dlp option set
    gallery-dl-options: firefox # reference a gallery-dl option set
    timer-oncalendar: "*-*-* 01:00:00" # accepts any systemd OnCalendar value
    timer-randomized-delay: 30m # accepts any systemd RandomizedDelaySec value
```

`yt-dlp-options` and `gallery-dl-options` map set names to command-line flags.
Drop the `--` prefix from each flag.

| YAML value    | Command line      |
| ------------- | ----------------- |
| `key:`        | `--key`           |
| `key: value`  | `--key value`     |
| `key: true`   | `--key`           |
| `key: false`  | `--no-key`        |
| `key: [a, b]` | `--key a --key b` |

Each job option key accepts one set name or a list of names. Later names win.

Change each old job `options` key to `yt-dlp-options`.

Job names accept letters, digits, `.`, `_` and `-`. The name becomes the systemd
instance name.

The program ignores the host yt-dlp and gallery-dl config files.

The program controls gallery-dl output paths, filenames, archives, and TikTok
media selection. Configured values for these options have no effect.

### TikTok photo posts

The program follows TikTok short-link redirects before it selects a downloader.
It sends `/video/` URLs to yt-dlp and `/photo/` URLs to gallery-dl.

Each photo post becomes one Matroska file. The video stream contains the original
JPEG data without a lossy conversion. Each image appears for five seconds and
has a chapter. The optional audio track repeats until the slideshow ends.

The final filename uses the yt-dlp output template. The default name contains
the TikTok title, tags, and post ID.

## Use

```nushell
yt-dlp-archiver list                                  # list all jobs
yt-dlp-archiver run --job some-collection             # run a job
yt-dlp-archiver run --all                             # run all jobs
yt-dlp-archiver run --job some-collection --dry-run   # show what would be downloaded
yt-dlp-archiver show --job some-collection            # show downloader commands
```

Run an ad-hoc URL without a job from a config file:

```nushell
yt-dlp-archiver run --url https://example.com/video --target-dir ~/desktop --yt-dlp-options firefox
```

Add `--gallery-dl-options firefox` to select a gallery-dl option set.

`show` prints the resolved settings and both downloader command lines.

## Verify and repair

There is a process in this program that can fix previously-downloaded files that
have no audio track (likely from TikTok).

```nushell
yt-dlp-archiver verify --job some-collection
yt-dlp-archiver verify --job some-collection --repair
```

`verify` probes every media file in the target directory. It reports video files
that have no audio track. Silent TikTok photo posts are valid.

`verify --repair` fixes them in place. It reads the source URL from the embedded
metadata, downloads only an audio-bearing format, then muxes. The existing video
stream stays untouched. Files that already have audio are not modified.

## systemd

```nushell
yt-dlp-archiver systemd install --all
yt-dlp-archiver systemd status
yt-dlp-archiver systemd uninstall --job some-collection
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
This serves as a marker for `uninstall`, which removes only files that carry
this line.

Inspect a job:

```nushell
systemctl --user list-timers "yt-dlp-archiver@*"
journalctl --user --unit "yt-dlp-archiver@some-collection.service" --lines 50
```

## Shell completion

Shell completion is provided by
[carapace](https://github.com/carapace-sh/carapace).

Install the completion spec for carapace with:

```bash
mkdir -p ~/.config/carapace/specs
yt-dlp-archiver completions carapace > ~/.config/carapace/specs/yt-dlp-archiver.yaml
```

Rewrite the spec after each upgrade of yt-dlp-archiver.

### Install the completion

Then open a new shell to take effect.

## Paths

| Purpose            | Path                                                       |
| ------------------ | ---------------------------------------------------------- |
| Config             | `$XDG_CONFIG_HOME/yt-dlp-archiver/config.yaml`             |
| yt-dlp archive     | `$XDG_STATE_HOME/yt-dlp-archiver/<job-name>.txt`           |
| gallery-dl archive | `$XDG_STATE_HOME/yt-dlp-archiver/<job-name>.gallery-dl.txt` |
| systemd units      | `$XDG_CONFIG_HOME/systemd/user`                            |
| Completion spec    | `$XDG_CONFIG_HOME/carapace/specs/yt-dlp-archiver.yaml`     |

## Develop

```nushell
uv run pytest
uv run ruff check src tests
uv run ruff format src tests
uv run ty check src tests
```
