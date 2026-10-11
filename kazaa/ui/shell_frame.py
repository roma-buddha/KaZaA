"""Native Windows movement, resizing and snapping for the integrated header."""
import sys

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QMainWindow, QPushButton

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class MINMAXINFO(ctypes.Structure):
        _fields_ = [(name, wintypes.POINT) for name in
                    ("reserved", "max_size", "max_position", "min_track", "max_track")]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                    ("work", wintypes.RECT), ("flags", wintypes.DWORD)]

    user32 = ctypes.windll.user32
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.IsZoomed.argtypes = [wintypes.HWND]
    user32.GetDpiForWindow.argtypes = [wintypes.HWND]
    user32.GetSystemMetricsForDpi.argtypes = [ctypes.c_int, wintypes.UINT]
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = wintypes.HMONITOR
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]


class ShellFrame(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowFlag(Qt.FramelessWindowHint)
        self.topbar = None

    def initialize_frame(self):
        if sys.platform != "win32" or QGuiApplication.platformName() != "windows":
            return
        hwnd = int(self.winId())
        # Retain the standard window actions while drawing the caption ourselves.
        style = user32.GetWindowLongW(hwnd, -16)
        user32.SetWindowLongW(hwnd, -16, style | 0x00CF0000)
        user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0027)

    def _frame_hit_test(self, point, width, height, edge):
        if not self.isMaximized():
            left, right = point.x() < edge, point.x() >= width - edge
            top, bottom = point.y() < edge, point.y() >= height - edge
            if top:
                return 13 if left else 14 if right else 12
            if bottom:
                return 16 if left else 17 if right else 15
            if left or right:
                return 10 if left else 11
        if self.topbar and point.y() < self.topbar.height():
            child = self.childAt(point)
            if child is getattr(self, "maximize_button", None):
                return 9  # HTMAXBUTTON enables Windows 11's Snap Layouts menu.
            if not isinstance(child, QPushButton):
                return 2  # HTCAPTION: native dragging and double-click maximize.
        return 1

    def nativeEvent(self, event_type, message):
        if sys.platform != "win32" or QGuiApplication.platformName() != "windows":
            return super().nativeEvent(event_type, message)
        msg = wintypes.MSG.from_address(int(message))
        if msg.message == 0x0083 and msg.wParam:  # WM_NCCALCSIZE: no system caption.
            if user32.IsZoomed(msg.hWnd):
                # The native thick frame extends beyond the work area when maximized.
                # Keep that invisible frame out of our client area and header.
                rect = wintypes.RECT.from_address(msg.lParam)
                dpi = user32.GetDpiForWindow(msg.hWnd)
                inset = (user32.GetSystemMetricsForDpi(32, dpi) +
                         user32.GetSystemMetricsForDpi(92, dpi))
                rect.left += inset
                rect.top += inset
                rect.right -= inset
                rect.bottom -= inset
            return True, 0
        if msg.message == 0x0024:  # WM_GETMINMAXINFO: maximize within the work area.
            monitor = MONITORINFO()
            monitor.size = ctypes.sizeof(monitor)
            handle = user32.MonitorFromWindow(msg.hWnd, 2)
            if user32.GetMonitorInfoW(handle, ctypes.byref(monitor)):
                info = MINMAXINFO.from_address(msg.lParam)
                info.max_position.x = monitor.work.left - monitor.monitor.left
                info.max_position.y = monitor.work.top - monitor.monitor.top
                info.max_size.x = monitor.work.right - monitor.work.left
                info.max_size.y = monitor.work.bottom - monitor.work.top
                scale = self.devicePixelRatioF()
                info.min_track.x = round(self.minimumWidth() * scale)
                info.min_track.y = round(self.minimumHeight() * scale)
                return True, 0
        if msg.message == 0x0084:  # WM_NCHITTEST: native screen coordinates are pixels.
            native_point = wintypes.POINT(ctypes.c_short(msg.lParam & 0xffff).value,
                                         ctypes.c_short((msg.lParam >> 16) & 0xffff).value)
            if user32.ScreenToClient(msg.hWnd, ctypes.byref(native_point)):
                scale = self.devicePixelRatioF()
                point = QPoint(round(native_point.x / scale), round(native_point.y / scale))
                return True, self._frame_hit_test(point, self.width(), self.height(), 6)
        if msg.message in (0x00A1, 0x00A2) and msg.wParam == 9:
            # Windows routes clicks on HTMAXBUTTON as non-client events.
            if msg.message == 0x00A2:
                self.toggle_maximized()
            return True, 0
        return super().nativeEvent(event_type, message)

    def toggle_maximized(self):
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def changeEvent(self, event):
        super().changeEvent(event)
        if hasattr(self, "maximize_button"):
            self.update_window_controls()
