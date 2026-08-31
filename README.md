# video-collection-archiver

video-collection-archiver downloads all items from a media collection. The `vca` command uses yt-dlp and gallery-dl.

The program targets TikTok collections. It converts each TikTok photo post into a Matroska slideshow.

## Requirements

- Python 3.14 or later
- `ffmpeg` and `ffprobe` on `PATH`

## Install

```sh
uv tool install git+https://github.com/t-mart/yt-dlp-archiver.git
```

## Configure

Create `$XDG_CONFIG_HOME/video-collection-archiver/config.yaml`. The default value of `$XDG_CONFIG_HOME` is `~/.config`.

```yaml
yt-dlp-options:
  embed-subs:
  embed-thumbnail:
  embed-metadata:
  cookies-from-browser: firefox

gallery-dl-options:
  cookies-from-browser: firefox

collections:
  tiktok-watch-on-desktop:
    url: "https://www.tiktok.com/@name/collection/example-123"
    target-dir: "~/Downloads/tiktok-watch-on-desktop"
```

Each downloader has one global option mapping. Omit the `--` prefix from each option name.

| YAML value    | Command-line arguments |
| ------------- | ---------------------- |
| `key:`        | `--key`                |
| `key: value`  | `--key value`          |
| `key: true`   | `--key`                |
| `key: false`  | `--no-key`             |
| `key: [a, b]` | `--key a --key b`      |

The program ignores the host configuration files for yt-dlp and gallery-dl.

## Download a configured collection

```sh
vca run tiktok-watch-on-desktop
```

The command prints the resolved configuration before it contacts the collection. Use `--dry-run` or `-n` to prevent downloads.

Use `--verbose` to print each collection item URL.

The command performs these operations:

1. Get all collection item URLs with yt-dlp.
2. Exclude URLs that occur in the collection cache.
3. Use gallery-dl metadata to identify TikTok photo posts.
4. Download videos with yt-dlp.
5. Download photo posts with gallery-dl and create Matroska slideshows.
6. Add each successful item URL to the collection cache.

A failed item does not enter the cache. Thus, the next run tries that item again.

## Download without a cache

```sh
vca oneshot "https://www.tiktok.com/@name/collection/example-123" --target-dir ~/Downloads/example
```

`oneshot` uses the global downloader options. It does not read or write a collection cache.

## File names

Downloads use this format:

```text
<title> - <platform> <video_id>.<ext>
```

yt-dlp sanitizes each name for the local file system. The title has a 180-byte limit.

The photo-post path uses the same yt-dlp filename formatter. Each photo post becomes one Matroska file.

The slideshow contains one 30 fps H.264 video stream. Each image appears for five seconds and starts at a keyframe.

The file has two audio tracks when a photo post contains audio. The default AAC track repeats until the slideshow ends.

The second track contains one uncut copy of the original audio stream. The file also contains the original images and audio as attachments.

## systemd

Create units for one collection with this command-line schedule:

```sh
vca systemd install tiktok-watch-on-desktop --on-calendar "*-*-* 01:00:00" --randomized-delay 30m
```

The schedule does not come from the configuration file. Run `install` again to change the schedule.

Use `--all` instead of a collection name to apply one schedule to every collection.

```sh
vca systemd status
vca systemd uninstall tiktok-watch-on-desktop
```

The `install` command creates these files:

```text
video-collection-archiver@.service
video-collection-archiver@.timer
video-collection-archiver@<collection>.timer.d/schedule.conf
```

Use `--no-enable` to create the files without a `systemctl` call. Use `--prune` to remove units absent from the configuration.

The `uninstall` command removes only files that contain the managed-file marker. Use `--no-disable` to omit the `systemctl` calls.

## Shell completion

The project supplies a [carapace](https://carapace-sh.github.io/carapace-bin/) specification.

```sh
mkdir -p ~/.config/carapace/specs
vca completions carapace > ~/.config/carapace/specs/vca.yaml
```

Regenerate the specification after each upgrade.

## Paths

| Purpose       | Path                                                               |
| ------------- | ------------------------------------------------------------------ |
| Configuration | `$XDG_CONFIG_HOME/video-collection-archiver/config.yaml`            |
| Cache         | `$XDG_STATE_HOME/video-collection-archiver/<collection-name>.txt`   |
| systemd units | `$XDG_CONFIG_HOME/systemd/user`                                     |
| Completion    | `$XDG_CONFIG_HOME/carapace/specs/vca.yaml`                          |

The default value of `$XDG_STATE_HOME` is `~/.local/state`.

## Develop

```sh
uv run ruff format --check src tests
uv run ruff check src tests
uv run ty check src tests
uv run pytest
```
