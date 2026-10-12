# KaZaA v2. revival

## start1: local desktop app

This branch starts the rebuild with a native local app shell. It matches Ohana AI's
cream and terracotta light theme, warm charcoal dark theme, typography, and sidebar.
The integrated header uses the workspace background, a text-only KaZaA wordmark,
and a compact row of sidebar, theme and appearance controls. Minimize, maximize,
restore and close sit at the right. Windows dragging, edge resizing and snapping
use native frame handling without a separate system title bar.
The sidebar has three pages: **Search**, **Downloads**, and **Shred**.
Sidebar collapse/resizing, keyboard shortcuts, and saved appearance preferences
work. The icon-only gear beside the wordmark opens theme and download-folder settings.
The sidebar toggle has no persistent selection outline. The rounded K-and-orbit
icon is used by the desktop shortcut and taskbar; the header displays only letters.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-video.txt
.\kazaa.bat
```

The app uses PySide6 Essentials, yt-dlp and libtorrent. Video/audio exports need FFmpeg;
install it on PATH or use the existing bundled tools. YouTube extraction also
uses Node.js 22 or newer on PATH and the solver included by `yt-dlp[default]`.
Caption-only exports do not require FFmpeg. There is no local server; network
requests happen when you inspect or download a link.
Appearance is saved in `%APPDATA%\KaZaA\shell-settings.json`; download options
and history are saved in `%APPDATA%\KaZaA\video-downloads.json`.
Use Ctrl+B to toggle the sidebar, Ctrl+, for settings, Ctrl+Shift+L to change theme,
and Ctrl+L to focus Search.

### Shred

Drop individual local files from Windows Explorer into the Shred table.
The table shows name, type, path, size and status. Files start
checked; use the table's header checkbox or individual checkboxes to choose
the batch. Click rows to highlight them, Ctrl-click for multiple rows, or Shift-click
for a range. Right-click the highlighted rows and choose **Remove**, or press Delete,
to remove them from the list without touching files on disk. Escape clears highlights.

Open **Algorithm** beside **Shred selected** to choose Single pass (default), Two passes, DoD-style (3), Seven passes, or Gutmann
(35), then **Shred selected** and confirm the batch. Every pass overwrites all
data streams, flushes writes and verifies the contents by reading them back.
Random passes use fresh cryptographic random bytes. The algorithm and active
tab are remembered. Files sent from Downloads stay queued across app restarts;
their paths and file identities are saved locally until shredded or removed from
the queue. Files added manually and shredding history stay only in memory.
The table is centered at 75% of the workspace width, adapting to smaller windows.
Per-file percentages and thin progress bars match Downloads; overall progress
appears below the table only while shredding; idle counts and explanatory footer text
are hidden. Verified successes leave the table immediately, while
failed and cancelled files stay with their status and error tooltips. The
confirmation has only Cancel and Shred controls. Cancelling or closing the app
stops the worker safely; a partly overwritten file stays at its existing size,
but completed overwrites cannot be undone. Errors never report successful deletion.

This is logical file overwriting on local Windows NTFS drives, not physical
device sanitization. SSD remapping, filesystem metadata, backups and snapshots
can retain information, and more passes do not overcome those limits. Folders,
network paths, links/junctions, cloud placeholders, hard-linked files and files
that are read-only, system, sparse, compressed, EFS-encrypted or offline are
rejected. A file that changed after being added must be removed and added again.
No drive-wide or free-space wiping is performed.

### Search and downloads

Paste one or several video links into Search, then click **Inspect** or press Enter.
Shift+Enter adds another line. Each result shows its title, thumbnail, creator,
and duration. YouTube and other yt-dlp-supported video sites
use the same workflow; individual site restrictions can still prevent extraction.
Links that cannot be inspected show a small **This link is not supported.** notice
instead of an unavailable preview and technical error text. Their input stays for retry.
New results default to Video, regardless of the previous export type.
After inspection, choose separately for each result using the compact controls
and Download button in a single row to the right of the preview:

- Video: MP4, MKV or WebM, with best quality or a resolution provided by the source.
- Audio: MP3, M4A, FLAC, WAV or OGG, with bitrate choices for lossy formats.
- Transcript/subtitles: SRT, VTT, TXT or Markdown, in an available language,
  using creator-provided or automatically generated captions.
- Caption source and language appear only for Transcript. Video/audio exports
  do not include captions. Set the remembered **Download folder** in the gear Settings.

Click a result's **Download**, or select results and choose **Download selected**.
Successfully queued results and their input links leave Search and appear in Downloads immediately,
without a queued notification;
failed submissions stay in Search with their error. Two jobs run at a time;
each keeps the options selected when it was queued.
Links already in Downloads can be submitted with a different type or output format.
The same link, type and format cannot be submitted twice, even with a different
quality or folder, or after restarting the app. Resume and Retry use the
existing entry. Removing the entry from history allows submitting that link again.
Search uses a transparent input with no enclosing panel, centered at 65% of the
main workspace width. Downloads uses centered tables at 94%, split into
**In progress** and **Downloaded**, with name, separate type and format columns, quality,
source (**Link** or **Torrent**), size, progress, speed, Added and Downloaded.
Quality shows the actual output resolution or audio bitrate, with sample rate and
bit depth for lossless audio when available. Unknown quality and dates in older
history appear as a dash. Dates use local time in DD.MM.YY form, without a time;
Downloaded is set only after
successful completion. Smaller windows use more
of the available width, with horizontal table scrolling when necessary.
Right-click a row for **Pause**, **Resume**, **Stop**, **Retry**, **Open file** or **Show in folder**,
as applicable; the keyboard menu key and Shift+F10 also work. Click a row to select
only it, or Ctrl-click to add or remove rows from the highlighted selection.
Double-click a downloaded row to open its file in the default app for its format;
entries with several files offer a file picker menu. Right-click a selected row
to delete the selection together, or press the Delete key to open the same dialog.
Escape clears selection. **Delete…** offers entry only, file only, or both.
Choosing a file-deletion option sends the files to **Shred**, where they accumulate
without changing the files on disk. Active jobs must be stopped first. Keeping
the download entry shows **In Shred** until the files are shredded, then **File deleted**.
Removing files from the Shred list keeps them on disk and clears the pending status.
Speed and ETA have separate columns. Hover over Source to see the original link
or torrent seed/peer counts and health. History survives restarting; unfinished
transfers restart automatically, while manually paused or stopped jobs stay inactive.
Unavailable options produce an error.
This rebuild accepts individual video/live-stream URLs, torrent magnets, local
`.torrent` files and HTTP(S) torrent-file links. Playlist-only URLs and keyword
search remain future work.

### Torrents

Paste a magnet or drop one or several `.torrent` files into Search, then click
**Inspect** or press Enter to fetch metadata. Adding a torrent does not start
inspection or show a pending preview. Video links and torrents can
share a batch; adding torrents preserves existing selections and inspections.
Local paths containing spaces are accepted. Magnet inspection fetches metadata
without downloading the payload; it times out after three minutes if no peers
provide metadata. Torrent metadata is cached under the application profile.

The preview expands to show the torrent's folder/file tree and sizes without an
internal scrollbar. The first checkbox selects or deselects everything; individual
file and folder checkboxes refine the selection. Padding
files are hidden. Click Download to transfer only the selected files to Downloads;
the preview and its input source then disappear from Search. Torrent contents keep
their original folder layout under the download folder selected in Settings.

Torrents use the same two-job queue and progress, speed and date columns as video
downloads. Type and Source say Torrent; Format and Quality show a dash. Pause, Stop
and normal app closure save resume data and keep partial files. After a restart,
unfinished transfers resume automatically unless manually paused or stopped. Selected files define progress and
completion; deselected files may require small boundary-piece data in an internal
part file. Peer sharing is allowed during download, then stopped at completion.
There is no seeding section, and qBittorrent is not required.

Only one Downloads entry is created per torrent, even when it is supplied through
different magnets or torrent files. Existing previews offer Open in Downloads.
Pause or stop an active torrent before using Choose files… in its context menu;
Download selected reuses that entry and its destination to fetch additional files.
Files already downloaded are retained when deselected. Open file and Show in
folder use recorded outputs; deletion only recycles this entry's files and leaves
unrelated files in the same folder untouched. Unsafe paths and unsupported torrent
symbolic links are rejected.

### Live streams

Paste a live-stream URL into the same input and inspect it. Detected live streams
show **LIVE** and a **Record** action, with video or audio choices. Live video
supports MP4/MKV/WebM; audio supports MP3/M4A/FLAC/WAV/OGG. Transcripts can be
exported once the broadcast is available as a regular video.
Clicking **Record** also moves the result from Search to Downloads.
In Downloads, a recording shows elapsed time and the growing file size.
Right-click **Stop** to finalize and save it in the Downloaded group. Closing
the app also requests a graceful recording stop. A forced interruption preserves
the `.part` recording; MP4/M4A use fragmented output so recorded fragments remain
recoverable. Finished MP4/M4A recordings are remuxed without re-encoding into
conventional indexed files. Live video uses keyframes approximately every two
seconds for seeking. Finalization failures retain the partial capture.
Retrying a live stream starts a new capture with a new filename.
Regular downloads retain partial files during Pause/Stop and continue on Resume
when the source supports byte-range requests. Paused jobs remain paused after
restarting the app. Live recording offers Stop rather than Pause because a live
broadcast cannot wait while recording is paused.

The previous full app remains available with `python -m kazaa --legacy` and its
original dependencies. Its existing capabilities are documented below.

Focused shell checks: `.\.venv\Scripts\python.exe tools/test_shell.py`.
Focused video checks: `.\.venv\Scripts\python.exe tools/test_video_workflow.py`.
Theme previews: `.\.venv\Scripts\python.exe tools/preview_shell.py`.

Create or repair the KaZaA desktop and Start menu shortcuts:
`powershell -ExecutionPolicy Bypass -File tools/install_shortcut.ps1`.
The script creates a small Windows launcher with KaZaA product metadata, registers
the exact Windows display name **KaZaA**, and refreshes matching Search-index entries.
The desktop launcher is inside the Desktop's KaZaA folder; the Start Menu launcher
is inside KaZaA Desktop. These fresh paths avoid stale capitalization cached for
the original shortcut locations. Replaced shortcuts
belonging to this checkout are backed up under `tools/out/shortcuts/`; separate
legacy installations are preserved.

If Codex holds the project folder open during a capitalization change, close
Codex and KaZaA, then run `powershell -ExecutionPolicy Bypass -File
"C:\Users\valer\Projects 2027\KaZaA\tools\finalize_folder_name.ps1"`.
The helper updates the folder spelling to `KaZaA` and repairs both shortcuts.

**A modern, dark-themed video downloader, converter & screen recorder for Windows —
built entirely on open-source components (yt-dlp + ffmpeg + PySide6).**

KaZaA v2. revival is a clean-room desktop application in the "video downloader converter"
category: paste a link, get the video; convert, trim, merge or record when you
need more. No accounts, no ads, no telemetry, no license checks.

![Platform](https://img.shields.io/badge/platform-Windows-7c6cff)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## Previous app features (`--legacy`)

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

### Torrents
- **Paste a magnet link or .torrent file** — local files and http(s) links
  both work; torrents land in the same queue as video downloads, with the
  same pause / stop / resume controls
- **libtorrent engine** — the same BitTorrent core qBittorrent is built on
  (DHT, peer exchange, sequential download)
- **Sequential by default** — pieces arrive in order, so a downloading video
  is already playable (qBittorrent's "download in sequential order")
- **Pause keeps your progress** — stopping a torrent never discards finished
  pieces; resume re-checks the data and continues where it left off
- **Live stats** — download speed and peer count in the activity row

### Music search
- **Search bar for YouTube music** — type an artist, song or lyrics; results
  come back as a clean list (title, channel, length — no clutter)
- **20-second preview** — hear a song before downloading; streamed via the
  audio track only (no video), played in-app, one click to stop
- **One-click mp3** — the Download button saves the audio track as a tagged
  320 kbps-quality mp3 (title + artist written into the file), and the
  temporary intermediate is removed automatically

### Live streams
- **Record live streams** — paste a live page URL (e.g. a webcam room) and
  KaZaA v2. revival records it while it plays, with both video and audio
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

KaZaA v2. revival needs an `ffmpeg.exe` / `ffprobe.exe` build. Either:

- drop a static build into `bin/` (e.g. the "essentials" build from
  https://www.gyan.dev/ffmpeg/builds/), or
- make sure `ffmpeg` is on your `PATH`.

`bin/` is intentionally not committed (binaries exceed GitHub's file-size limit).

### Run

```
kazaa.bat                                # GUI
python -m kazaa --legacy --url "https://..."      # previous app: download on launch
python -m kazaa --legacy --url "..." --quality 720 --exit force
python -m kazaa --legacy --install-plugins        # browser extension instructions
```

The release is **2.0.0**. Existing settings, history, and live-recording recovery
data are copied to `%APPDATA%\KaZaA` on first launch; the original data is kept.
New downloads and screen recordings default to `%USERPROFILE%\Videos\KaZaA`.

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
kazaa/
  __main__.py        CLI entry (GUI or headless download)
  settings.py        JSON-backed persistent settings (%APPDATA%\KaZaA)
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
