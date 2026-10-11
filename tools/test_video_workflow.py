"""Focused offline checks for inspection, export selection and the video UI/queue."""
import json
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import QApplication
from kazaa import transcripts, video_backend as backend
from kazaa.video_jobs import Inspector, VideoQueue
from kazaa.ui.shell import ShellWindow


def media(url="https://example.com/video"):
    return {"url": url, "title": "Example video", "has_video": True, "has_audio": True,
            "heights": [360, 720], "creator": "Example", "duration": 12,
            "captions": {"manual": {"en": "English"}, "automatic": {"es": "Spanish"}}}


class FakeWorker(QObject):
    progress = Signal(dict)
    result = Signal(dict)
    error = Signal(str)
    finished = Signal()
    created = []

    def __init__(self, request, parent=None):
        super().__init__(parent)
        self.request = request
        self.cancelled = False
        self.started = False
        self.created.append(self)

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def succeed(self, data):
        self.result.emit(data)
        self.finished.emit()

    def fail(self, message):
        self.error.emit(message)
        self.finished.emit()


class VideoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.queue = VideoQueue(self.root / "downloads.json", worker_factory=FakeWorker)
        FakeWorker.created = []
        self.options = backend.DownloadOptions(folder=str(self.root))
        self.tool_patch = patch("kazaa.video_backend.find_ffmpeg", return_value="ffmpeg")
        self.tool_patch.start()

    def tearDown(self):
        self.queue.stop()
        for worker in list(self.queue.workers.values()):
            worker.fail("Cancelled")
        self.app.processEvents()
        self.tool_patch.stop()
        self.temporary.cleanup()

    def test_input_normalizes_video_and_deduplicates_without_expanding_playlist(self):
        entries = backend.parse_links("https://youtube.com/watch?v=abc&list=xyz\nhttps://www.youtube.com/watch?v=abc\nhttps://example.com/video#part")
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["url"], "https://www.youtube.com/watch?v=abc")
        self.assertEqual(entries[0]["error"], "")

    def test_worker_uses_utf8_for_titles_on_windows_pipes(self):
        from kazaa import video_worker
        incoming = io.TextIOWrapper(io.BytesIO(b'{"action":"inspect","url":"https://example.com/video"}'), encoding="cp1252")
        output_bytes = io.BytesIO()
        outgoing = io.TextIOWrapper(output_bytes, encoding="cp1252")
        errors = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        title = "Музыка 日本語"
        with patch.object(video_worker.sys, "stdin", incoming), patch.object(video_worker.sys, "stdout", outgoing), patch.object(video_worker.sys, "stderr", errors), patch.object(video_worker, "inspect_video", return_value={"title": title}):
            code = video_worker.main()
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output_bytes.getvalue().decode("utf-8"))["data"]["title"], title)
    def test_bad_and_torrent_inputs_do_not_block_valid_links(self):
        entries = backend.parse_links("magnet:?xt=abc\nhttps://example.com/a.torrent\ninvalid\nhttps://example.com/video")
        self.assertEqual(sum(not item["error"] for item in entries), 1)
        self.assertIn("planned", entries[0]["error"])
        self.assertIn("planned", entries[1]["error"])
        self.assertNotIn("kazaa.torrent", sys.modules)

    def test_playlist_and_live_sources_are_explicitly_rejected(self):
        with self.assertRaises(ValueError):
            backend.validate_url("https://youtube.com/playlist?list=abc")
        with self.assertRaises(ValueError):
            backend.summarize({"_type": "playlist"}, "https://example.com")
        with self.assertRaises(ValueError):
            backend.summarize({"is_live": True}, "https://example.com")

    def test_unavailable_resolution_and_caption_source_are_not_silently_changed(self):
        with self.assertRaisesRegex(ValueError, "1080p"):
            backend.DownloadOptions(quality="1080", folder=str(self.root)).validate(media())
        with self.assertRaisesRegex(ValueError, "caption"):
            backend.DownloadOptions(kind="transcript", format="txt", language="es", folder=str(self.root)).validate(media())
        backend.DownloadOptions(kind="transcript", format="txt", language="es", caption_source="automatic", folder=str(self.root)).validate(media())

    def test_format_quality_and_caption_only_options(self):
        audio = backend.export_options(backend.DownloadOptions(kind="audio", format="mp3", quality="192", folder=str(self.root)), "test")
        self.assertEqual(audio["format"], "bestaudio/best")
        self.assertEqual(audio["postprocessors"][0]["preferredquality"], "192")
        ogg = backend.export_options(backend.DownloadOptions(kind="audio", format="ogg", folder=str(self.root)), "test")
        self.assertEqual(ogg["postprocessors"][0]["preferredcodec"], "vorbis")
        video = backend.export_options(backend.DownloadOptions(quality="720", folder=str(self.root)), "test")
        self.assertNotIn("bestvideo*", video["format"])
        captions = backend.export_options(backend.DownloadOptions(kind="transcript", format="txt", folder=str(self.root)), "test")
        self.assertTrue(captions["skip_download"])
        self.assertTrue(captions["writesubtitles"])
        self.assertFalse(captions["writeautomaticsub"])

    def test_plain_text_transcript_export_preserves_words_without_timing(self):
        source = self.root / "captions.vtt"
        source.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHello &amp; <c>world</c>\n", encoding="utf-8")
        output = transcripts.convert(str(source), "txt")
        self.assertEqual(Path(output).read_text(), "Hello & world\n")
        self.assertTrue(source.exists())

    def test_queue_is_bounded_and_keeps_captured_options(self):
        first = self.queue.submit(media(), self.options)
        second = self.queue.submit(media("https://example.com/2"), self.options)
        third = self.queue.submit(media("https://example.com/3"), self.options)
        self.assertEqual(len(self.queue.workers), 2)
        self.assertEqual(self.queue.jobs[third]["status"], "queued")
        self.queue.set_options({"kind": "audio", "format": "mp3"})
        self.assertEqual(self.queue.jobs[first]["options"]["kind"], "video")
        self.queue.workers[first].fail("Site unavailable")
        self.assertEqual(self.queue.jobs[first]["status"], "failed")
        self.assertEqual(self.queue.jobs[second]["status"], "starting")
        self.assertIn(third, self.queue.workers)

    def test_duplicate_active_download_is_rejected(self):
        self.queue.submit(media(), self.options)
        with self.assertRaisesRegex(ValueError, "already"):
            self.queue.submit(media(), self.options)

    def test_cancel_then_retry_retains_same_job_and_settings(self):
        job_id = self.queue.submit(media(), self.options)
        worker = self.queue.workers[job_id]
        self.queue.cancel(job_id)
        self.assertTrue(worker.cancelled)
        worker.progress.emit({"status": "downloading", "percent": 50})
        self.assertEqual(self.queue.jobs[job_id]["status"], "cancelling")
        worker.fail("Cancelled")
        self.assertEqual(self.queue.jobs[job_id]["status"], "cancelled")
        self.queue.retry(job_id)
        self.assertEqual(self.queue.jobs[job_id]["status"], "starting")
        self.assertEqual(self.queue.workers[job_id].request["options"], self.options.to_dict())

    def test_completed_files_and_interrupted_jobs_survive_restart(self):
        completed = self.queue.submit(media(), self.options)
        output = self.root / "video.mp4"
        output.write_bytes(b"test output")
        self.queue.workers[completed].succeed({"files": [str(output)], "size": output.stat().st_size})
        active = self.queue.submit(media("https://example.com/2"), self.options)
        restored = VideoQueue(self.queue.path, worker_factory=FakeWorker)
        self.assertEqual(restored.jobs[completed]["status"], "completed")
        self.assertEqual(restored.jobs[active]["status"], "interrupted")
        self.assertEqual(restored.workers, {})

    def test_missing_output_is_failed_instead_of_completed(self):
        job_id = self.queue.submit(media(), self.options)
        self.queue.workers[job_id].succeed({"files": []})
        self.assertEqual(self.queue.jobs[job_id]["status"], "failed")

    def test_old_inspection_results_cannot_replace_a_new_batch(self):
        inspector = Inspector(worker_factory=FakeWorker)
        results = []
        inspector.item_ready.connect(lambda *data: results.append(data))
        inspector.inspect(["https://example.com/old"])
        old = FakeWorker.created[-1]
        inspector.inspect(["https://example.com/new"])
        new = FakeWorker.created[-1]
        self.assertTrue(old.cancelled)
        old.succeed(media("https://example.com/old"))
        new.succeed(media("https://example.com/new"))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][1], "https://example.com/new")

    def test_search_batch_queues_valid_items_and_shows_unavailable_options(self):
        window = ShellWindow(self.root / "shell.json")
        window.download_queue.worker_factory = FakeWorker
        page = window.search_page
        page.inspector.worker_factory = FakeWorker
        window.appearance.folder.setText(str(self.root))
        window.appearance._save_folder()
        window.show()
        page.input.setPlainText("https://example.com/one\nhttps://example.com/two\nmagnet:?xt=x")
        page.inspect()
        for worker in list(page.inspector.workers):
            info = media(worker.request["url"])
            if info["url"].endswith("two"):
                info["heights"] = [360]
            worker.succeed(info)
        first = page.cards["https://example.com/one"].options_panel
        second = page.cards["https://example.com/two"].options_panel
        first.quality.setCurrentIndex(first.quality.findData("720"))
        second.kind.setCurrentIndex(second.kind.findData("transcript"))
        second.caption_source.setCurrentIndex(second.caption_source.findData("automatic"))
        page.cards["https://example.com/two"].info["captions"]["automatic"] = {}
        page._download_selected()
        self.assertEqual(len(window.download_queue.jobs), 1)
        self.assertIn("caption", page.cards["https://example.com/two"].status.text())
        self.assertIn("planned", page.cards["magnet:?xt=x"].status.text())
        self.assertEqual(window.downloaded_page.active_table.rowCount(), 1)
        for worker in list(window.download_queue.workers.values()):
            worker.fail("Cancelled")
        window.close()
        self.app.processEvents()

    def test_each_result_keeps_its_own_type_and_quality_without_caption_sidecars(self):
        from kazaa.ui.video_pages import SearchPage, VideoCard
        page = SearchPage(self.queue)
        for url in ("https://example.com/one", "https://example.com/two"):
            card = VideoCard(url, self.queue)
            card.set_result(media(url))
            page.cards[url] = card
            page.cards_layout.addWidget(card)
        first, second = list(page.cards.values())
        first.options_panel.quality.setCurrentIndex(first.options_panel.quality.findData("720"))
        second.options_panel.kind.setCurrentIndex(second.options_panel.kind.findData("audio"))
        second.options_panel.format.setCurrentIndex(second.options_panel.format.findData("mp3"))
        second.options_panel.quality.setCurrentIndex(second.options_panel.quality.findData("192"))
        page._download_selected()
        jobs = list(self.queue.jobs.values())
        self.assertEqual([(j["options"]["kind"], j["options"]["quality"]) for j in jobs], [("video", "720"), ("audio", "192")])
        self.assertTrue(all(j["options"]["captions"] is False for j in jobs))
        self.assertEqual(first.options_panel.quality.currentData(), "720")
        self.assertTrue(second.options_panel.caption_fields.isHidden())
        second.options_panel.kind.setCurrentIndex(second.options_panel.kind.findData("transcript"))
        self.assertFalse(second.options_panel.caption_fields.isHidden())
        self.assertTrue(second.options_panel.quality.isHidden())
        page.deleteLater()

    def test_folder_settings_persist_and_only_affect_new_downloads(self):
        window = ShellWindow(self.root / "shell.json")
        queue = window.download_queue
        queue.worker_factory = FakeWorker
        queue.set_options({"folder": str(self.root / "first")})
        first = queue.submit(media(), backend.DownloadOptions(folder=str(self.root / "first")))
        window.appearance.folder.setText(str(self.root / "next"))
        window.appearance._save_folder()
        with patch("kazaa.ui.shell.QFileDialog.getExistingDirectory", return_value=str(self.root / "next")):
            window.appearance._browse_folder()
        from kazaa.ui.video_pages import ResultOptions
        options = ResultOptions(queue)
        options.set_info(media())
        second = queue.submit(media("https://example.com/next"), options.options())
        self.assertEqual(queue.jobs[first]["options"]["folder"], str(self.root / "first"))
        self.assertEqual(queue.jobs[second]["options"]["folder"], str(self.root / "next"))
        restored = VideoQueue(queue.path, worker_factory=FakeWorker)
        self.assertEqual(restored.options["folder"], str(self.root / "next"))
        for worker in list(queue.workers.values()):
            worker.fail("Cancelled")
        window.close()

    def test_table_updates_size_progress_and_moves_completed_rows(self):
        from kazaa.ui.video_pages import DownloadedPage
        page = DownloadedPage(self.queue)
        job_id = self.queue.submit(media(), self.options)
        worker = self.queue.workers[job_id]
        worker.progress.emit({"status": "downloading", "percent": 50, "total_bytes": 2048, "downloaded_bytes": 1024})
        self.assertEqual(page.active_table.rowCount(), 1)
        self.assertEqual(page.active_table.item(0, 1).text(), "Video · MP4")
        self.assertEqual(page.active_table.item(0, 3).text(), "Link")
        self.assertEqual(page.active_table.item(0, 4).text(), "2.0 KB")
        self.assertEqual(page.active_table.cellWidget(0, 5).bar.value(), 50)
        output = self.root / "video.mp4"
        output.write_bytes(b"done")
        worker.succeed({"files": [str(output)], "size": 4})
        self.assertEqual(page.active_table.rowCount(), 0)
        self.assertEqual(page.completed_table.rowCount(), 1)
        self.assertEqual(page.completed_table.item(0, 4).text(), "4 B")
        page.deleteLater()

    def test_table_context_actions_and_keyboard_menu(self):
        from kazaa.ui.video_pages import DownloadedPage
        page = DownloadedPage(self.queue)
        job_id = self.queue.submit(media(), self.options)
        worker = self.queue.workers[job_id]
        page.context_menu(job_id).actions()[0].trigger()
        self.assertTrue(worker.cancelled)
        worker.fail("Cancelled")
        self.assertEqual(page.context_menu(job_id).actions()[0].text(), "Retry")
        page.context_menu(job_id).actions()[0].trigger()
        output = self.root / "video.mp4"
        output.write_bytes(b"done")
        self.queue.workers[job_id].succeed({"files": [str(output)], "size": 4})
        menu = page.context_menu(job_id)
        self.assertEqual([a.text() for a in menu.actions()], ["Open file", "Show in folder"])
        with patch("kazaa.ui.video_pages.QDesktopServices.openUrl") as opened:
            menu.actions()[0].trigger()
            self.assertEqual(opened.call_args[0][0].toLocalFile(), str(output).replace("\\", "/"))
            menu.actions()[1].trigger()
            self.assertEqual(opened.call_args[0][0].toLocalFile(), str(self.root).replace("\\", "/"))
        page.completed_table.menu_requested.disconnect()
        events = []
        page.completed_table.menu_requested.connect(lambda job_id, position: events.append(job_id))
        page.completed_table.selectRow(0)
        QTest.keyClick(page.completed_table, Qt.Key_F10, Qt.ShiftModifier)
        self.assertEqual(events, [job_id])
        position = page.completed_table.visualItemRect(page.completed_table.item(0, 0)).center()
        self.app.sendEvent(page.completed_table.viewport(), QContextMenuEvent(QContextMenuEvent.Mouse, position, page.completed_table.viewport().mapToGlobal(position)))
        self.assertEqual(events, [job_id, job_id])
        page.deleteLater()


if __name__ == "__main__":
    unittest.main()
