"""Entry point: GUI or headless CLI."""
import argparse
import sys


def _redirect_stderr():
    """Windowed apps have no console; capture tracebacks in a log file."""
    import os
    try:
        from .settings import config_dir
        d = config_dir()
        f = open(os.path.join(d, "stderr.log"), "a", encoding="utf-8")
        sys.stderr = f
        sys.stdout = f
    except OSError:
        pass


def legacy_main(argv=None):
    _redirect_stderr()
    p = argparse.ArgumentParser(prog="kazaa",
                                description="KazaA v2. revival - video downloader/converter")
    p.add_argument("--url", action="append", help="URL to download (repeatable)")
    p.add_argument("--quality", help="e.g. 720, 1080, best, worst")
    p.add_argument("--output-dir", help="override download directory")
    p.add_argument("--convert-to", help="auto-convert to format (mp4, mp3, ...)")
    p.add_argument("--subtitles", choices=["md", "srt", "vtt"],
                   help="also download the video transcript in this format")
    p.add_argument("--sub-langs", default="en",
                   help="comma-separated transcript languages (default: en)")
    p.add_argument("--sub-auto", action="store_true", default=True,
                   help="include auto-generated captions (default)")
    p.add_argument("--no-sub-auto", dest="sub_auto", action="store_false",
                   help="manual captions only")
    p.add_argument("--transcript-only", action="store_true",
                   help="download only the transcript, skip the video "
                        "(requires --subtitles)")
    p.add_argument("--exit", nargs="?", const="prompt", choices=["prompt", "force"],
                   help="exit after finishing ('force' = no prompt)")
    p.add_argument("--install-plugins", action="store_true",
                   help="print browser extension install instructions")
    p.add_argument("--uninstall-plugins", action="store_true",
                   help="print browser extension uninstall instructions")
    p.add_argument("--version", action="store_true")
    args = p.parse_args(argv)

    if args.version:
        from . import VERSION
        print(f"KazaA v2. revival {VERSION}")
        return 0

    if args.install_plugins or args.uninstall_plugins:
        return _plugin_instructions(install=args.install_plugins)

    from PySide6.QtWidgets import QApplication
    from .ui import theme
    from .ui.main_window import MainWindow

    app = QApplication(sys.argv[:1])
    theme.apply(app)
    win = MainWindow()

    # Repair live captures orphaned by a crash/kill during recording.
    from PySide6.QtCore import QTimer
    from .downloader import recover_interrupted_live
    import os as _os

    def _sweep_interrupted():
        recovered = recover_interrupted_live()
        if recovered:
            names = ", ".join(_os.path.basename(p) for p in recovered)
            win.statusBar().showMessage(
                f"Recovered interrupted live recording(s): {names}", 20000)

    QTimer.singleShot(300, _sweep_interrupted)

    if args.output_dir:
        win.settings.set("save_to", args.output_dir)
    if args.url:
        win.set_page(1)
        subtitles = None
        if args.subtitles:
            subtitles = {"format": args.subtitles,
                         "langs": [l.strip() for l in args.sub_langs.split(",")
                                   if l.strip()] or ["en"],
                         "auto": args.sub_auto}
        for url in args.url:
            tid = win.downloads.submit(
                url, quality=args.quality, subtitles=subtitles,
                transcript_only=args.transcript_only)
            if tid:
                win.activity.add_task(tid, url)
        if args.convert_to:
            win._auto_conv_fmt = args.convert_to
            win._auto_conv_q = "normal"
    if args.exit == "force":
        win.settings.set("after_done", "exit")
    elif args.exit == "prompt":
        win._exit_prompt = True  # handled by after-done 'exit' action if set
    if not args.url:
        win.show()
    return app.exec()


def _plugin_instructions(install=True):
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    what = "Install" if install else "Uninstall"
    print(f"{what} browser extensions:")
    print(f"  Chrome : open chrome://extensions, enable Developer mode, "
          f"then 'Load unpacked' -> {root}\\extensions\\chrome"
          if install else
          f"  Chrome : open chrome://extensions and remove 'KazaA v2. revival Helper'")
    print(f"  Firefox: open about:debugging#/runtime/this-firefox, "
          f"'Load Temporary Add-on' -> {root}\\extensions\\firefox\\manifest.json"
          if install else
          f"  Firefox: open about:addons and remove 'KazaA v2. revival Helper'")
    return 0


def main(argv=None):
    from . import VERSION
    parser = argparse.ArgumentParser(prog="kazaa", description="KazaA v2. revival — local desktop workspace")
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--legacy", action="store_true", help="open the previous full application")
    args, remaining = parser.parse_known_args(argv)
    if args.version:
        print(f"KazaA v2. revival {VERSION}")
        return 0
    if args.legacy:
        return legacy_main(remaining)
    if remaining:
        parser.error("media CLI options belong to the previous app; use --legacy before those options")
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication
    from .ui.shell import ShellWindow
    app = QApplication(sys.argv[:1])
    app.setApplicationName("KazaA")
    app.setOrganizationName("KazaA")
    app.setFont(QFont("Segoe UI", 10))
    window = ShellWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
