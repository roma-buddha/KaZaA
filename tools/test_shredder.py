"""Focused shredding checks. All real writes use disposable temporary files."""
import os
from pathlib import Path
import sys
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from kazaa import shredder as s


@unittest.skipUnless(os.name == "nt", "Native Windows backend")
class ShredderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name, "sample.txt")
        self.original = b"Sensitive disposable test contents" * 100
        self.path.write_bytes(self.original)

    def tearDown(self):
        self.temp.cleanup()

    def shred(self, algorithm="single", **kwargs):
        return s.shred_file(s.inspect_file(self.path), algorithm, **kwargs)

    def test_algorithms_are_correct_byte_patterns_and_pass_counts(self):
        self.assertEqual([len(a.patterns) for a in s.ALGORITHMS], [1, 2, 3, 7, 35])
        self.assertEqual(s.GUTMANN[6], bytes.fromhex("92 49 24"))
        self.assertEqual(s.GUTMANN[28], bytes.fromhex("6d b6 db"))
        for algorithm in s.ALGORITHMS:
            with self.subTest(algorithm=algorithm.key):
                self.path.write_bytes(self.original)
                self.shred(algorithm.key)
                self.assertFalse(self.path.exists())

    def test_empty_file_is_deleted(self):
        self.path.write_bytes(b"")
        self.shred()
        self.assertFalse(self.path.exists())

    def test_named_data_stream_is_overwritten_before_deletion(self):
        stream = str(self.path) + ":private"
        Path(stream).write_bytes(b"Secret alternate stream")
        observed = []
        original_delete = s._WindowsFile.delete_verified

        def check(opened):
            for name, fd, size in opened.streams:
                os.lseek(fd, 0, os.SEEK_SET)
                self.assertEqual(os.read(fd, size), b"\0" * size)
                observed.append(name)
            original_delete(opened)

        with patch.object(s._WindowsFile, "delete_verified", check):
            self.shred()
        self.assertEqual(set(observed), {"::$DATA", ":private:$DATA"})
        self.assertFalse(self.path.exists())
        self.assertFalse(Path(stream).exists())

    def test_cancel_before_start_preserves_contents(self):
        cancelled = Event()
        cancelled.set()
        with self.assertRaises(s.ShredCancelled):
            self.shred(cancel=cancelled)
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_cancel_mid_write_keeps_file_at_original_size(self):
        cancelled = Event()
        with patch.object(s, "BLOCK_SIZE", 16):
            with self.assertRaises(s.ShredCancelled):
                self.shred(cancel=cancelled, progress=lambda *_: cancelled.set())
        self.assertEqual(self.path.stat().st_size, len(self.original))
        self.assertEqual(self.path.read_bytes()[:16], b"\0" * 16)
        self.assertEqual(self.path.read_bytes()[16:], self.original[16:])

    def test_partial_writes_are_completed_and_verified(self):
        actual_write = os.write
        calls = []

        def short_write(fd, data):
            calls.append(len(data))
            return actual_write(fd, data[:137])

        with patch.object(s.os, "write", short_write):
            self.shred()
        self.assertGreater(len(calls), 1)
        self.assertFalse(self.path.exists())

    def test_zero_write_never_deletes_or_truncates(self):
        with patch.object(s.os, "write", return_value=0):
            with self.assertRaises(s.ShredError):
                self.shred()
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_flush_failure_keeps_full_size_file(self):
        with patch.object(s.os, "fsync", side_effect=OSError("flush failed")):
            with self.assertRaises(OSError):
                self.shred()
        self.assertEqual(self.path.stat().st_size, len(self.original))

    def test_verification_failure_keeps_file(self):
        with patch.object(s.os, "read", return_value=b"x" * len(self.original)):
            with self.assertRaisesRegex(s.ShredError, "Verification failed"):
                self.shred()
        self.assertTrue(self.path.exists())

    def test_replacement_since_queueing_is_rejected(self):
        target = s.inspect_file(self.path)
        self.path.unlink()
        self.path.write_bytes(b"Unrelated replacement")
        with self.assertRaises(s.ShredError):
            s.shred_file(target, "single")
        self.assertEqual(self.path.read_bytes(), b"Unrelated replacement")

    def test_hard_link_is_rejected_without_writes(self):
        link = Path(self.temp.name, "alias.txt")
        os.link(self.path, link)
        with self.assertRaises(s.ShredError):
            s.inspect_file(self.path)
        self.assertEqual(link.read_bytes(), self.original)

    def test_junction_is_rejected(self):
        import subprocess
        directory = Path(self.temp.name, "real")
        directory.mkdir()
        (directory / "file.txt").write_bytes(b"keep me")
        junction = Path(self.temp.name, "link")
        completed = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(directory)],
                                   capture_output=True, timeout=5)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        try:
            with self.assertRaises(s.ShredError):
                s.inspect_file(junction / "file.txt")
            self.assertEqual((directory / "file.txt").read_bytes(), b"keep me")
        finally:
            junction.rmdir()

    def test_open_file_is_rejected_without_writes(self):
        target = s.inspect_file(self.path)
        with self.path.open("rb"):
            with self.assertRaises(OSError):
                s.shred_file(target, "single")
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_unknown_algorithm_is_rejected(self):
        with self.assertRaises(s.ShredError):
            self.shred("invented")
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_triple_pattern_is_continuous_across_blocks(self):
        cancelled = Event()
        with self.path.open("r+b", buffering=0) as file:
            with patch.object(s, "BLOCK_SIZE", 17):
                s._overwrite_stream(file.fileno(), len(self.original),
                    s.Algorithm("test", "test", (b"\x92\x49\x24",)), cancelled, lambda *_: None)
        expected = (b"\x92\x49\x24" * (len(self.original) // 3 + 1))[:len(self.original)]
        self.assertEqual(self.path.read_bytes(), expected)


if __name__ == "__main__":
    unittest.main()
