"""Screen recorder: ffmpeg gdigrab capture, region or fullscreen, MP4 output."""
import os
import subprocess
import sys
import threading

from PySide6.QtCore import QObject, Signal

from .downloader import find_ffmpeg

MOD_NOREPEAT = 0x4000
HOTKEY_F9 = 1
HOTKEY_F10 = 2
VK_F9, VK_F10 = 0x78, 0x79
WM_HOTKEY = 0x0312


def _install_hotkeys(on_f9, on_f10):
    """Register F9/F10 as global hotkeys; runs a message loop in this thread."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    ok9 = user32.RegisterHotKey(None, HOTKEY_F9, MOD_NOREPEAT, VK_F9)
    ok10 = user32.RegisterHotKey(None, HOTKEY_F10, MOD_NOREPEAT, VK_F10)
    if not (ok9 or ok10):
        return  # hotkeys unavailable (non-Windows / denied) - UI buttons still work

    class MSG(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                    ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
                    ("time", wintypes.DWORD), ("pt", wintypes.POINT)]

    msg = MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
        if msg.message == WM_HOTKEY:
            if msg.wParam == HOTKEY_F9:
                on_f9()
            elif msg.wParam == HOTKEY_F10:
                on_f10()
    user32.UnregisterHotKey(None, HOTKEY_F9)
    user32.UnregisterHotKey(None, HOTKEY_F10)


class Recorder(QObject):
    """Records a screen region (or full screen) to MP4 via ffmpeg gdigrab."""
    state_changed = Signal(str)   # idle | recording | paused-stopped
    finished = Signal(str)        # output path

    def __init__(self, parent=None):
        super().__init__(parent)
        self.proc = None
        self.output = ""
        self._hotkey_thread = None
        self._hotkey_stop = None

    def start(self, rect=None, with_audio=True, framerate=30, out_path=None):
        """rect: (x, y, w, h) or None for full virtual screen."""
        if self.proc:
            return False
        if not out_path:
            import time
            stamp = time.strftime("%Y%m%d_%H%M%S")
            out_path = os.path.join(os.path.expanduser("~"), "Videos",
                                    "VLoader", f"record_{stamp}.mp4")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        ffmpeg = find_ffmpeg() or "ffmpeg"
        args = [ffmpeg, "-y", "-nostdin", "-hide_banner",
                "-f", "gdigrab", "-framerate", str(framerate)]
        if rect:
            x, y, w, h = rect
            args += ["-offset_x", str(x), "-offset_y", str(y),
                     "-video_size", f"{w}x{h}"]
        args += ["-i", "desktop"]
        if with_audio:
            args += ["-f", "dshow", "-i", "audio=virtual-audio-capturer"]
        args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                 "-pix_fmt", "yuv420p", out_path]
        try:
            self.proc = subprocess.Popen(
                args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError:
            self.proc = None
            return False
        self.output = out_path
        self.state_changed.emit("recording")
        return True

    def stop(self):
        """Stop and finalize. ffmpeg gdigrab has no real pause; stop = finish."""
        if not self.proc:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.proc = None
        self.state_changed.emit("idle")
        if os.path.exists(self.output):
            self.finished.emit(self.output)

    @property
    def is_recording(self):
        return self.proc is not None

    def start_hotkeys(self, on_toggle, on_stop):
        if sys.platform != "win32":
            return
        self._hotkey_thread = threading.Thread(
            target=_install_hotkeys, args=(on_toggle, on_stop), daemon=True)
        self._hotkey_thread.start()
