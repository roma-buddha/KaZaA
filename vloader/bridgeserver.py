"""Local HTTP bridge so browser extensions can hand URLs to the app.

Listens on 127.0.0.1:8765. Extensions POST /add?url=<page url>.
CORS is answered so fetch() from content scripts succeeds.
"""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

from PySide6.QtCore import QObject, Signal

HOST, PORT = "127.0.0.1", 8765


class _Handler(BaseHTTPRequestHandler):
    server_version = "VLoaderBridge/1.0"

    def log_message(self, *a):  # keep the console clean
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/add":
            qs = parse_qs(parsed.query)
            url = unquote(qs.get("url", [""])[0])
            if url:
                self.server.bridge.url_received.emit(url)
        self.send_response(200)
        self._cors()
        self.end_headers()
        self.wfile.write(b"ok")

    def do_POST(self):
        self.do_GET()


class Bridge(QObject):
    url_received = Signal(str)


class BridgeServer:
    def __init__(self):
        self.bridge = Bridge()
        self._httpd = None
        self._thread = None

    def start(self):
        if self._httpd:
            return
        try:
            self._httpd = ThreadingHTTPServer((HOST, PORT), _Handler)
        except OSError:
            self._httpd = None  # port taken (another VLoader instance)
            return
        self._httpd.bridge = self.bridge
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        daemon=True)
        self._thread.start()

    def stop(self):
        if self._httpd:
            self._httpd.shutdown()
            self._httpd = None
