# yt-dlp-archiver plan

## 1. The missing audio bug

### Symptom

The audio track is absent. It is not silent. The broken files contain no audio
stream at all.

### Evidence

A probe of all 120 files in `~/desktop` gives this result:

| Video codec | Has audio | No audio |
| ----------- | --------- | -------- |
| h264        | 5         | 0        |
| hevc (h265) | 94        | 21       |

Duration correlates but does not explain the fault. Broken files start at 127
seconds. Good files exist at 641 seconds.

### Root cause

TikTok publishes two format families:

- `h264_*` and `download`: H.264, always muxed with AAC audio.
- `bytevc1_*`: H.265, sometimes video only.

TikTok reports `acodec=aac` on every format. For some videos the `bytevc1`
bytes contain no audio track. The metadata is wrong.

A direct test of video `7653695564026023182` proves this:

| Format                 | Advertised   | Actual content |
| ---------------------- | ------------ | -------------- |
| `bytevc1_1080p_812562` | `acodec=aac` | video only     |
| `bytevc1_720p_435796`  | `acodec=aac` | video only     |
| `h264_720p_1210205`    | `acodec=aac` | video + audio  |
| `h264_540p_427264`     | `acodec=aac` | video + audio  |
| `download`             | `acodec=aac` | video + audio  |

`bytevc1` is the only family with a 1080p rung. yt-dlp ranks it first on
resolution. yt-dlp trusts `acodec` and does not merge an audio stream. The
output has no audio.

### Why no format selector fixes this

A merge selector such as `-f "bv*[vcodec^=h265]+ba*[vcodec^=h264]"` collapses to
a single format. See
[YoutubeDL.py:2463-2477](/home/tim/.local/share/uv/tools/yt-dlp/lib/python3.13/site-packages/yt_dlp/YoutubeDL.py#L2463-L2477).
The prune loop sets `get_no_more` for audio and video from the first format,
because that format declares both codecs. Then it drops the second format.
`--audio-multistreams` alone does not stop this. Both multistream flags together
stop it, but then correct videos get two audio tracks and two video tracks.

No field predicts the fault. A diff of the two format dictionaries shows
`acodec=aac` and `abr=None` on both.

**Conclusion: only the downloaded bytes tell the truth. The tool must probe
after download.**

### The repair

A stream copy mux is sufficient. No re-encode:

```
ffmpeg -i <h265-video-only> -i <h264-muxed> -map 0 -map 1:a:0 -c copy out.mp4
```

Verified: output is 1080x1920 hevc plus stereo AAC, 12.4 MB.

### Why the archive must not record a broken file

yt-dlp writes the archive entry after post-processing. See
[YoutubeDL.py:3666-3677](/home/tim/.local/share/uv/tools/yt-dlp/lib/python3.13/site-packages/yt_dlp/YoutubeDL.py#L3666-L3677).
A `PostProcessingError` returns early, so `__write_download_archive` stays
unset. A verification post-processor that raises keeps the video out of the
archive. The next run retries it. This is the correct behavior and it needs no
private API.

## 2. Architecture

### Embedded library, not subprocess

Use `yt_dlp` as a library. Reasons:

- The verify and repair step needs the output path and the format list. A
  subprocess forces us to parse `--print` output.
- The repair step needs a second targeted download. A nested `YoutubeDL` call is
  direct.
- A custom post-processor gives the archive semantics in section 1 for free.

Build the options with `yt_dlp.parse_options()`. It converts CLI flags into
`YoutubeDL` parameters, including the full post-processor chain for
`--embed-subs`, `--embed-thumbnail`, `--embed-metadata` and `--sponsorblock-mark`.
Confirmed to work on the installed version.

Cost: `parse_options` is not a documented public API. Mitigation: pin `yt-dlp`
in `uv.lock` and add a test that asserts the translation of the exact flag set
in the config.

Cost: yt-dlp updates now come from `uv.lock`, not from `uv tool upgrade`.

### Verify and repair algorithm

Register a post-processor at `when='post_process'`.

1. Probe the output file with `ffprobe`. Count the audio streams.
2. If an audio stream exists, return. No change.
3. If no audio stream exists, select repair candidates from `info_dict`:
   - Keep formats with `vcodec != 'none'`.
   - Drop the format that was downloaded.
   - Drop duplicate CDN mirrors. `-0` and `-1` hold identical content.
   - Put formats with a different `vcodec` first. The alternate codec family is
     the family that carries real audio.
   - Sort by `tbr` descending. Put an absent `tbr` last.
4. Download the first candidate to a temporary file. Probe it.
5. If it has audio, mux with `-map 0 -map 1:a:0 -c copy -map_metadata 0`.
   `-map 0` keeps the subtitle track and the thumbnail stream.
6. If it has no audio, try the next candidate. Limit to 2 candidates.
7. If no candidate has audio, the source is genuinely silent. Accept the file
   and log a warning. This guarantees that the job terminates.

The post-processor runs last, after the embed steps. `-map 0` preserves their
output.

### Audio quality drives the candidate order

Do not select the cheapest candidate. TikTok ties audio quality to the video
rung. Measured on video `7653695564026023182`:

| Format             | Size    | Audio            |
| ------------------ | ------- | ---------------- |
| `h264_540p_427264` | 6.8 MB  | HE-AACv2 32 kbps |
| `download`         | 18.8 MB | HE-AACv2 32 kbps |
| `h264_720p_1210205`| 19.5 MB | HE-AACv2 64 kbps |

The cheapest candidate carries the worst audio. `tbr` descending is the correct
proxy, because the format dictionary reports `abr=None` on every format.

### No format-strategy option

Always run verify and repair. Do not add a `prefer-avc` strategy. That strategy
encodes a TikTok-specific fact into a tool that serves every yt-dlp site. A user
who wants that behavior sets `format-sort` in a `yt-dlp-options` set.

## 3. Configuration

Path: `$XDG_CONFIG_HOME/yt-dlp-archiver/config.yaml`, default
`~/.config/yt-dlp-archiver/config.yaml`.

A directory holds future files. A single flat file does not.

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
    url: https://www.tiktok.com/@seasonproperly/collection/watch%20on%20desktop%20later-7603372412029111071
    target-dir: ~/desktop
    options: firefox
    timer-oncalendar: "*-*-* 01:00:00"
    timer-randomized-delay: 30m
```

Flag rendering rules:

| YAML value  | Command line     |
| ----------- | ---------------- |
| `key:`      | `--key`          |
| `key: val`  | `--key val`      |
| `key: true` | `--key`          |
| `key: false`| `--no-key`       |
| `key: [a,b]`| `--key a --key b`|

`options:` accepts a name or a list of names. Later names win.

**Correction to the stub config**: the URL needs `%20`, not `%%20`. The `%%`
escape belongs to systemd unit files. The URL now lives in YAML, so the escape
is wrong there.

Validate job names against `[A-Za-z0-9._-]+`. This keeps unit names readable and
removes the need for `systemd-escape`.

## 4. State paths

Download archive: `$XDG_STATE_HOME/yt-dlp-archiver/<job-name>.txt`, default
`~/.local/state/yt-dlp-archiver/<job-name>.txt`.

`$XDG_STATE_HOME` is correct. The XDG specification lists "actions history" as
state. A download archive is a history of downloaded IDs. It is also
reconstructible from the target directory, because each filename holds the ID.

Logs go to the journal. Do not write log files.

Migration of the existing 258-entry archive:

```nushell
mkdir ~/.local/state/yt-dlp-archiver
mv ~/.local/state/yt-dlp-schedule-archive.txt ~/.local/state/yt-dlp-archiver/tiktok-watch-on-desktop.txt
```

## 5. systemd units

Use template units. The instance name is the job name.

```
~/.config/systemd/user/yt-dlp-archiver@.service
~/.config/systemd/user/yt-dlp-archiver@.timer
~/.config/systemd/user/yt-dlp-archiver@<job>.timer.d/schedule.conf
```

The two templates hold the shared definition. A per-instance drop-in holds
`OnCalendar` and `RandomizedDelaySec`. systemd reads drop-ins from
`<full-unit-name>.d/`, so per-instance override works.

`yt-dlp-archiver@<job>.timer` activates `yt-dlp-archiver@<job>.service` by name.
No `Unit=` line is needed.

Service template:

```ini
# Managed by yt-dlp-archiver. Do not edit.
[Unit]
Description=yt-dlp archive job %i
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=%h/.local/bin/yt-dlp-archiver run --job %i
TimeoutStartSec=6h
Nice=10
IOSchedulingClass=idle
```

Timer template:

```ini
# Managed by yt-dlp-archiver. Do not edit.
[Unit]
Description=Schedule for yt-dlp archive job %i

[Timer]
Persistent=true
AccuracySec=1m

[Install]
WantedBy=timers.target
```

Two benefits over the current unit:

- The URL leaves the unit file, so the `%%20` escape problem disappears.
- One `ExecStart` line serves every job.

Resolve the absolute path of the `yt-dlp-archiver` executable at install time.
systemd requires an absolute path.

Write the header `# Managed by yt-dlp-archiver. Do not edit.` into every
generated file. Delete only files that carry this header.

Commands:

- `install`: write the templates and the drop-in, run `daemon-reload`, then
  `enable --now` the timer.
- `uninstall`: run `disable --now`, remove the drop-in directory. Remove the
  templates when no instance remains.
- Update: run `install` again. The operation is idempotent.
- `install --all --prune`: remove installed instances that no longer exist in
  the config.

Rename of a job means uninstall and install. Report orphaned instances.

## 6. Command line

```
yt-dlp-archiver run --job <name>
yt-dlp-archiver run --all
yt-dlp-archiver run --url <url> --target-dir <dir> [--options <name>]
yt-dlp-archiver verify --job <name> [--repair]
yt-dlp-archiver list
yt-dlp-archiver show --job <name>
yt-dlp-archiver systemd install [--job <name> | --all] [--prune]
yt-dlp-archiver systemd uninstall [--job <name> | --all]
yt-dlp-archiver systemd status
```

Global flags: `--config <path>`, `--dry-run`, `--verbose`.

`show` prints the resolved job settings and the equivalent `yt-dlp` command
line, shell-quoted. The name `show` follows `docker compose config` and
`git config --list`. It reads better than `render-command`, and it leaves room
to print more than the command.

Exit non-zero when any item fails. systemd then marks the unit failed and
`systemctl --user list-units --failed` shows it.

`verify --repair` fixes files that are already broken. It does not re-download
the video. It reads the source URL from the embedded `comment` tag, fetches only
the best audio-bearing format, then muxes the audio into the existing file. The
original video stream stays untouched.

## 7. Dependencies

Python packages:

```
yt-dlp[default,curl-cffi]
pyyaml
typer
```

Drop `httpx`. Nothing needs it.

System binaries: `ffmpeg` and `ffprobe`. Both are present.

`deno` is present. It serves `--remote-components ejs:github` for YouTube. TikTok
does not need it.

Command to add the dependency:

```nushell
uv add "yt-dlp[default,curl-cffi]"
uv remove httpx
```

Note: the host CLI prints `no impersonate target is available` even though
`curl-cffi` is installed in its environment. Check this during implementation.
TikTok extraction works without it today.

## 8. Tests

- Flag rendering: YAML mapping to argument list, all five value forms.
- `parse_options` translation of the config flag set produces the expected
  post-processor keys.
- Audio detection: probe a fixture with audio and a fixture without audio.
- Repair candidate selection: order, mirror de-duplication, exclusion of the
  downloaded format.
- Unit file generation: template text, drop-in content, job name validation.

Use the files in `/tmp/fmt` as fixtures. Truncate them first.

## 9. Decisions

1. `uv.lock` pins the yt-dlp version. Accepted.
2. Always run verify and repair. No `format-strategy` option.
3. Config path is `~/.config/yt-dlp-archiver/config.yaml`.
4. Accept a silent source and log a warning, so the job terminates.
5. `verify --repair` muxes audio into the existing file. It never re-downloads
   the video.

## 10. Known gap

The names in `~/.local/state/yt-dlp-schedule-archive.txt` do not all match the
files in `~/desktop`. Handle this later. Do not modify the existing video files
during implementation.
