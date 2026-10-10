# VLoader

**A modern, dark-themed video downloader, converter & screen recorder for Windows —
built entirely on open-source components (yt-dlp + ffmpeg + PySide6).**

VLoader is a clean-room desktop application in the "video downloader converter"
category: paste a link, get the video; convert, trim, merge or record when you
need more. No accounts, no ads, no telemetry, no license checks.

![Platform](https://img.shields.io/badge/platform-Windows-7c6cff)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## Features

### Download
- **1000+ sites** via the bundled yt-dlp engine: YouTube, Vimeo, Dailymotion,
  Facebook, SoundCloud, Twitch, and many more (anything yt-dlp supports)
- **Playlists & channels** — paste one URL, every item is queued automatically
- **Bulk URLs** — paste many links at once (one per line)
- **Quality picker** — Best Available / 1080p / 720p / 480p / 360p / 240p / Worst
- **Pause & resume** — interrupted downloads keep their partial file and continue
  where they left off
- **Auto-convert on download** — e.g. always save as MP3 or MP4
- **Metadata recorded in every file** — title, artist and year are written
  into downloaded audio/video (visible in Windows Properties → Details),
  and conversion outputs keep the tags
- **Queue control** — configurable simultaneous downloads, per-task and batch
  start / pause / stop, reorder, checkboxes
- **History** — persistent log of every download and conversion

### Live streams
- **Record live streams** — paste a live page URL (e.g. a webcam room) and
  VLoader records it while it plays, with both video and audio
- **● LIVE status** — live tasks show a red badge, an indeterminate progress
  bar and the recording elapsed time instead of a percentage
- **Graceful stop** — the ⏹ button sends ffmpeg a quit command so the MP4 is
  finalized immediately and stays playable
- **Crash recovery** — every active recording is registered on disk; if the
  app is force-killed mid-recording, the next launch detects the orphaned
  partial and re-muxes it into a playable MP4 automatically (a force-killed
  app can leave an orphan ffmpeg behind — `taskkill /F /IM ffmpeg.exe`
  releases the file so the next run can repair it)
- **Original naming** — recordings are saved like `model 2026-10-10 22:32.mp4`,
  named after the title/timestamp the site reports
- Quality selection applies (best variant not exceeding the chosen resolution);
  Pause is disabled for live tasks (a live stream cannot be resumed mid-air)

### Spotify
- **Paste any Spotify link** — a track, an album or a playlist (also accepts
  `spotify:track:…` URIs and `spotify.link` short links)
- **Tagged MP3, 320 kbps** — every track is saved with full ID3v2 tags:
  title, artist, album, year, track number and genre, plus the cover art
  embedded (all visible in Windows file Properties → Details)
- **Format choice** — MP3 320 kbps (universal), or **FLAC / WAV** for a
  lossless copy of the source audio (no re-encode loss; note the source
  itself is lossy, so FLAC preserves rather than invents quality)
- **Album / playlist folders** — collections download into their own folder
  (`Artist - Album/01 - Title.mp3`, playlists numbered with artist names)
- Metadata (track list, covers) comes from Spotify's public embed pages —
  no account or API key needed. Audio is fetched from a public source
  (YouTube search for "artist - title"), the same approach every web
  Spotify downloader uses, since Spotify's own streams are DRM-protected
- **Album-version matching** — candidates are scored against Spotify's
  exact duration, so you get the clean album/Topic upload instead of
  music-video edits (intros, shortened cuts), live versions, remixes or
  sped-up uploads
- Per-track progress in the Activity table; a track with no match is
  skipped and reported while the rest of the collection continues
- Missing fields are enriched from the iTunes Search API (public, no
  key): album, year, track number and genre

### Convert
- **15 output formats** — MP4, MKV, AVI, MOV, WMV, FLV, WebM, XviD (video) and
  MP3, M4A, WMA, WAV, FLAC, OGG (audio)
- **Trim / cut** any fragment with start & end times
- **Volume adjustment** (amplify or attenuate)
- **Merge** multiple clips into one file (mixed codecs handled safely)
- **Quality presets** — High / Normal / Low (CRF-tuned)
- Optional "delete original after conversion"

### Transcripts
- **Download video transcripts** alongside any video — manual or
  auto-generated captions, multiple languages at once
- **Export as Markdown (.md)** — heading, language + source metadata, and
  per-line `[mm:ss]` timestamps; also exportable as **SRT** or **WebVTT**
- **Convert existing transcripts** — load any `.vtt` / `.srt` file into the
  Convert pane and turn it into Markdown (timestamps optional)

### Record
- **Screen recorder** — full screen or a drag-selected region
- **MP4 output** (H.264, yuv420p) playable everywhere
- **Global hotkeys** — F9 record/pause, F10 stop (registered via Win32 API)
- Optional system-audio capture via a dshow loopback device

### Browser integration
- **Chrome (MV3) and Firefox (MV2) extensions** overlay a "Download" button on
  videos as you browse; one click sends the page URL to the app through a local
  HTTP bridge (`127.0.0.1:8765`) — nothing leaves your machine

### Automation & UX
- **After-finish actions** — exit / shut down / restart / log off / hibernate /
  stand by when all tasks complete (with confirmation)
- **Command-line interface** for scripting and scheduled jobs
- **17 UI languages** (English complete; others cover core UI with graceful
  English fallback)
- **Modern dark UI** — custom QSS theme, sidebar navigation, card layout,
  color-coded task statuses, gradient accents

## Screenshots

Rendered previews of the three main pages (Download / Activity / Convert) are
generated by `tools/screenshot.py`:

```
python tools/screenshot.py    # writes tools/shot_*.png
```

## Getting started

### Requirements
- Windows 10/11
- Python 3.10+
- `pip install PySide6 yt-dlp`

### ffmpeg

VLoader needs an `ffmpeg.exe` / `ffprobe.exe` build. Either:

- drop a static build into `bin/` (e.g. the "essentials" build from
  https://www.gyan.dev/ffmpeg/builds/), or
- make sure `ffmpeg` is on your `PATH`.

`bin/` is intentionally not committed (binaries exceed GitHub's file-size limit).

### Run

```
vloader.bat                                # GUI
python -m vloader --url "https://..."      # add a download on launch
python -m vloader --url "..." --quality 720 --exit force
python -m vloader --install-plugins        # browser extension instructions
```

### Browser extensions

- **Chrome:** `chrome://extensions` → enable *Developer mode* → *Load unpacked* →
  `extensions\chrome`
- **Firefox:** `about:debugging` → *This Firefox* → *Load Temporary Add-on* →
  `extensions\firefox\manifest.json`

## Command line

| Option | Effect |
|---|---|
| `--url URL` (repeatable) | download URL(s) on launch |
| `--quality N` | `best`, `1080`, `720`, `480`, `360`, `240`, `worst` |
| `--output-dir DIR` | override download directory |
| `--convert-to FMT` | auto-convert finished downloads |
| `--subtitles md|srt|vtt`\|srt\|vtt` | also download the transcript in that format |
| `--sub-langs en,de` | transcript languages (default: en) |
| `--sub-auto` / `--no-sub-auto` | include auto-generated captions (default on) |
| `--transcript-only` | skip the video, download just the transcript |
| `--exit [force]` | exit after finishing (`force` skips prompts) |
| `--install-plugins` / `--uninstall-plugins` | print extension instructions |
| `--version` | print version |

## Architecture

```
vloader/
  __main__.py        CLI entry (GUI or headless download)
  settings.py        JSON-backed persistent settings (%APPDATA%\VLoader)
  history.py         download/convert history (JSON)
  downloader.py      yt-dlp engine, QThread workers, concurrency-limited queue
  converter.py       ffmpeg subprocess wrapper: convert/trim/volume/merge
  recorder.py        ffmpeg gdigrab capture + Win32 global hotkeys
  bridgeserver.py    local HTTP bridge for browser extensions
  transcripts.py     VTT/SRT parser + Markdown/SRT/VTT export
  afterdone.py       after-finish power actions
  i18n.py            JSON dictionary i18n with English fallback
  i18n/*.json        17 language files
  ui/
    theme.py         application-wide dark QSS theme
    main_window.py   sidebar nav, menus, task wiring, after-done logic
    panes.py         Download pane & Convert pane
    activity.py      task table (progress/speed/ETA, colored statuses)
    recorder_window.py  region overlay + recorder controls
    dialogs.py       preferences, history, about
extensions/
  chrome/            Manifest V3 helper
  firefox/           Manifest V2 helper
bin/                 ffmpeg.exe + ffprobe.exe (not committed)
tools/
  e2e_test.py        headless end-to-end test (download/convert/trim/merge)
  screenshot.py      render UI pages to PNG
  gen_langs.py       language-file generator
```

### Design notes
- Downloads run in `QThread` workers; yt-dlp cancellation is cooperative
  (progress-hook exception), which also powers pause/resume via partial files.
- Conversions are plain ffmpeg subprocesses; progress is parsed from ffmpeg's
  stderr `time=` against the source duration probed by ffprobe.
- Merging uses ffmpeg's `concat` filter (re-encode) so mixed codecs/resolutions
  can't produce broken output.
- The browser bridge binds only to `127.0.0.1` and accepts no external traffic.

## Testing

```
python tools/e2e_test.py
```

Downloads a small public sample clip, converts it, trims it, and merges two
clips — verifying the whole pipeline end to end.

## Known limitations

- No passive HTTP "sniffer" — use the extensions or paste URLs instead.
- Recorder pause = stop + new take (a gdigrab limitation).
- System-audio recording requires a dshow loopback device such as
  *virtual-audio-capturer*.
- DRM-protected streams are not supported by design.
- Live recording needs the broadcaster to be online at grab time; a finished
  live task cannot be re-downloaded retroactively.

## License

MIT — see [LICENSE](LICENSE).
yt-dlp and ffmpeg are governed by their respective licenses.
