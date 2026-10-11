"""Focused offline checks for inspection, export selection and the video UI/queue."""
import json
import io
import os
from datetime import datetime
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QMimeData, QObject, Qt, QUrl, Signal
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
        self.stopped = False
        self.started = False
        self.created.append(self)

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def stop(self):
        self.stopped = True

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

    def test_playlist_is_rejected_and_live_sources_are_identified(self):
        with self.assertRaises(ValueError):
            backend.validate_url("https://youtube.com/playlist?list=abc")
        with self.assertRaises(ValueError):
            backend.summarize({"_type": "playlist"}, "https://example.com")
        info = backend.summarize({"is_live": True, "ext": "mp4"}, "https://example.com")
        self.assertTrue(info["live"])
        backend.DownloadOptions(folder=str(self.root)).validate(info)
        with self.assertRaisesRegex(ValueError, "Live streams"):
            backend.DownloadOptions(kind="transcript", format="txt", folder=str(self.root)).validate(info)

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

    def test_same_link_type_and_format_are_blocked_for_every_status(self):
        job_id = self.queue.submit(media(), self.options)
        self.queue.workers[job_id].fail("Stopped")
        changed = backend.DownloadOptions(quality="720", folder=str(self.root / "other"))
        for status in ("queued", "starting", "downloading", "recording", "processing", "paused", "stopped",
                       "completed", "failed", "cancelled", "interrupted"):
            with self.subTest(status=status):
                self.queue.jobs[job_id]["status"] = status
                with self.assertRaisesRegex(ValueError, "already in Downloads"):
                    self.queue.submit(media(), changed)
                self.assertEqual(len(self.queue.jobs), 1)
                self.assertEqual(self.queue.workers, {})
        self.queue.jobs[job_id]["status"] = "failed"
        self.queue.retry(job_id)
        self.assertEqual(len(self.queue.jobs), 1)
        self.assertIn(job_id, self.queue.workers)

    def test_same_link_allows_different_types_and_formats(self):
        self.queue.submit(media(), self.options)
        for kind, fmt in (("video", "mkv"), ("audio", "mp3"), ("audio", "m4a"),
                          ("transcript", "txt"), ("transcript", "srt")):
            options = backend.DownloadOptions(kind=kind, format=fmt, folder=str(self.root))
            self.queue.submit(media(), options)
            with self.assertRaisesRegex(ValueError, f"{kind.title()} {fmt.upper()}"):
                self.queue.submit(media(), options)
        self.assertEqual(len(self.queue.jobs), 6)

    def test_duplicate_completed_link_is_rejected_after_restart(self):
        job_id, output = self._completed_fixture()
        restored = VideoQueue(self.queue.path, worker_factory=FakeWorker)
        with self.assertRaisesRegex(ValueError, "already in Downloads"):
            restored.submit(media(), self.options)
        self.assertEqual(list(restored.jobs), [job_id])
        self.assertEqual(restored.workers, {})
        self.assertTrue(output.exists())
        audio = backend.DownloadOptions(kind="audio", format="mp3", folder=str(self.root))
        alternate = restored.submit(media(), audio)
        self.assertNotEqual(alternate, job_id)
        restored.stop()
        restored.workers[alternate].fail("Cancelled")

    def test_duplicate_link_normalization_handles_fragments_and_youtube_parameters(self):
        self.queue.submit(media("https://example.com/video#part1"), self.options)
        with self.assertRaisesRegex(ValueError, "already"):
            self.queue.submit(media("https://example.com/video#part2"), self.options)
        youtube = "https://youtube.com/watch?v=abc&list=xyz"
        self.queue.submit(media(youtube), self.options)
        with self.assertRaisesRegex(ValueError, "already"):
            self.queue.submit(media("https://www.youtube.com/watch?v=abc&feature=share"), self.options)
        self.assertEqual(len(self.queue.jobs), 2)

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
        self.assertGreaterEqual(restored.jobs[completed]["completed"], restored.jobs[completed]["created"])
        self.assertNotIn("completed", restored.jobs[active])
        self.assertEqual(restored.jobs[active]["status"], "queued")
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
        self.assertNotIn("https://example.com/one", page.cards)
        self.assertIn("caption", page.cards["https://example.com/two"].status.text())
        self.assertIn("info-hash", page.cards["magnet:?xt=x"].status.text())
        self.assertEqual(page.input.toPlainText(), "https://example.com/two\nmagnet:?xt=x")
        self.assertTrue(page.current_input)
        self.assertTrue(page.cards["https://example.com/two"].download.isEnabled())
        self.assertTrue(page.notice.isHidden())
        self.assertEqual(window.downloaded_page.active_table.rowCount(), 1)
        for worker in list(window.download_queue.workers.values()):
            worker.fail("Cancelled")
        window.close()
        self.app.processEvents()

    def test_new_previews_default_to_video_without_changing_other_selections(self):
        from kazaa.ui.video_pages import VideoCard
        for kind, fmt in (("audio", "mp3"), ("transcript", "txt")):
            self.queue.set_options({"kind": kind, "format": fmt, "folder": str(self.root)})
            card = VideoCard("https://example.com/new", self.queue)
            card.set_result(media(card.url))
            self.assertEqual(card.options_panel.kind.currentData(), "video")
            self.assertEqual(card.options_panel.format.currentData(), "mp4")
            self.assertTrue(card.options_panel.caption_fields.isHidden())
            card.deleteLater()
        first = VideoCard("https://example.com/first", self.queue)
        first.set_result(media(first.url))
        first.options_panel.kind.setCurrentIndex(first.options_panel.kind.findData("audio"))
        second = VideoCard("https://example.com/second", self.queue)
        second.set_result(media(second.url))
        self.assertEqual(first.options_panel.kind.currentData(), "audio")
        self.assertEqual(second.options_panel.kind.currentData(), "video")
        first.deleteLater()
        second.deleteLater()

    def test_input_cleanup_preserves_other_results_and_inspection_generation(self):
        from kazaa.ui.video_pages import SearchPage
        page = SearchPage(self.queue)
        page.inspector.worker_factory = FakeWorker
        page.input.setPlainText("https://youtube.com/watch?v=abc&list=xyz\nhttps://example.com/two")
        page.inspect()
        workers = list(page.inspector.workers)
        workers[0].succeed(media(workers[0].request["url"]))
        generation = page.inspector.generation
        page._download_one("https://www.youtube.com/watch?v=abc")
        self.assertEqual(page.input.toPlainText(), "https://example.com/two")
        self.assertTrue(page.current_input)
        self.assertEqual(page.inspector.generation, generation)
        self.assertFalse(workers[1].cancelled)
        self.assertIn(workers[1], page.inspector.workers)
        workers[1].succeed(media(workers[1].request["url"]))
        self.assertTrue(page.cards["https://example.com/two"].download.isEnabled())
        self.assertTrue(page.notice.isHidden())
        page._download_one("https://example.com/two")
        self.assertEqual(page.input.toPlainText(), "")
        self.assertEqual(page.cards, {})
        self.assertTrue(page.notice.isHidden())
        self.assertEqual(len(self.queue.jobs), 2)
        page.deleteLater()

    def test_search_cleanup_does_not_hide_history_save_errors(self):
        from kazaa.ui.video_pages import SearchPage, VideoCard
        page = SearchPage(self.queue)
        card = VideoCard("https://example.com/video", self.queue)
        card.set_result(media())
        page.cards[card.url] = card
        page.cards_layout.addWidget(card)
        self.queue.notice.emit("Could not save download history")
        page._download_one(card.url)
        self.assertEqual(page.notice.text(), "Could not save download history")
        self.assertEqual(page.cards, {})
        page.deleteLater()

    def test_download_dates_are_numeric_and_have_no_time(self):
        from kazaa.ui.video_pages import date_added, DownloadedPage
        stamp = datetime(2026, 10, 11, 23, 17).timestamp()
        self.assertEqual(date_added(stamp), "11.10.26")
        self.assertEqual(date_added(None), "—")
        self.assertEqual(date_added("invalid"), "—")
        job_id, output = self._completed_fixture()
        self.queue.jobs[job_id].update(created=stamp, completed=stamp)
        page = DownloadedPage(self.queue)
        for column, heading in ((9, "Added"), (10, "Downloaded")):
            self.assertEqual(page.completed_table.horizontalHeaderItem(column).text(), heading)
            self.assertEqual(page.completed_table.item(0, column).text(), "11.10.26")
        page.deleteLater()

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
        self.assertEqual(page.cards, {})
        self.assertTrue(page.download_selected.isHidden())
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
        worker.progress.emit({"status": "downloading", "percent": 50, "total_bytes": 2048, "downloaded_bytes": 1024,
                              "speed": 1024, "actual_quality": "720p"})
        self.assertEqual(page.active_table.rowCount(), 1)
        self.assertEqual(page.active_table.item(0, 1).text(), "Video")
        self.assertEqual(page.active_table.item(0, 2).text(), "MP4")
        self.assertEqual(page.active_table.item(0, 4).text(), "Link")
        self.assertEqual(page.active_table.item(0, 5).text(), "2.0 KB")
        self.assertEqual(page.active_table.cellWidget(0, 6).bar.value(), 50)
        self.assertEqual(page.active_table.cellWidget(0, 6).state.text(), "50%")
        self.assertEqual(page.active_table.item(0, 7).text(), "1.0 KB/s")
        self.assertEqual(page.active_table.item(0, 3).text(), "720p")
        self.assertNotEqual(page.active_table.item(0, 9).text(), "—")
        self.assertEqual(page.active_table.item(0, 10).text(), "—")
        output = self.root / "video.mp4"
        output.write_bytes(b"done")
        worker.succeed({"files": [str(output)], "size": 4, "actual_quality": "720p"})
        self.assertEqual(page.active_table.rowCount(), 0)
        self.assertEqual(page.completed_table.rowCount(), 1)
        self.assertEqual(page.completed_table.item(0, 5).text(), "4 B")
        self.assertEqual(page.completed_table.cellWidget(0, 6).state.text(), "100%")
        self.assertEqual(page.completed_table.item(0, 7).text(), "—")
        self.assertNotEqual(page.completed_table.item(0, 10).text(), "—")
        page.deleteLater()

    def test_table_context_actions_and_keyboard_menu(self):
        from kazaa.ui.video_pages import DownloadedPage
        page = DownloadedPage(self.queue)
        job_id = self.queue.submit(media(), self.options)
        worker = self.queue.workers[job_id]
        self.assertEqual([a.text() for a in page.context_menu(job_id).actions()], ["Pause", "Stop", "Delete…"])
        self.assertFalse(page.context_menu(job_id).actions()[-1].isEnabled())
        page.context_menu(job_id).actions()[1].trigger()
        self.assertTrue(worker.cancelled)
        worker.fail("Cancelled")
        self.assertEqual(page.context_menu(job_id).actions()[0].text(), "Resume")
        page.context_menu(job_id).actions()[0].trigger()
        output = self.root / "video.mp4"
        output.write_bytes(b"done")
        self.queue.workers[job_id].succeed({"files": [str(output)], "size": 4})
        menu = page.context_menu(job_id)
        self.assertEqual([a.text() for a in menu.actions()], ["Open file", "Show in folder", "Delete…"])
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

    def test_pause_resume_keeps_job_id_and_partial_options(self):
        job_id = self.queue.submit(media(), self.options)
        worker = self.queue.workers[job_id]
        worker.progress.emit({"status": "downloading", "percent": 25})
        self.queue.pause(job_id)
        worker.progress.emit({"status": "downloading", "percent": 30})
        self.assertEqual(self.queue.jobs[job_id]["status"], "pausing")
        worker.fail("Cancelled")
        self.assertEqual(self.queue.jobs[job_id]["status"], "paused")
        restored = VideoQueue(self.queue.path, worker_factory=FakeWorker)
        self.assertEqual(restored.jobs[job_id]["status"], "paused")
        self.assertEqual(restored.workers, {})
        with self.assertRaises(ValueError):
            self.queue.submit(media(), self.options)
        self.queue.resume(job_id)
        self.assertEqual(self.queue.workers[job_id].request["id"], job_id)
        self.assertEqual(self.queue.workers[job_id].request["options"], self.options.to_dict())

    def test_live_stop_finalizes_and_keeps_file_in_downloaded_group(self):
        from kazaa.ui.video_pages import DownloadedPage
        page = DownloadedPage(self.queue)
        info = {**media(), "live": True}
        job_id = self.queue.submit(info, self.options)
        worker = self.queue.workers[job_id]
        worker.progress.emit({"status": "recording", "live": True, "elapsed": 65, "size": 2048})
        self.assertEqual(page.active_table.cellWidget(0, 6).state.text(), "Recording · 1:05")
        self.assertEqual([a.text() for a in page.context_menu(job_id).actions()], ["Stop", "Delete…"])
        self.queue.pause(job_id)
        self.assertFalse(worker.cancelled)
        self.queue.stop_job(job_id)
        self.assertTrue(worker.stopped)
        self.assertFalse(worker.cancelled)
        worker.progress.emit({"status": "recording", "elapsed": 70})
        self.assertEqual(self.queue.jobs[job_id]["status"], "stopping")
        output = self.root / "recording.mp4"
        output.write_bytes(b"playable test fixture")
        worker.succeed({"files": [str(output)], "size": output.stat().st_size, "live": True, "stopped": True})
        self.assertEqual(self.queue.jobs[job_id]["status"], "completed")
        self.assertEqual(page.completed_table.rowCount(), 1)
        self.assertIsNotNone(self.queue.jobs[job_id]["completed"])
        page.deleteLater()

    def test_download_and_record_remove_cards_only_after_successful_submission(self):
        from kazaa.ui.video_pages import SearchPage, VideoCard
        page = SearchPage(self.queue)
        for live in (False, True):
            url = f"https://example.com/{live}"
            page.input.setPlainText(url)
            page.current_input = True
            card = VideoCard(url, self.queue)
            card.set_result({**media(url), "live": live})
            page.cards[url] = card
            page.cards_layout.addWidget(card)
            card.download_requested.connect(page._download_one)
            QTest.mouseClick(card.download, Qt.LeftButton)
            self.assertNotIn(url, page.cards)
            self.assertEqual(page.cards_layout.count(), 0)
            self.assertEqual(page.input.toPlainText(), "")
            self.assertTrue(page.notice.isHidden())
            page._download_one(url)  # A second click cannot submit another job.
        self.assertEqual(len(self.queue.jobs), 2)
        duplicate = VideoCard("https://example.com/False", self.queue)
        duplicate.set_result(media(duplicate.url))
        page.cards[duplicate.url] = duplicate
        page.cards_layout.addWidget(duplicate)
        page._download_one(duplicate.url)
        self.assertIn(duplicate.url, page.cards)
        self.assertIn("already", duplicate.status.text())
        page.deleteLater()

    def test_final_quality_uses_output_streams_and_not_audio_selection(self):
        fixtures = [
            ("video", "mp4", {"codec_type": "video", "height": 1080}, "1080p"),
            ("audio", "mp3", {"codec_type": "audio", "bit_rate": "191923"}, "192 kbps"),
            ("audio", "flac", {"codec_type": "audio", "sample_rate": "48000", "bits_per_raw_sample": "24"}, "48 kHz · 24-bit"),
            ("audio", "wav", {"codec_type": "audio", "sample_rate": "44100", "bits_per_sample": 16}, "44.1 kHz · 16-bit"),
        ]
        for kind, fmt, stream, expected in fixtures:
            options = backend.DownloadOptions(kind=kind, format=fmt, folder=str(self.root))
            result = SimpleNamespace(stdout=json.dumps({"streams": [stream]}))
            with patch.object(backend, "which", return_value="ffprobe"), patch.object(backend.subprocess, "run", return_value=result) as run:
                self.assertEqual(backend.output_quality(self.root / f"output.{fmt}", options), expected)
                self.assertEqual(run.call_args.kwargs["timeout"], 10)
        with patch.object(backend, "which", return_value="ffprobe"), patch.object(backend.subprocess, "run", side_effect=OSError):
            self.assertEqual(backend.output_quality("video.mp4", self.options, {"requested_formats": [{"height": 720}]}), "720p")
            audio = backend.DownloadOptions(kind="audio", format="mp3", quality="192", folder=str(self.root))
            self.assertEqual(backend.output_quality("audio.mp3", audio, {"abr": 128}), "")

    def test_old_history_has_unknown_quality_and_completion_date(self):
        from kazaa.ui.video_pages import DownloadedPage
        job_id = self.queue.submit(media(), self.options)
        self.queue.workers[job_id].fail("Stopped")
        job = self.queue.jobs[job_id]
        job.update(status="completed", created=0)
        self.queue.save()
        restored = VideoQueue(self.queue.path, worker_factory=FakeWorker)
        page = DownloadedPage(restored)
        self.assertEqual(page.completed_table.item(0, 3).text(), "—")
        self.assertNotEqual(page.completed_table.item(0, 9).text(), "—")
        self.assertEqual(page.completed_table.item(0, 10).text(), "—")
        page.deleteLater()

    def _completed_fixture(self):
        job_id = self.queue.submit(media(), self.options)
        output = self.root / "fixture.mp4"
        output.write_bytes(b"fixture")
        self.queue.workers[job_id].succeed({"files": [str(output)], "actual_quality": "720p"})
        return job_id, output

    def test_delete_modes_update_files_rows_and_saved_history(self):
        from kazaa.ui.video_pages import DownloadedPage
        page = DownloadedPage(self.queue)
        for mode in ("entry", "file", "both"):
            job_id, output = self._completed_fixture()
            def recycle(path):
                Path(path).unlink()  # Only the temporary fixture; mock the external trash API.
                return True
            with patch("kazaa.video_jobs.QFile.moveToTrash", side_effect=recycle) as trash:
                self.queue.delete(job_id, mode)
                self.assertEqual(trash.call_count, 0 if mode == "entry" else 1)
            self.assertEqual(output.exists(), mode == "entry")
            restored = VideoQueue(self.queue.path, worker_factory=FakeWorker)
            self.assertEqual(job_id in restored.jobs, mode == "file")
            self.assertEqual(page.completed_table.row_for(job_id) >= 0, mode == "file")
            if mode == "file":
                row = page.completed_table.row_for(job_id)
                self.assertEqual(page.completed_table.cellWidget(row, 6).state.text(), "File deleted")
                self.assertTrue(restored.jobs[job_id]["files_deleted"])
                self.assertFalse(page.context_menu(job_id).actions()[0].isEnabled())
                self.queue.delete(job_id, "entry")
        self.assertEqual(page.jobs, {})
        self.assertFalse(page.empty.isHidden())
        page.deleteLater()

    def test_delete_rejects_active_jobs_and_keeps_entry_when_recycling_fails(self):
        job_id = self.queue.submit(media(), self.options)
        with self.assertRaisesRegex(ValueError, "Stop"):
            self.queue.delete(job_id, "both")
        self.queue.workers[job_id].fail("Cancelled")
        self.queue.delete(job_id)
        job_id, output = self._completed_fixture()
        with patch("kazaa.video_jobs.QFile.moveToTrash", return_value=False):
            with self.assertRaisesRegex(OSError, "entry was kept"):
                self.queue.delete(job_id, "both")
        self.assertTrue(output.exists())
        self.assertIn(job_id, self.queue.jobs)
        self.assertIn(job_id, VideoQueue(self.queue.path, worker_factory=FakeWorker).jobs)
        self.queue.jobs[job_id]["files"] = [str(self.root)]
        with self.assertRaisesRegex(ValueError, "output files"):
            self.queue.delete(job_id, "both")

    def test_missing_files_and_failed_history_save_do_not_lose_entries(self):
        job_id, output = self._completed_fixture()
        output.unlink()
        with patch.object(self.queue, "save", return_value=False):
            with self.assertRaisesRegex(OSError, "entry was kept"):
                self.queue.delete(job_id, "both")
        self.assertIn(job_id, self.queue.jobs)
        self.queue.delete(job_id, "both")
        self.assertNotIn(job_id, self.queue.jobs)

    def test_delete_dialog_defaults_to_entry_and_cancel_keeps_download(self):
        from kazaa.ui.video_pages import DeleteDownloadDialog, DownloadedPage
        job_id, output = self._completed_fixture()
        dialog = DeleteDownloadDialog(self.queue.jobs[job_id])
        self.assertEqual(dialog.mode(), "entry")
        dialog.choices["file"].setChecked(True)
        self.assertEqual(dialog.mode(), "file")
        dialog.deleteLater()
        page = DownloadedPage(self.queue)
        with patch.object(DeleteDownloadDialog, "exec", return_value=DeleteDownloadDialog.Rejected):
            page._delete(job_id)
        self.assertIn(job_id, self.queue.jobs)
        self.assertTrue(output.exists())
        with patch.object(DeleteDownloadDialog, "exec", return_value=DeleteDownloadDialog.Accepted):
            page._delete(job_id)
        self.assertNotIn(job_id, self.queue.jobs)
        self.assertTrue(output.exists())
        page.deleteLater()

    def _completed_batch(self, count=3):
        entries = []
        for index in range(count):
            job_id = self.queue.submit(media(f"https://example.com/batch/{index}"), self.options)
            output = self.root / f"batch-{index}.mp4"
            output.write_bytes(b"fixture")
            self.queue.workers[job_id].succeed({"files": [str(output)]})
            entries.append((job_id, output))
        return entries

    def test_download_click_selection_context_menu_and_moving_rows(self):
        from kazaa.ui.video_pages import DownloadedPage
        entries = self._completed_batch()
        page = DownloadedPage(self.queue)
        page.resize(1500, 700)
        page.show()
        self.app.processEvents()
        table = page.completed_table
        def click(row, button=Qt.LeftButton, modifiers=Qt.NoModifier):
            QTest.mouseClick(table.viewport(), button, modifiers,
                pos=table.visualItemRect(table.item(row, 0)).center())
        click(0)
        click(1)
        self.assertEqual(page.selected_jobs(), [entries[1][0]])
        click(1)
        self.assertEqual(page.selected_jobs(), [entries[1][0]])
        click(0, modifiers=Qt.ControlModifier)
        self.assertEqual(set(page.selected_jobs()), {entries[0][0], entries[1][0]})
        click(0, Qt.RightButton)
        self.assertEqual(len(page.selected_jobs()), 2)
        table._context_menu(table.visualItemRect(table.item(0, 0)).center())
        self.assertEqual(len(page.selected_jobs()), 2)
        self.assertIn("Delete selected", page._menu.actions()[0].text())
        page._menu.close()
        click(0, modifiers=Qt.ControlModifier)
        self.assertEqual(page.selected_jobs(), [entries[1][0]])
        table._context_menu(table.visualItemRect(table.item(2, 0)).center())
        self.assertEqual(page.selected_jobs(), [entries[2][0]])
        page._menu.close()
        job_id = entries[2][0]
        moved = {**self.queue.jobs[job_id], "status": "stopped"}
        page.update_job(job_id, moved)
        self.assertEqual(page.selected_jobs(), [job_id])
        page.update_job(job_id, {**moved, "status": "completed"})
        self.assertEqual(page.selected_jobs(), [job_id])
        QTest.keyClick(page.completed_table, Qt.Key_Escape)
        self.assertEqual(page.selected_jobs(), [])
        click(0)
        self.assertEqual(len(page.selected_jobs()), 1)
        QTest.mouseClick(page.widget(), Qt.LeftButton, pos=page.widget().rect().bottomRight())
        self.assertEqual(page.selected_jobs(), [])
        # Selection can span the two sections, and a row update preserves it.
        page.update_job(entries[2][0], {**moved, "status": "stopped"})
        click(0)
        active_table = page.active_table
        QTest.mouseClick(active_table.viewport(), Qt.LeftButton, Qt.ControlModifier,
            pos=active_table.visualItemRect(active_table.item(0, 0)).center())
        self.assertEqual(set(page.selected_jobs()), {entries[0][0], entries[2][0]})
        page.update_job(entries[0][0], self.queue.jobs[entries[0][0]])
        self.assertEqual(len(page.selected_jobs()), 2)
        click(0)
        self.assertEqual(page.selected_jobs(), [entries[0][0]])
        QTest.mouseClick(active_table.viewport(), Qt.LeftButton,
            pos=active_table.visualItemRect(active_table.item(0, 0)).center())
        self.assertEqual(page.selected_jobs(), [entries[2][0]])
        page.deleteLater()

    def test_download_double_click_opens_file_and_reports_opening_errors(self):
        from kazaa.ui.video_pages import DownloadedPage
        job_id, output = self._completed_batch(1)[0]
        page = DownloadedPage(self.queue)
        page.resize(1500, 700)
        page.show()
        self.app.processEvents()
        table = page.completed_table
        position = table.visualItemRect(table.item(0, 2)).center()
        with patch("kazaa.ui.video_pages.QDesktopServices.openUrl", return_value=True) as open_url:
            QTest.mouseClick(table.viewport(), Qt.LeftButton, pos=position)
            open_url.assert_not_called()
            QTest.mouseDClick(table.viewport(), Qt.LeftButton, pos=position)
            open_url.assert_called_once()
            self.assertEqual(open_url.call_args.args[0].toLocalFile(), output.as_posix())
            self.assertEqual(page.selected_jobs(), [job_id])
            self.assertEqual(page.notice.text(), "")
        with patch("kazaa.ui.video_pages.QDesktopServices.openUrl", return_value=False):
            page._open_download(job_id)
            self.assertIn("default app", page.notice.text())
        with patch("kazaa.ui.video_pages.QDesktopServices.openUrl", return_value=True):
            page._open_download(job_id)
            self.assertEqual(page.notice.text(), "")
        output.unlink()
        with patch("kazaa.ui.video_pages.QDesktopServices.openUrl") as open_url:
            page._open_download(job_id)
            open_url.assert_not_called()
            self.assertIn("no longer", page.notice.text())
        page.deleteLater()

    def test_download_double_click_ignores_unfinished_and_deleted_files(self):
        from kazaa.ui.video_pages import DownloadedPage
        job_id, output = self._completed_batch(1)[0]
        page = DownloadedPage(self.queue)
        page.resize(1500, 700)
        page.show()
        self.app.processEvents()
        with patch("kazaa.ui.video_pages.QDesktopServices.openUrl") as open_url:
            page.update_job(job_id, {**self.queue.jobs[job_id], "status": "stopped"})
            table = page.active_table
            position = table.visualItemRect(table.item(0, 0)).center()
            QTest.mouseClick(table.viewport(), Qt.LeftButton, pos=position)
            QTest.mouseDClick(table.viewport(), Qt.LeftButton, pos=position)
            open_url.assert_not_called()
            for changes in ({"files": []}, {"files_deleted": True}):
                page.update_job(job_id, {**self.queue.jobs[job_id], **changes})
                page._open_download(job_id)
                open_url.assert_not_called()
                self.assertIn("no longer", page.notice.text())
        page.deleteLater()

    def test_download_double_click_offers_multiple_files_without_opening_all(self):
        from kazaa.ui.video_pages import DownloadedPage
        job_id, output = self._completed_batch(1)[0]
        second = self.root / "second.txt"
        second.write_text("fixture")
        page = DownloadedPage(self.queue)
        page.update_job(job_id, {**self.queue.jobs[job_id], "files": [str(output), str(second)]})
        page.resize(1500, 700)
        page.show()
        self.app.processEvents()
        table = page.completed_table
        position = table.visualItemRect(table.item(0, 0)).center()
        with patch("kazaa.ui.video_pages.QDesktopServices.openUrl", return_value=True) as open_url:
            QTest.mouseClick(table.viewport(), Qt.LeftButton, pos=position)
            QTest.mouseDClick(table.viewport(), Qt.LeftButton, pos=position)
            open_url.assert_not_called()
            submenu = page._menu.actions()[0].menu()
            self.assertEqual([action.text() for action in submenu.actions()], [output.name, second.name])
            submenu.actions()[1].trigger()
            open_url.assert_called_once()
            self.assertEqual(open_url.call_args.args[0].toLocalFile(), second.as_posix())
            submenu.close()
        page.deleteLater()

    def test_batch_delete_modes_keep_unselected_downloads(self):
        from kazaa.ui.video_pages import DeleteDownloadDialog, DownloadedPage
        for mode in ("entry", "file", "both"):
            entries = self._completed_batch()
            page = DownloadedPage(self.queue)
            selected = [job_id for job_id, output in entries[:2]]
            def recycle(path):
                Path(path).unlink()
                return True
            with patch.object(DeleteDownloadDialog, "exec", return_value=DeleteDownloadDialog.Accepted), \
                    patch.object(DeleteDownloadDialog, "mode", return_value=mode), \
                    patch("kazaa.video_jobs.QFile.moveToTrash", side_effect=recycle):
                page._delete(selected)
            for job_id, output in entries[:2]:
                self.assertEqual(job_id in self.queue.jobs, mode == "file")
                self.assertEqual(output.exists(), mode == "entry")
            self.assertIn(entries[2][0], self.queue.jobs)
            self.assertTrue(entries[2][1].exists())
            page.deleteLater()
            for job_id, output in entries:
                if job_id in self.queue.jobs:
                    self.queue.delete(job_id)

    def test_batch_delete_rejects_active_selection_and_reports_partial_failure(self):
        from kazaa.ui.video_pages import DeleteDownloadDialog, DownloadedPage
        entries = self._completed_batch()
        page = DownloadedPage(self.queue)
        active = self.queue.submit(media("https://example.com/active"), self.options)
        selected = [entries[0][0], active]
        self.assertFalse(page.context_menu(active, selected).actions()[0].isEnabled())
        with patch.object(DeleteDownloadDialog, "exec") as show:
            page._delete(selected)
            show.assert_not_called()
        self.assertIn(entries[0][0], self.queue.jobs)
        original = self.queue.delete
        def delete(job_id, mode):
            if job_id == entries[1][0]:
                raise OSError("Could not recycle this file")
            original(job_id, mode)
        with patch.object(DeleteDownloadDialog, "exec", return_value=DeleteDownloadDialog.Accepted), \
                patch.object(self.queue, "delete", side_effect=delete):
            page._delete([job_id for job_id, output in entries])
        self.assertNotIn(entries[0][0], self.queue.jobs)
        self.assertIn(entries[1][0], self.queue.jobs)
        self.assertNotIn(entries[2][0], self.queue.jobs)
        self.assertIn("Could not recycle", page.notice.text())
        page.deleteLater()

    def test_live_close_requests_graceful_stop_and_preserves_completed_capture(self):
        job_id = self.queue.submit({**media(), "live": True}, self.options)
        worker = self.queue.workers[job_id]
        self.queue.stop()
        self.assertTrue(worker.stopped)
        self.assertFalse(worker.cancelled)
        output = self.root / "closing.mp4"
        output.write_bytes(b"saved")
        worker.succeed({"files": [str(output)], "live": True})
        self.assertEqual(self.queue.jobs[job_id]["status"], "completed")

    def test_failed_live_stop_does_not_claim_a_completed_file(self):
        job_id = self.queue.submit({**media(), "live": True}, self.options)
        worker = self.queue.workers[job_id]
        self.queue.stop_job(job_id)
        worker.fail("Cancelled")
        self.assertEqual(self.queue.jobs[job_id]["status"], "stopped")
        self.assertEqual(self.queue.jobs[job_id]["files"], [])
        self.assertIn("partial", self.queue.jobs[job_id]["error"])

    def test_live_format_selection_preserves_resolution_and_separate_audio(self):
        from kazaa.video_live import recording_command, select_streams
        info = {"formats": [{"url": "https://example.com/360", "height": 360, "vcodec": "h264", "acodec": "none"},
                            {"url": "https://example.com/720", "height": 720, "vcodec": "h264", "acodec": "none"},
                            {"url": "https://example.com/audio", "vcodec": "none", "acodec": "aac"}]}
        options = backend.DownloadOptions(quality="360", folder=str(self.root))
        self.assertEqual([f["url"] for f in select_streams(info, options)], ["https://example.com/360", "https://example.com/audio"])
        command = recording_command(info, options, self.root / "capture.part")
        self.assertIn("1:a:0?", command)
        self.assertIn("+frag_keyframe+empty_moov", command)
        self.assertEqual(command[command.index("-force_key_frames") + 1], "expr:gte(t,n_forced*2)")
        self.assertEqual(command[command.index("-forced-idr") + 1], "1")

    def test_live_finalization_copies_streams_and_validates_before_publishing(self):
        from kazaa import video_live
        partial, output = self.root / "capture.mp4.part", self.root / "capture.mp4"
        partial.write_bytes(b"capture")
        calls = []
        def run(command, **kwargs):
            calls.append(command)
            if "-c" in command:
                self.assertEqual(command[command.index("-c") + 1], "copy")
                self.assertIn("+faststart", command)
                Path(command[-1]).write_bytes(b"finalized")
                return SimpleNamespace(returncode=0, stderr="")
            self.assertTrue(partial.exists())
            self.assertFalse(output.exists())
            return SimpleNamespace(returncode=0, stdout=json.dumps({"format": {"duration": "5"},
                "streams": [{"codec_type": "video"}, {"codec_type": "audio"}]}))
        with patch.object(video_live.shutil, "which", return_value="ffprobe"), \
                patch.object(video_live.subprocess, "run", side_effect=run):
            video_live.finalize_recording(partial, output, self.options)
        self.assertEqual(output.read_bytes(), b"finalized")
        self.assertFalse(partial.exists())
        self.assertEqual(len(calls), 2)

    def test_live_failed_or_timed_out_finalization_keeps_partial(self):
        from kazaa import video_live
        for failure in (SimpleNamespace(returncode=1, stderr="Mux failed"),
                        video_live.subprocess.TimeoutExpired("ffmpeg", 120)):
            partial, output = self.root / "capture.mp4.part", self.root / "capture.mp4"
            partial.write_bytes(b"capture")
            def run(*args, **kwargs):
                Path(str(output) + ".finalizing").write_bytes(b"incomplete")
                if isinstance(failure, Exception):
                    raise failure
                return failure
            with patch.object(video_live.shutil, "which", return_value="ffprobe"), \
                    patch.object(video_live.subprocess, "run", side_effect=run):
                with self.assertRaisesRegex(ValueError, "partial recording was kept"):
                    video_live.finalize_recording(partial, output, self.options)
            self.assertEqual(partial.read_bytes(), b"capture")
            self.assertFalse(output.exists())
            self.assertFalse(Path(str(output) + ".finalizing").exists())

    def test_live_finalization_rejects_missing_media_and_stop_shows_processing(self):
        from kazaa import video_live
        partial, output = self.root / "capture.mp4.part", self.root / "capture.mp4"
        partial.write_bytes(b"capture")
        def run(command, **kwargs):
            if "-c" in command:
                Path(command[-1]).write_bytes(b"invalid")
                return SimpleNamespace(returncode=0, stderr="")
            return SimpleNamespace(returncode=0, stdout='{"format":{"duration":"5"},"streams":[]}')
        with patch.object(video_live.shutil, "which", return_value="ffprobe"), \
                patch.object(video_live.subprocess, "run", side_effect=run):
            with self.assertRaisesRegex(ValueError, "missing its media"):
                video_live.finalize_recording(partial, output, self.options)
        self.assertTrue(partial.exists())
        self.assertFalse(output.exists())
        job_id = self.queue.submit({**media(), "live": True}, self.options)
        worker = self.queue.workers[job_id]
        self.queue.stop_job(job_id)
        worker.progress.emit({"status": "processing", "live": True})
        self.assertEqual(self.queue.jobs[job_id]["status"], "processing")

    def test_live_result_has_record_action_and_disables_transcript_capture(self):
        from kazaa.ui.video_pages import VideoCard
        self.queue.set_options({"kind": "transcript", "format": "txt", "folder": str(self.root)})
        card = VideoCard("https://example.com/live", self.queue)
        card.set_result({**media(), "live": True})
        self.assertEqual(card.download.text(), "Record")
        self.assertEqual(card.options_panel.kind.currentData(), "video")
        self.assertFalse(card.options_panel.kind.model().item(2).isEnabled())
        card.deleteLater()

    def torrent_info(self, url=None):
        return {"source": "torrent", "url": url or "magnet:?xt=urn:btih:" + "a" * 40,
                "title": "Bundle", "hashes": ["v1:" + "a" * 40, "v2:" + "b" * 64], "size": 30,
                "metadata_file": str(self.root / "cached.metadata"),
                "manifest": [{"index": 0, "path": "Bundle/first.txt", "size": 10},
                             {"index": 1, "path": "Bundle/nested/second.txt", "size": 20},
                             {"index": 2, "path": "Bundle/.pad/3", "size": 3, "pad": True}]}

    def test_restart_runs_unfinished_torrents_and_links_but_keeps_manual_states(self):
        torrent = self.queue.submit(self.torrent_info(), {"folder": str(self.root), "selected_files": [0]})
        active = self.queue.submit(media(), self.options)
        paused = self.queue.submit(media("https://example.com/paused"), self.options)
        self.queue.pause(paused)
        stopped = self.queue.submit(media("https://example.com/stopped"), self.options)
        self.queue.stop_job(stopped)
        waiting = self.queue.submit(media("https://example.com/waiting"), self.options)
        self.queue.stop()
        for worker in list(self.queue.workers.values()):
            worker.fail("Cancelled")
        restored = VideoQueue(self.queue.path, worker_factory=FakeWorker)
        restored.start_pending()
        self.assertEqual(set(restored.workers), {torrent, active})
        self.assertEqual(restored.jobs[waiting]["status"], "queued")
        self.assertEqual(restored.jobs[paused]["status"], "paused")
        self.assertEqual(restored.jobs[stopped]["status"], "stopped")
        self.assertEqual(restored.workers[torrent].request["options"]["selected_files"], [0])
        restored.workers[active].fail("Network error")
        self.assertIn(waiting, restored.workers)
        restored.stop()
        for worker in list(restored.workers.values()):
            worker.fail("Cancelled")

    def test_close_while_pausing_preserves_pause_across_restart(self):
        job_id = self.queue.submit(self.torrent_info(), {"folder": str(self.root), "selected_files": [0]})
        self.queue.pause(job_id)
        self.queue.stop()
        self.queue.workers[job_id].fail("Cancelled")
        restored = VideoQueue(self.queue.path, worker_factory=FakeWorker)
        restored.start_pending()
        self.assertEqual(restored.jobs[job_id]["status"], "paused")
        self.assertEqual(restored.workers, {})

    def test_torrent_main_checkbox_selects_all_and_reflects_individual_choices(self):
        from kazaa.ui.torrent_widgets import TorrentCard
        card = TorrentCard(self.torrent_info()["url"], self.queue)
        card.set_result(self.torrent_info())
        card.selected.click()
        self.assertEqual(card.file_selector.selected_files(), [])
        self.assertFalse(card.download.isEnabled())
        card.file_selector.items[0].setCheckState(0, Qt.Checked)
        self.assertEqual(card.selected.checkState(), Qt.PartiallyChecked)
        self.assertTrue(card.download.isEnabled())
        card.selected.click()
        self.assertEqual(card.file_selector.selected_files(), [0, 1])
        card.selected.click()
        self.assertEqual(card.file_selector.selected_files(), [])
        card.deleteLater()

    def test_eta_and_source_hover_use_live_worker_health_and_clear_eta_when_paused(self):
        from kazaa.ui.video_pages import DownloadedPage
        from kazaa.torrent_backend import torrent_health
        page = DownloadedPage(self.queue)
        job_id = self.queue.submit(self.torrent_info(), {"folder": str(self.root), "selected_files": [0]})
        health = torrent_health(SimpleNamespace(num_seeds=2, num_peers=5, num_complete=8,
                                               num_incomplete=-1, download_payload_rate=100))
        self.queue.workers[job_id].progress.emit({"status": "downloading", "eta": 3661, "torrent_health": health})
        self.assertEqual(page.active_table.horizontalHeaderItem(8).text(), "ETA")
        self.assertEqual(page.active_table.item(0, 8).text(), "1:01:01")
        details = page.active_table.item(0, 4).toolTip()
        self.assertIn("Active", details)
        self.assertIn("Seeds: 2 connected · 8 reported", details)
        self.assertIn("Peers: 3 connected", details)
        self.assertNotIn("-1", details)
        self.queue.pause(job_id)
        self.queue.workers[job_id].fail("Cancelled")
        self.assertEqual(page.active_table.item(0, 8).text(), "—")
        self.assertIn("Paused", page.active_table.item(0, 4).toolTip())
        link = self.queue.submit(media(), self.options)
        row = page.active_table.row_for(link)
        self.assertEqual(page.active_table.item(row, 4).toolTip(), media()["url"])
        page.deleteLater()

    def test_torrent_inputs_keep_paths_with_spaces_and_hash_identity(self):
        from kazaa.sources import parse_sources, source_key, magnet_hashes
        path = self.root / "folder with spaces" / "sample.torrent"
        inputs = parse_sources(str(path) + "\nhttps://example.com/movie\nhttps://example.com/file.torrent?x=1")
        self.assertEqual(len(inputs), 3)
        self.assertEqual(inputs[0]["url"], path.as_uri())
        self.assertEqual([entry["source"] for entry in inputs], ["torrent", "link", "torrent"])
        magnet = self.torrent_info()["url"]
        self.assertEqual(source_key(magnet), source_key(magnet + "&dn=Other&tr=https%3A%2F%2Ftracker.example"))
        self.assertEqual(magnet_hashes("magnet:?xt=urn:btmh:1220" + "b" * 64), ["v2:" + "b" * 64])

    def test_torrent_tree_folder_states_selection_size_and_padding(self):
        from kazaa.ui.torrent_widgets import TorrentFiles
        selector = TorrentFiles(self.torrent_info()["manifest"])
        self.assertEqual(selector.selected_files(), [0, 1])
        self.assertIn("30 B", selector.summary.text())
        root = selector.tree.topLevelItem(0)
        selector.items[0].setCheckState(0, Qt.Unchecked)
        self.assertEqual(root.checkState(0), Qt.PartiallyChecked)
        self.assertEqual(selector.selected_files(), [1])
        root.setCheckState(0, Qt.Unchecked)
        self.assertEqual(selector.selected_files(), [])
        root.setCheckState(0, Qt.Checked)
        self.assertEqual(selector.selected_files(), [0, 1])
        selector.select_all(False)
        self.assertEqual(selector.selected_files(), [])
        selector.show()
        selector.tree.setCurrentItem(selector.items[0])
        QTest.keyClick(selector.tree, Qt.Key_Space)
        self.assertEqual(selector.selected_files(), [0])
        self.assertNotIn(2, selector.items)
        selector.deleteLater()

    def test_torrent_paste_preserves_video_selection_and_pending_inspection(self):
        from kazaa.ui.video_pages import SearchPage
        page = SearchPage(self.queue)
        page.inspector.worker_factory = FakeWorker
        page.input.setPlainText("https://example.com/one\nhttps://example.com/two")
        page.inspect()
        first, pending = list(page.inspector.workers)
        first.succeed(media(first.request["url"]))
        card = page.cards[first.request["url"]]
        card.options_panel.kind.setCurrentIndex(card.options_panel.kind.findData("audio"))
        mime = QMimeData()
        mime.setText(self.torrent_info()["url"])
        page.input.insertFromMimeData(mime)
        self.assertFalse(pending.cancelled)
        self.assertIs(page.cards[first.request["url"]], card)
        self.assertEqual(card.options_panel.kind.currentData(), "audio")
        self.assertFalse(any(w.request["source"] == "torrent" for w in page.inspector.workers))
        self.assertNotIn(self.torrent_info()["url"], page.cards)
        page.inspect()
        torrent_worker = next(w for w in page.inspector.workers if w.request["source"] == "torrent")
        torrent_worker.succeed(self.torrent_info())
        tor_card = page.cards[self.torrent_info()["url"]]
        tor_card.file_selector.select_all(False)
        self.assertFalse(tor_card.download.isEnabled())
        tor_card.file_selector.items[1].setCheckState(0, Qt.Checked)
        page._download_one(tor_card.url)
        job = next(iter(self.queue.jobs.values()))
        self.assertEqual(job["options"]["selected_files"], [1])
        self.assertNotIn(tor_card.url, page.input.toPlainText())
        self.assertTrue(card.download.isEnabled())
        pending.succeed(media(pending.request["url"]))
        self.assertTrue(page.cards[pending.request["url"]].download.isEnabled())
        self.assertFalse(page.notice.isVisible())
        page.deleteLater()

    def test_torrents_share_concurrency_with_videos_and_shutdown_gracefully(self):
        first = self.queue.submit(media("https://example.com/one"), self.options)
        torrent = self.queue.submit(self.torrent_info(), {"folder": str(self.root), "selected_files": [0]})
        waiting = self.queue.submit(media("https://example.com/two"), self.options)
        self.assertEqual(len(self.queue.workers), 2)
        self.assertEqual(self.queue.jobs[waiting]["status"], "queued")
        torrent_worker = self.queue.workers[torrent]
        video_worker = self.queue.workers[first]
        self.queue.stop()
        self.assertTrue(torrent_worker.stopped)
        self.assertFalse(torrent_worker.cancelled)
        self.assertTrue(video_worker.cancelled)
        self.assertEqual(self.queue.jobs[waiting]["status"], "interrupted")

    def test_dropped_torrents_are_inspected_before_download_and_failures_can_retry(self):
        from kazaa.ui.video_pages import SearchPage
        page = SearchPage(self.queue)
        page.inspector.worker_factory = FakeWorker
        path = self.root / "file with spaces.torrent"
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path))])
        self.assertTrue(page.input.canInsertFromMimeData(mime))
        page.input.insertFromMimeData(mime)
        self.assertEqual(page.inspector.workers, {})
        self.assertEqual(page.cards, {})
        self.assertEqual(page.input.toPlainText(), path.as_uri())
        page.inspect()
        worker = next(iter(page.inspector.workers))
        self.assertEqual(worker.request["url"], path.as_uri())
        self.assertEqual(worker.request["source"], "torrent")
        self.assertEqual(self.queue.jobs, {})
        worker.fail("Invalid torrent")
        self.assertIn("Invalid torrent", page.cards[path.as_uri()].status.text())
        page.inspect()
        retry = next(iter(page.inspector.workers))
        retry.succeed(self.torrent_info(path.as_uri()))
        self.assertTrue(page.cards[path.as_uri()].download.isEnabled())
        page.deleteLater()

    def test_multiple_dropped_torrents_and_mixed_paste_wait_for_inspect(self):
        from kazaa.ui.video_pages import SearchPage
        page = SearchPage(self.queue)
        page.inspector.worker_factory = FakeWorker
        paths = [self.root / 'first file.torrent', self.root / 'second file.torrent']
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
        page.input.insertFromMimeData(mime)
        mime = QMimeData()
        mime.setText('https://example.com/video\n' + self.torrent_info()['url'])
        page.input.insertFromMimeData(mime)
        self.assertEqual(FakeWorker.created, [])
        self.assertEqual(page.cards, {})
        QTest.keyClick(page.input, Qt.Key_Return)
        self.assertEqual(len(page.cards), 4)
        requested = [w.request['url'] for w in page.inspector.workers]
        requested += [url for generation, url in page.inspector.pending]
        self.assertEqual(set(requested), {*(path.as_uri() for path in paths),
                                        'https://example.com/video', self.torrent_info()['url']})
        self.assertEqual(self.queue.jobs, {})
        page.deleteLater()

    def test_torrent_duplicates_match_files_magnets_and_hybrid_aliases_after_restart(self):
        info = self.torrent_info()
        options = {"folder": str(self.root), "selected_files": [0]}
        job_id = self.queue.submit(info, options)
        with self.assertRaisesRegex(ValueError, "already in Downloads"):
            self.queue.submit(self.torrent_info((self.root / "other.torrent").as_uri()), options)
        worker = self.queue.workers[job_id]
        self.queue.pause(job_id)
        self.assertTrue(worker.stopped)
        self.assertFalse(worker.cancelled)
        worker.fail("Cancelled")
        restored = VideoQueue(self.queue.path, worker_factory=FakeWorker)
        self.assertEqual(restored.torrent_match(["v2:" + "b" * 64]), job_id)
        self.assertEqual(restored.jobs[job_id]["status"], "paused")
        restored.stop()

    def test_torrent_existing_preview_opens_downloads_and_clears_search(self):
        from kazaa.ui.video_pages import SearchPage
        from kazaa.ui.torrent_widgets import TorrentCard
        info = self.torrent_info()
        job_id = self.queue.submit(info, {"folder": str(self.root), "selected_files": [0]})
        page = SearchPage(self.queue)
        card = TorrentCard(info["url"], self.queue)
        card.set_result(info)
        page.cards[info["url"]] = card
        page.cards_layout.addWidget(card)
        page.input.setPlainText(info["url"])
        page.current_input = True
        opened = []
        page.open_download.connect(opened.append)
        self.assertEqual(card.download.text(), "Open in Downloads")
        page._download_one(card.url)
        self.assertEqual(opened, [job_id])
        self.assertEqual(len(self.queue.jobs), 1)
        self.assertEqual(page.input.toPlainText(), "")
        page.deleteLater()

    def test_torrent_additional_files_reuse_entry_destination_dates_and_outputs(self):
        info = self.torrent_info()
        job_id = self.queue.submit(info, {"folder": str(self.root), "selected_files": [0]})
        job = self.queue.jobs[job_id]
        created = job["created"]
        output = self.root / "Bundle/first.txt"
        output.parent.mkdir()
        output.write_text("0123456789")
        self.queue.workers[job_id].succeed({"files": [str(output)], "size": 10})
        self.assertEqual(job["status"], "completed")
        self.queue.select_torrent_files(job_id, [1])
        self.assertEqual(len(self.queue.jobs), 1)
        self.assertEqual(job["created"], created)
        self.assertIsNone(job["completed"])
        self.assertEqual(job["options"]["folder"], str(self.root))
        self.assertEqual(job["files"], [str(output)])
        self.assertEqual(self.queue.workers[job_id].request["owned_files"], [str(output)])
        with self.assertRaisesRegex(ValueError, "Pause or stop"):
            self.queue.select_torrent_files(job_id, [0, 1])

    def test_torrent_unsafe_paths_and_unrelated_file_deletion_are_rejected(self):
        from kazaa.sources import output_paths
        for name in ("../escape", "C:/escape", "a/CON.txt", "a/hidden:stream", "a/end.", "/absolute"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                output_paths([{"index": 0, "path": name}], self.root)
        with self.assertRaises(ValueError):
            output_paths([{"index": 0, "path": "a.txt"}, {"index": 1, "path": "A.txt"}], self.root)
        info = self.torrent_info()
        job_id = self.queue.submit(info, {"folder": str(self.root), "selected_files": [0]})
        self.queue.pause(job_id)
        self.queue.workers[job_id].fail("Cancelled")
        unrelated = self.root / "unrelated.txt"
        unrelated.write_text("keep")
        self.queue.jobs[job_id]["files"] = [str(unrelated)]
        with patch("kazaa.video_jobs.QFile.moveToTrash") as trash:
            with self.assertRaisesRegex(ValueError, "Only this torrent"):
                self.queue.delete(job_id, "both")
            trash.assert_not_called()
        self.assertTrue(unrelated.is_file())

    def test_torrent_table_and_file_selection_menu_use_existing_actions(self):
        from kazaa.ui.video_pages import DownloadedPage
        job_id = self.queue.submit(self.torrent_info(), {"folder": str(self.root), "selected_files": [0]})
        page = DownloadedPage(self.queue)
        values = [page.active_table.item(0, i).text() for i in (1, 2, 3, 4)]
        self.assertEqual(values, ["Torrent", "—", "—", "Torrent"])
        choose = next(a for a in page.context_menu(job_id).actions() if a.text() == "Choose files…")
        self.assertFalse(choose.isEnabled())
        self.queue.pause(job_id)
        self.queue.workers[job_id].fail("Cancelled")
        actions = {a.text(): a for a in page.context_menu(job_id).actions()}
        self.assertTrue(actions["Choose files…"].isEnabled())
        self.assertIn("Resume", actions)
        page.deleteLater()

    def test_torrent_file_actions_open_outputs_and_delete_only_owned_files(self):
        from kazaa.ui.video_pages import DeleteDownloadDialog, DownloadedPage
        job_id = self.queue.submit(self.torrent_info(), {"folder": str(self.root), "selected_files": [0]})
        output = self.root / "Bundle/first.txt"
        output.parent.mkdir()
        output.write_text("0123456789")
        unrelated = output.parent / "unrelated.txt"
        unrelated.write_text("keep")
        self.queue.workers[job_id].succeed({"files": [str(output)], "size": 10})
        page = DownloadedPage(self.queue)
        actions = {a.text(): a for a in page.context_menu(job_id).actions()}
        with patch("kazaa.ui.video_pages.QDesktopServices.openUrl") as open_url:
            actions["Open file"].trigger()
            self.assertEqual(open_url.call_args.args[0].toLocalFile(), str(output).replace("\\", "/"))
            actions["Show in folder"].trigger()
            self.assertEqual(open_url.call_args.args[0].toLocalFile(), str(output.parent).replace("\\", "/"))
        dialog = DeleteDownloadDialog(self.queue.jobs[job_id])
        self.assertEqual(set(dialog.choices), {"entry", "file", "both"})
        with patch("kazaa.video_jobs.QFile.moveToTrash", return_value=True) as trash:
            self.queue.delete(job_id, "both")
            trash.assert_called_once_with(str(output))
        self.assertTrue(unrelated.is_file())
        self.assertNotIn(job_id, self.queue.jobs)
        dialog.deleteLater()
        page.deleteLater()


if __name__ == "__main__":
    unittest.main()
