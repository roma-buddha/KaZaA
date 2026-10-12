"""Focused Shred tab interaction checks with isolated profiles and test files."""
import json
import os
from pathlib import Path
import sys
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QContextMenuEvent, QDragEnterEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QPushButton
from kazaa.ui.shell import ShellWindow
from kazaa.ui.shred_page import ShredConfirmation
from kazaa.shredder import ShredCancelled
from kazaa.video_backend import DownloadOptions


class ShredPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.settings = self.folder / "shell.json"
        self.file = self.folder / "document.txt"
        self.file.write_bytes(b"Disposable UI test file")
        self.window = ShellWindow(self.settings)
        self.window.navigate("shred")
        self.window.show()
        self.app.processEvents()
        self.page = self.window.shred_page

    def tearDown(self):
        self.window.close()
        self.app.processEvents()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def _completed_download(self, path):
        job_id = path.name
        self.window.download_queue.jobs[job_id] = {
            "id": job_id, "url": "https://example.com/" + job_id,
            "title": job_id, "options": DownloadOptions(folder=str(self.folder)).to_dict(),
            "status": "completed", "percent": 100, "files": [str(path)],
            "created": 0, "completed": 0, "error": ""}
        self.window.download_queue._changed(job_id)
        return job_id

    def _reopen(self):
        self.window.close()
        self.app.processEvents()
        self.window.deleteLater()
        self.app.processEvents()
        self.window = ShellWindow(self.settings)
        self.window.navigate("shred")
        self.window.show()
        self.app.processEvents()
        self.page = self.window.shred_page

    def _row_point(self, row):
        return self.page.table.visualItemRect(self.page.table.item(row, 1)).center()

    def _right_click(self, row):
        point = self._row_point(row)
        viewport = self.page.table.viewport()
        QTest.mouseClick(viewport, Qt.RightButton, pos=point)
        event = QContextMenuEvent(QContextMenuEvent.Mouse, point, viewport.mapToGlobal(point))
        QApplication.sendEvent(viewport, event)
        self.app.processEvents()

    def test_download_deletion_modes_accumulate_without_touching_files(self):
        from kazaa.ui.video_pages import DeleteDownloadDialog
        for mode in ("entry", "file", "both"):
            path = self.folder / (mode + ".txt")
            path.write_bytes(b"Keep until explicit shredding")
            job_id = self._completed_download(path)
            with patch.object(DeleteDownloadDialog, "exec", return_value=QDialog.Accepted), \
                    patch.object(DeleteDownloadDialog, "mode", return_value=mode):
                self.window.downloaded_page._delete(job_id)
            self.assertEqual(path.read_bytes(), b"Keep until explicit shredding")
            self.assertEqual(job_id in self.window.download_queue.jobs, mode == "file")
            self.assertEqual(str(path) in self.page.targets, mode != "entry")
        self.assertEqual(self.page.table.rowCount(), 2)
        row = self.window.downloaded_page.completed_table.row_for("file.txt")
        self.assertEqual(self.window.downloaded_page.completed_table.cellWidget(row, 6).state.text(), "In Shred")
        self.assertIsNone(self.page.worker)
        self.window.download_queue.delete("file.txt", "file")
        self.assertEqual(self.page.table.rowCount(), 2)
        self._reopen()
        self.assertEqual({Path(path).name for path in self.page.targets}, {"file.txt", "both.txt"})
        self.assertIn("file.txt", self.window.download_queue.jobs)
        self.assertNotIn("both.txt", self.window.download_queue.jobs)

    def test_shredding_handed_over_file_updates_history_and_saved_queue(self):
        job_id = self._completed_download(self.file)
        self.window.download_queue.delete(job_id, "file")
        self.page.start_shredding(self.page.selected_targets())
        worker = self.page.worker
        self.assertTrue(worker.wait(5000))
        self.app.processEvents()
        self.assertFalse(self.file.exists())
        self.assertEqual(self.page.table.rowCount(), 0)
        self.assertEqual(json.loads(self.page.queue_path.read_text())["files"], [])
        self.assertTrue(self.window.download_queue.jobs[job_id]["files_deleted"])
        row = self.window.downloaded_page.completed_table.row_for(job_id)
        self.assertEqual(self.window.downloaded_page.completed_table.cellWidget(row, 6).state.text(), "File deleted")
        self._reopen()
        self.assertEqual(self.page.table.rowCount(), 0)
        self.assertTrue(self.window.download_queue.jobs[job_id]["files_deleted"])

    def test_failed_handoff_keeps_download_and_accepts_no_partial_batch(self):
        job_id = self._completed_download(self.file)
        with patch.object(self.page, "_write_pending", side_effect=OSError("Disk unavailable")):
            with self.assertRaisesRegex(OSError, "Disk unavailable"):
                self.window.download_queue.delete(job_id, "both")
        self.assertEqual(self.page.table.rowCount(), 0)
        self.assertTrue(self.file.exists())
        self.assertIn(job_id, self.window.download_queue.jobs)
        self.assertNotIn("pending_shred_files", self.window.download_queue.jobs[job_id])
        missing = self.folder / "missing.txt"
        with self.assertRaises((OSError, ValueError)):
            self.page.enqueue_files([str(self.file), str(missing)])
        self.assertEqual(self.page.table.rowCount(), 0)
        self.assertEqual(self.page.pending_downloads, {})
        self.assertFalse(self.page.queue_path.exists())

    def test_history_save_failure_leaves_files_safely_queued_and_entry_retained(self):
        job_id = self._completed_download(self.file)
        with patch.object(self.window.download_queue, "save", return_value=False):
            with self.assertRaisesRegex(OSError, "entry was kept"):
                self.window.download_queue.delete(job_id, "both")
        self.assertIn(job_id, self.window.download_queue.jobs)
        self.assertIn(str(self.file), self.page.pending_downloads)
        self.assertEqual(len(json.loads(self.page.queue_path.read_text())["files"]), 1)
        self.assertTrue(self.file.exists())
        self._reopen()
        self.assertIn(job_id, self.window.download_queue.jobs)
        self.assertIn(str(self.file), self.page.targets)

    def test_remove_from_shred_keeps_file_and_clears_pending_history(self):
        job_id = self._completed_download(self.file)
        self.window.download_queue.delete(job_id, "file")
        self.page.table.selectRow(0)
        with patch.object(self.page, "_write_pending", side_effect=OSError("Disk unavailable")):
            self.page._remove()
        self.assertEqual(self.page.table.rowCount(), 1)
        self.assertEqual(self.window.download_queue.jobs[job_id]["pending_shred_files"], [str(self.file)])
        self.page._remove()
        self.assertTrue(self.file.exists())
        self.assertEqual(self.window.download_queue.jobs[job_id]["pending_shred_files"], [])
        row = self.window.downloaded_page.completed_table.row_for(job_id)
        self.assertEqual(self.window.downloaded_page.completed_table.cellWidget(row, 6).state.text(), "100%")
        self._reopen()
        self.assertEqual(self.page.table.rowCount(), 0)

    def test_restored_changed_file_requires_confirmation_and_invalid_journal_is_kept(self):
        job_id = self._completed_download(self.file)
        self.window.download_queue.delete(job_id, "both")
        original_target = self.page.targets[str(self.file)]
        self.file.write_bytes(b"A changed file must not be silently shredded")
        self._reopen()
        self.assertEqual(self.page.targets[str(self.file)], original_target)
        self.assertEqual(self.page.table.item(0, 0).checkState(), Qt.Unchecked)
        self.assertEqual(self.page.table.cellWidget(0, 5).state.text(), "Check file")
        self.page.queue_path.write_text("Invalid saved list")
        self._reopen()
        job_id = self._completed_download(self.file)
        with self.assertRaisesRegex(OSError, "saved list was kept"):
            self.window.download_queue.delete(job_id, "both")
        self.assertEqual(self.page.queue_path.read_text(), "Invalid saved list")
        self.assertIn(job_id, self.window.download_queue.jobs)
        self.assertTrue(self.file.exists())

    def test_handoff_during_shredding_waits_for_next_batch_and_cancellation_persists(self):
        from tools.test_video_workflow import FakeWorker
        job_id = self._completed_download(self.file)
        self.window.download_queue.delete(job_id, "file")
        second = self.folder / "later-download.txt"
        second.write_bytes(b"Later download")
        later_id = self._completed_download(second)
        entered = Event()

        def cancellable(target, algorithm, cancel, progress):
            entered.set()
            if not cancel.wait(3):
                raise RuntimeError("Test cancellation timed out")
            raise ShredCancelled("Cancelled; file kept")

        with patch("kazaa.ui.shred_page.shred_file", side_effect=cancellable) as mocked:
            self.page.start_shredding(self.page.selected_targets())
            worker = self.page.worker
            self.assertTrue(entered.wait(2))
            with self.assertRaisesRegex(ValueError, "already being shredded"):
                self.window.download_queue.delete(job_id, "both")
            self.window.download_queue.delete(later_id, "both")
            self.assertEqual(self.page.table.rowCount(), 2)
            self.assertEqual(len(worker.targets), 1)
            self.assertEqual(self.page.table.cellWidget(1, 5).state.text(), "Ready")
            self.page.stop()
            self.assertTrue(worker.wait(5000))
            self.app.processEvents()
        self.assertEqual(mocked.call_count, 1)
        self.assertTrue(second.exists())
        self.assertTrue(self.file.exists())
        # Partial failed downloads must not resume while their files await shredding.
        queue = self.window.download_queue
        queue.worker_factory = FakeWorker
        queue.jobs[job_id]["status"] = "interrupted"
        queue.save()
        queue.retry(job_id)
        self.assertEqual(queue.workers, {})
        self._reopen()
        self.assertEqual(self.page.table.rowCount(), 2)
        self.assertEqual(self.window.download_queue.jobs[job_id]["status"], "stopped")
        self.assertEqual(self.window.download_queue.workers, {})

    def test_explorer_drop_adds_checked_file_and_ignores_duplicate(self):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(self.file))])
        enter = QDragEnterEvent(self.page.table.rect().center(), Qt.CopyAction | Qt.MoveAction,
                                mime, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(self.page.table.viewport(), enter)
        self.assertTrue(enter.isAccepted())
        drop = QDropEvent(QPointF(self.page.table.rect().center()), Qt.CopyAction | Qt.MoveAction,
                         mime, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(self.page.table.viewport(), drop)
        self.assertTrue(drop.isAccepted())
        self.assertEqual(drop.dropAction(), Qt.CopyAction)
        self.page.add_files([self.file])
        self.assertEqual(self.page.table.rowCount(), 1)
        self.assertEqual(self.page.table.item(0, 1).text(), "document.txt")
        self.assertEqual(self.page.table.item(0, 2).text(), "TXT")
        self.assertTrue(self.page.shred_button.isEnabled())
        self.assertFalse(self.page.table.empty.isVisible())

    def test_selection_removal_and_algorithm_persistence(self):
        self.page.add_files([self.file])
        QTest.mouseClick(self.page.table.master, Qt.LeftButton)
        self.assertFalse(self.page.shred_button.isEnabled())
        QTest.mouseClick(self.page.table.master, Qt.LeftButton)
        self.assertTrue(self.page.shred_button.isEnabled())
        self.page.algorithm.choices["dod"].trigger()
        saved = json.loads(self.settings.read_text())
        self.assertEqual(saved["page"], "shred")
        self.assertEqual(saved["shred_algorithm"], "dod")
        self.assertEqual(self.page.algorithm.text(), "Algorithm")
        self.assertTrue(self.page.algorithm.choices["dod"].isChecked())
        self.assertNotIn(str(self.file), self.settings.read_text())
        self.page.table.selectRow(0)
        QTest.keyClick(self.page.table, Qt.Key_Delete)
        self.assertEqual(self.page.table.rowCount(), 0)
        self.assertEqual(self.file.read_bytes(), b"Disposable UI test file")

    def test_cancel_confirmation_does_not_start_worker(self):
        self.page.add_files([self.file])
        with patch.object(ShredConfirmation, "exec", return_value=QDialog.Rejected):
            self.page._confirm_shred()
        self.assertIsNone(self.page.worker)
        self.assertTrue(self.file.exists())

    def test_real_worker_deletes_only_checked_disposable_file(self):
        kept = self.folder / "kept.txt"
        kept.write_bytes(b"Keep this test file")
        self.page.add_files([self.file, kept])
        self.page.table.item(1, 0).setCheckState(Qt.Unchecked)
        self.page.start_shredding(self.page.selected_targets())
        self.assertFalse(self.page.table.isEnabled())
        worker = self.page.worker
        self.assertTrue(worker.wait(5000))
        self.app.processEvents()
        self.assertIsNone(self.page.worker)
        self.assertFalse(self.file.exists())
        self.assertEqual(kept.read_bytes(), b"Keep this test file")
        self.assertEqual(self.page.table.rowCount(), 1)
        self.assertEqual(self.page.table.item(0, 1).text(), "kept.txt")
        self.assertEqual(self.page.table.cellWidget(0, 5).state.text(), "Ready")
        self.assertNotIn(str(self.file), self.page.targets)
        self.assertNotIn(str(self.file), self.page.results)
        self.assertTrue(self.page.summary.isHidden())
        self.assertTrue(self.page.table.isEnabled())

    def test_rejects_folder_and_keeps_valid_files(self):
        self.page.add_files([self.folder, self.file])
        self.assertEqual(self.page.table.rowCount(), 1)
        self.assertTrue(self.page.notice.isVisible())
        self.assertIn("folders", self.page.notice.text())

    def test_cancel_worker_keeps_later_files_and_restores_controls(self):
        second = self.folder / "later.txt"
        second.write_bytes(b"Later file")
        self.page.add_files([self.file, second])
        entered = Event()

        def cancellable(target, algorithm, cancel, progress):
            entered.set()
            if not cancel.wait(3):
                raise RuntimeError("Test cancellation timed out")
            raise ShredCancelled("Cancelled; file kept")

        with patch("kazaa.ui.shred_page.shred_file", side_effect=cancellable) as mocked:
            self.page.start_shredding(self.page.selected_targets())
            worker = self.page.worker
            self.assertTrue(entered.wait(2))
            self.page.stop()
            self.assertTrue(worker.wait(5000))
            self.app.processEvents()
        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(self.page.results[str(self.file)], "cancelled")
        self.assertEqual(self.page.results[str(second)], "kept")
        self.assertTrue(self.file.exists())
        self.assertEqual(second.read_bytes(), b"Later file")
        self.assertTrue(self.page.table.isEnabled())
        self.assertTrue(self.page.shred_button.isEnabled())

    def test_close_cancels_worker_before_window_is_destroyed(self):
        self.page.add_files([self.file])
        entered = Event()

        def cancellable(target, algorithm, cancel, progress):
            entered.set()
            if not cancel.wait(3):
                raise RuntimeError("Test cancellation timed out")
            raise ShredCancelled("Cancelled; file kept")

        with patch("kazaa.ui.shred_page.shred_file", side_effect=cancellable):
            self.page.start_shredding(self.page.selected_targets())
            worker = self.page.worker
            self.assertTrue(entered.wait(2))
            self.window.close()
            self.assertTrue(worker.cancel.is_set())
            self.assertTrue(worker.wait(5000))
            self.app.processEvents()
            self.window.close()
            self.app.processEvents()
        self.assertIsNone(self.page.worker)
        self.assertFalse(self.window.isVisible())
        self.assertTrue(self.file.exists())

    def test_shred_preferences_restore(self):
        self.page.algorithm.choices["gutmann"].trigger()
        self.window.close()
        reopened = ShellWindow(self.settings)
        try:
            self.assertEqual(reopened.canvas.currentWidget(), reopened.shred_page)
            self.assertEqual(reopened.shred_page.algorithm.currentData(), "gutmann")
            self.assertEqual(reopened.shred_page.table.rowCount(), 0)
        finally:
            reopened.close()
            reopened.deleteLater()
            self.app.processEvents()

    def test_header_partial_selection_and_cell_checkbox_clicks(self):
        second = self.folder / "second.txt"
        second.write_bytes(b"Second file")
        self.page.add_files([self.file, second])
        self.assertEqual(self.page.table.master.checkState(), Qt.Checked)
        cell = self.page.table.visualItemRect(self.page.table.item(0, 0)).center()
        QTest.mouseClick(self.page.table.viewport(), Qt.LeftButton, pos=cell)
        self.assertEqual(self.page.table.item(0, 0).checkState(), Qt.Unchecked)
        self.assertEqual(self.page.table.master.checkState(), Qt.PartiallyChecked)
        QTest.mouseClick(self.page.table.master, Qt.LeftButton)
        self.assertEqual(len(self.page.selected_targets()), 2)
        QTest.mouseClick(self.page.table.master, Qt.LeftButton)
        self.assertEqual(len(self.page.selected_targets()), 0)
        QTest.mouseClick(self.page.table.viewport(), Qt.LeftButton, pos=cell)
        self.assertEqual(self.page.table.item(0, 0).checkState(), Qt.Checked)

    def test_success_removes_rows_and_restores_empty_drop_zone(self):
        self.page.add_files([self.file])
        self.page.start_shredding(self.page.selected_targets())
        worker = self.page.worker
        self.assertTrue(worker.wait(5000))
        self.app.processEvents()
        self.assertFalse(self.file.exists())
        self.assertEqual(self.page.table.rowCount(), 0)
        self.assertTrue(self.page.table.empty.isVisible())
        self.assertFalse(self.page.table.master.isEnabled())
        self.assertFalse(self.page.shred_button.isEnabled())
        self.assertTrue(self.page.summary.isHidden())

    def test_failure_retains_row_when_later_success_disappears(self):
        second = self.folder / "second.txt"
        second.write_bytes(b"Second file")
        self.page.add_files([self.file, second])
        original = self.file.read_bytes()

        def outcome(target, algorithm, cancel, progress):
            if target.path == str(self.file):
                raise OSError("Test sharing violation")
            from kazaa.shredder import shred_file
            shred_file(target, algorithm, cancel, progress)

        with patch("kazaa.ui.shred_page.shred_file", side_effect=outcome):
            self.page.start_shredding(self.page.selected_targets())
            worker = self.page.worker
            self.assertTrue(worker.wait(5000))
            self.app.processEvents()
        self.assertEqual(self.page.table.rowCount(), 1)
        status = self.page.table.cellWidget(0, 5)
        self.assertEqual(status.state.text(), "Failed")
        self.assertIn("Test sharing violation", status.toolTip())
        self.assertEqual(self.file.read_bytes(), original)
        self.assertFalse(second.exists())
        self.assertTrue(self.page.summary.isHidden())
        self.assertTrue(self.page.notice.isVisible())

    def test_progress_percentages_are_visible_and_cancellation_keeps_row(self):
        self.page.add_files([self.file])
        entered, release = Event(), Event()

        def progress_then_cancel(target, algorithm, cancel, progress):
            progress(42, "Verifying · pass 1/1")
            entered.set()
            if not release.wait(3):
                raise RuntimeError("Progress test timed out")
            raise ShredCancelled("Cancelled; file kept")

        with patch("kazaa.ui.shred_page.shred_file", side_effect=progress_then_cancel):
            self.page.start_shredding(self.page.selected_targets())
            worker = self.page.worker
            try:
                self.assertTrue(entered.wait(2))
                self.app.processEvents()
                widget = self.page.table.cellWidget(0, 5)
                self.assertEqual(widget.state.text(), "42%")
                self.assertEqual(widget.bar.value(), 42)
                self.assertTrue(widget.bar.isVisible())
                self.assertEqual(widget.toolTip(), "Verifying · pass 1/1")
                self.assertTrue(self.page.progress.isVisible())
                self.assertEqual(self.page.progress.value(), 42)
                self.assertIn("42%", self.page.summary.text())
                self.assertTrue(self.page.summary.isVisible())
                self.assertFalse(self.page.table.master.isEnabled())
            finally:
                release.set()
                self.assertTrue(worker.wait(5000))
                self.app.processEvents()
        self.assertEqual(widget.state.text(), "Cancelled")
        self.assertTrue(self.page.summary.isHidden())
        self.assertFalse(widget.bar.isVisible())
        self.assertEqual(self.page.table.rowCount(), 1)

    def test_confirmation_has_only_cancel_and_shred_and_requires_acceptance(self):
        self.page.add_files([self.file])
        dialog = ShredConfirmation(self.page.selected_targets(), self.page.algorithm.currentText(), self.window)
        dialog.show()
        self.app.processEvents()
        self.assertEqual({b.text() for b in dialog.findChildren(QPushButton)}, {"Cancel", "Shred"})
        self.assertLess(dialog.cancel_button.x(), dialog.shred_button.x())
        self.assertEqual(dialog.shred_button.property("role"), "outline")
        QTest.keyClick(dialog, Qt.Key_Escape)
        self.assertEqual(dialog.result(), QDialog.Rejected)
        dialog.deleteLater()
        with patch.object(ShredConfirmation, "exec", return_value=QDialog.Accepted), patch.object(self.page, "start_shredding") as start:
            self.page._confirm_shred()
        start.assert_called_once()

    def test_remove_clears_current_cell_and_keeps_other_files(self):
        second = self.folder / "second.txt"
        second.write_bytes(b"Second file")
        self.page.add_files([self.file, second])
        self.page.table.item(1, 0).setCheckState(Qt.Unchecked)
        self.page.table.setCurrentCell(0, 0)
        self.page.table.selectRow(0)
        QTest.keyClick(self.page.table, Qt.Key_Delete)
        self.assertEqual(self.page.table.rowCount(), 1)
        self.assertFalse(self.page.table.currentIndex().isValid())
        self.assertEqual(len(self.page.table.selectedItems()), 0)
        self.assertTrue(self.file.exists())
        self.assertTrue(second.exists())

    def test_ctrl_shift_escape_and_blank_click_match_downloads_selection(self):
        files = [self.file, self.folder / "second.txt", self.folder / "third.txt"]
        for path in files[1:]:
            path.write_bytes(b"Keep file contents")
        self.page.add_files(files)
        table = self.page.table
        QTest.mouseClick(table.viewport(), Qt.LeftButton, pos=self._row_point(0))
        QTest.mouseClick(table.viewport(), Qt.LeftButton, Qt.ControlModifier, self._row_point(2))
        self.assertEqual(set(table.selected_paths()), {str(files[0]), str(files[2])})
        QTest.mouseClick(table.viewport(), Qt.LeftButton, Qt.ControlModifier, self._row_point(2))
        self.assertEqual(table.selected_paths(), [str(files[0])])
        QTest.mouseClick(table.viewport(), Qt.LeftButton, pos=self._row_point(0))
        QTest.mouseClick(table.viewport(), Qt.LeftButton, Qt.ShiftModifier, self._row_point(2))
        self.assertEqual(set(table.selected_paths()), {str(path) for path in files})
        self.assertEqual(len(self.page.selected_targets()), 3)
        QTest.keyClick(table, Qt.Key_Escape)
        self.assertEqual(table.selected_paths(), [])
        QTest.keyClick(table, Qt.Key_Delete)
        self.assertEqual(table.rowCount(), 3)
        QTest.mouseClick(table.viewport(), Qt.LeftButton, pos=self._row_point(0))
        QTest.mouseClick(table.viewport(), Qt.LeftButton, pos=QPoint(20, table.viewport().height() - 10))
        self.assertEqual(table.selected_paths(), [])
        QTest.mouseClick(table.viewport(), Qt.LeftButton, pos=self._row_point(0))
        QTest.mouseClick(self.page.content, Qt.LeftButton, pos=QPoint(4, self.page.content.height() - 4))
        self.assertEqual(table.selected_paths(), [])

    def test_context_remove_preserves_group_and_removes_unchecked_highlighted_rows(self):
        files = [self.file, self.folder / "second.txt", self.folder / "third.txt"]
        for path in files[1:]:
            path.write_bytes(b"Keep file contents")
        self.page.add_files(files)
        table = self.page.table
        table.item(0, 0).setCheckState(Qt.Unchecked)
        QTest.mouseClick(table.viewport(), Qt.LeftButton, pos=self._row_point(0))
        QTest.mouseClick(table.viewport(), Qt.LeftButton, Qt.ControlModifier, self._row_point(2))
        self._right_click(0)
        self.assertEqual(set(table.selected_paths()), {str(files[0]), str(files[2])})
        menu = self.page._menu
        self.assertEqual([action.text() for action in menu.actions()], ["Remove"])
        self.assertTrue(menu.actions()[0].isEnabled())
        menu.actions()[0].trigger()
        menu.close()
        self.assertEqual(table.rowCount(), 1)
        self.assertEqual(table.item(0, 1).text(), "second.txt")
        self.assertTrue(all(path.is_file() for path in files))
        self.assertEqual(table.selected_paths(), [])

    def test_right_click_unselected_row_targets_only_that_row_and_keyboard_menu_works(self):
        second = self.folder / "second.txt"
        second.write_bytes(b"Keep file contents")
        self.page.add_files([self.file, second])
        self.page.table.selectRow(0)
        self._right_click(1)
        self.assertEqual(self.page.table.selected_paths(), [str(second)])
        self.page._menu.close()
        QTest.keyClick(self.page.table, Qt.Key_F10, Qt.ShiftModifier)
        menu = self.page._menu
        self.assertTrue(menu.isVisible())
        menu.actions()[0].trigger()
        menu.close()
        self.assertEqual(self.page.table.rowCount(), 1)
        self.assertEqual(self.page.table.item(0, 1).text(), self.file.name)
        self.assertTrue(second.exists())

    def test_delete_multiple_pending_entries_updates_history_and_saved_queue(self):
        second = self.folder / "second.txt"
        second.write_bytes(b"Keep file contents")
        for path in (self.file, second):
            job_id = self._completed_download(path)
            self.window.download_queue.delete(job_id, "file")
        table = self.page.table
        table.item(0, 0).setCheckState(Qt.Unchecked)
        QTest.mouseClick(table.viewport(), Qt.LeftButton, pos=self._row_point(0))
        QTest.mouseClick(table.viewport(), Qt.LeftButton, Qt.ControlModifier, self._row_point(1))
        QTest.keyClick(table, Qt.Key_Delete)
        self.assertEqual(table.rowCount(), 0)
        self.assertTrue(self.file.is_file())
        self.assertTrue(second.is_file())
        for job in self.window.download_queue.jobs.values():
            self.assertEqual(job["pending_shred_files"], [])
            self.assertFalse(job["files_deleted"])
        self.assertEqual(json.loads(self.page.queue_path.read_text())["files"], [])
        self._reopen()
        self.assertEqual(self.page.table.rowCount(), 0)

    def test_removal_is_disabled_during_shredding_even_for_an_open_menu(self):
        self.page.add_files([self.file])
        self.page.table.selectRow(0)
        menu = self.page.context_menu()
        entered = Event()

        def cancellable(target, algorithm, cancel, progress):
            entered.set()
            if not cancel.wait(3):
                raise RuntimeError("Test cancellation timed out")
            raise ShredCancelled("Cancelled; file kept")

        with patch("kazaa.ui.shred_page.shred_file", side_effect=cancellable):
            self.page.start_shredding(self.page.selected_targets())
            worker = self.page.worker
            try:
                self.assertTrue(entered.wait(2))
                self.assertFalse(self.page.context_menu().actions()[0].isEnabled())
                menu.actions()[0].trigger()
                QTest.keyClick(self.page.table, Qt.Key_Delete)
                self.assertEqual(self.page.table.rowCount(), 1)
            finally:
                self.page.stop()
                self.assertTrue(worker.wait(5000))
                self.app.processEvents()
        self.assertTrue(self.file.exists())
        menu.deleteLater()


if __name__ == "__main__":
    unittest.main()
