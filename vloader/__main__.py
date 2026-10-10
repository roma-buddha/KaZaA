"""Entry point: GUI or headless CLI."""
import argparse
import sys


def main(argv=None):
    p = argparse.ArgumentParser(prog="vloader",
                                description="VLoader - video downloader/converter")
    p.add_argument("--url", action="append", help="URL to download (repeatable)")
    p.add_argument("--quality", help="e.g. 720, 1080, best, worst")
    p.add_argument("--output-dir", help="override download directory")
    p.add_argument("--convert-to", help="auto-convert to format (mp4, mp3, ...)")
    p.add_argument("--exit", nargs="?", const="prompt", choices=["prompt", "force"],
                   help="exit after finishing ('force' = no prompt)")
    p.add_argument("--install-plugins", action="store_true",
                   help="print browser extension install instructions")
    p.add_argument("--uninstall-plugins", action="store_true",
                   help="print browser extension uninstall instructions")
    p.add_argument("--version", action="store_true")
    args = p.parse_args(argv)

    if args.version:
        from .ui.main_window import VERSION
        print(f"VLoader {VERSION}")
        return 0

    if args.install_plugins or args.uninstall_plugins:
        return _plugin_instructions(install=args.install_plugins)

    from PySide6.QtWidgets import QApplication
    from .ui import theme
    from .ui.main_window import MainWindow

    app = QApplication(sys.argv[:1])
    theme.apply(app)
    win = MainWindow()
    if args.output_dir:
        win.settings.set("save_to", args.output_dir)
    if args.url:
        win.tabs.setCurrentIndex(1)
        for url in args.url:
            tid = win.downloads.submit(url, quality=args.quality)
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
    root = __file__.rsplit("\\vloader\\", 1)[0]
    what = "Install" if install else "Uninstall"
    print(f"{what} browser extensions:")
    print(f"  Chrome : open chrome://extensions, enable Developer mode, "
          f"then 'Load unpacked' -> {root}\\extensions\\chrome"
          if install else
          f"  Chrome : open chrome://extensions and remove 'VLoader Helper'")
    print(f"  Firefox: open about:debugging#/runtime/this-firefox, "
          f"'Load Temporary Add-on' -> {root}\\extensions\\firefox\\manifest.json"
          if install else
          f"  Firefox: open about:addons and remove 'VLoader Helper'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
