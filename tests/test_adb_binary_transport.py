from __future__ import annotations

import sys
import unittest

from talkback_lib.adb_device import AdbBinaryCommandFailure, AdbDevice


class AdbBinaryTransportTests(unittest.TestCase):
    def setUp(self):
        self.adb = AdbDevice(sys.executable, lambda _dev: None)

    def test_stdout_is_returned_as_exact_bytes_without_text_normalization(self):
        expected = b"line1\r\nline2\x1a\xff\x00\n"
        code = "import sys; sys.stdout.buffer.write(bytes.fromhex('" + expected.hex() + "'))"
        result = self.adb._run_adb_binary_command(
            ["-c", code], timeout=5, max_stdout_bytes=len(expected), max_stderr_bytes=8
        )
        self.assertEqual(expected, result.stdout)
        self.assertEqual(b"", result.stderr)
        self.assertEqual(0, result.returncode)

    def test_stdout_limit_is_fail_closed(self):
        code = "import sys; sys.stdout.buffer.write(b'x' * 1024)"
        with self.assertRaises(AdbBinaryCommandFailure) as raised:
            self.adb._run_adb_binary_command(
                ["-c", code], timeout=5, max_stdout_bytes=64, max_stderr_bytes=8
            )
        self.assertEqual("stdout_limit_exceeded", raised.exception.reason)
        self.assertLessEqual(len(raised.exception.stdout), 64)

    def test_timeout_is_reported_without_accepting_partial_output(self):
        code = "import sys,time; sys.stdout.buffer.write(b'partial'); sys.stdout.flush(); time.sleep(5)"
        with self.assertRaises(AdbBinaryCommandFailure) as raised:
            self.adb._run_adb_binary_command(
                ["-c", code], timeout=0.1, max_stdout_bytes=64, max_stderr_bytes=8
            )
        self.assertEqual("adb_command_timeout", raised.exception.reason)

    def test_stderr_is_bounded_and_nonzero_exit_is_rejected(self):
        code = "import sys; sys.stderr.buffer.write(b'e' * 128); sys.exit(7)"
        with self.assertRaises(AdbBinaryCommandFailure) as raised:
            self.adb._run_adb_binary_command(
                ["-c", code], timeout=5, max_stdout_bytes=64, max_stderr_bytes=16
            )
        self.assertEqual("adb_command_failed", raised.exception.reason)
        self.assertEqual(b"e" * 16, raised.exception.stderr)
        self.assertTrue(raised.exception.stderr_truncated)


if __name__ == "__main__":
    unittest.main()
