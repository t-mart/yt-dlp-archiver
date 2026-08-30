# Redo

This document describes how I want to redo/rearchitect this project.

## Rename

As you will see, yt-dlp-archiver is no longer an apt name because we now
archiving with more than just yt-dlp. Instead, lets call it
`video-collection-archiver`. The cli tool and module name can be called `vca`
for short. But metadata/documentation should use the full name.

i will rename the repo dir and remote later.

## Too general

> Premature optimization is the root of all evil.

We tried to make this project general purpose, but it has become too complex and
serves use cases that are not relevant to me.

For now, let's solve the minimum problem that I have:

- I have a tiktok collection URL (i save things to it that I want to archive).
- I want this program to download all the video URLs in that collection
  - Note that it may not be just videos, it may be image slideshows, which we
    already have good machinery to make videos from (with attachments, mkv
    containers, etc).
- The software should keep a cache file to track of which ones I have already
  downloaded. This works well in ~/.local/cache/<program_name>/<job_name>.txt.
  (I will discuss `program_name` later.) Therefore, when I run the program
  again, it should only download the new ones.

  We used to rely on yt-dlp's `--archive` option, but that's insufficient
  because we don't always download with yt-dlp.

- And yes, here's how we should do it:
  - yt-dlp is good for getting the collection item URLs. keep doing that, and do
    it first.
  - then, we need to determine filter out which ones have already been
    downloaded.
  - then, we need to figure out which are videos and which are image slideshows.
    (I think we use gallery-dl to interrogate this, that is fine).
  - once the media type is determined, we can download the media with the
    appropriate tool (yt-dlp or gallery-dl).

- Our systemd integration are currently good, don't need to mess with those
  much. however, we should no longer pull timer-oncalendar/randomized-delay
  option values from the config file. (because that implies that updating the
  config will update the systemd timer, which is not true). instead, these
  params should come from command line arguments when the systemd service/timer
  is created.
- Redo the config file format.

  The config file should not have option profiles for yt-dlp and gallery-dl. It
  should instead have a single global profile (again, don't need to premature
  optimize for other use cases).

  Something like this could be fine:

  ```yaml
  yt-dlp-options:
    yadda-yadda: ""
  gallery-dl-options:
    yadda-yadda: ""

  collections:
    tiktok-watch-on-desktop: # collection name, used for cache file and systemd service/timer names
      url: "https://www.tiktok.com/collection/..."
      target-dir: "/home/tim/Downloads/tiktok-watch-on-desktop"
    foo:
      url: "https://www.tiktok.com/collection/..."
      target-dir: "/home/tim/Downloads/foo"
  ```

- Remove any machinery around supporting old config formats or cli options. Just
  fail with a clear error message if the config file is not in the new format.
  Don't talk about migration.

- We should have the following subcommands:
  - `vca run <collection_name>`: download the collection, using the cache file
    to skip already downloaded items. When we run, we should print the config
    options that are being used, so that the user can verify that they are
    correct.
  - `vca oneshot <collection_url> --target-dir <dir>` : download the collection,
    no caching, no systemd integration. This is for one-off downloads (or to
    test things). Again, also print relevant config.
  - `vca systemd`, good as-is, but again, oncalendar and other systemd stuff
    comes from command line, not config file.
  - `vca completions`, good as-is
  - `vca verify`: delete this. not necessary anymore.

  There are other nuances of the subcommands, just do what you think is best.
  Try to follow `https://clig.dev` for best practices. You should quickly review
  this document before implementing. If anything I'm prescribing contradicts
  what is in this document, bring it up with me at the end.

- file naming needs to be reworked. i want this:

  `<title> - <platform> <video_id>.<ext>`

  where `<platform>` is the name of the platform (tiktok, youtube, etc),
  `<video_id>` is the unique id of the video, `<title>` is the title of the
  video, and `<ext>` is the file extension.

  Use best judgement for titles with sanitization and length limits. (Try to do
  what yt-dlp does, and make sure that gallery-dl can do it too)
