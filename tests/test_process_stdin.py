"""Regression: a Windows MCP input pipe must not reach helper processes."""
import ctypes
import os
import sys
import tempfile
import threading
import time
import unittest

from video_reader.common import run
from video_reader.vendor.runtime import run_text


@unittest.skipUnless(sys.platform == 'win32', 'Windows pipe inheritance regression')
class ProcessStdinTests(unittest.TestCase):
    def check_pending_input(self, execute):
        import msvcrt
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetStdHandle.argtypes = [wintypes.DWORD]
        kernel.GetStdHandle.restype = wintypes.HANDLE
        kernel.SetStdHandle.argtypes = [wintypes.DWORD, wintypes.HANDLE]
        kernel.SetStdHandle.restype = wintypes.BOOL
        stdin_id = -10 & 0xffffffff
        original = kernel.GetStdHandle(stdin_id)
        reader, writer = os.pipe()
        started = threading.Event()

        def consume():
            started.set()
            os.read(reader, 1)

        thread = threading.Thread(target=consume, daemon=True)
        try:
            self.assertTrue(kernel.SetStdHandle(stdin_id, msvcrt.get_osfhandle(reader)))
            thread.start()
            self.assertTrue(started.wait(1))
            time.sleep(.05)
            result = execute([sys._base_executable, '-I', '-c', 'print("ready")'])
            self.assertEqual(result.strip(), 'ready')
        finally:
            kernel.SetStdHandle(stdin_id, original)
            os.write(writer, b'x')
            thread.join(1)
            os.close(reader)
            os.close(writer)

    def test_common_does_not_inherit_pending_mcp_input(self):
        self.check_pending_input(lambda command: run(command, timeout=3))

    def test_vendor_does_not_inherit_pending_mcp_input(self):
        self.check_pending_input(lambda command: run_text(command, timeout=3).stdout)

    def test_vendor_preserves_explicit_input(self):
        with tempfile.TemporaryFile() as source:
            source.write(b'explicit input')
            source.seek(0)
            result = run_text([sys._base_executable, '-I', '-c',
                               'import sys; print(sys.stdin.read())'], stdin=source, timeout=3)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), 'explicit input')
