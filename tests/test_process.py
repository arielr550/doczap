"""Exercise real parent/child processes, without needing LibreOffice."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import Mock, patch

from doczap.process import ConversionCancelled, _wait_group, renderer_environment, run_process


def alive(pid: int) -> bool:
    if sys.platform == "darwin":
        # kill(pid, 0) can return EPERM for an exited macOS process.
        result = subprocess.run(
            ["/bin/ps", "-p", str(pid), "-o", "stat="],
            capture_output=True, text=True, timeout=2,
        )
        return bool(result.stdout.strip()) and not result.stdout.strip().startswith("Z")
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A stopped orphan can briefly remain as a zombie until the OS reaps it.
    if sys.platform == "linux":
        try:
            return Path(f"/proc/{pid}/stat").read_text().split(")", 1)[1].split()[0] != "Z"
        except (FileNotFoundError, ProcessLookupError):
            return False
    return True


class ProcessTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.pids = self.folder / "pids"
        self.script = self.folder / "renderer.py"
        self.script.write_text(
            "import os, pathlib, signal, subprocess, sys, time\n"
            "if sys.argv[1] == 'child':\n"
            "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "    pathlib.Path(sys.argv[2]).write_text(str(os.getpid()))\n"
            "    time.sleep(60)\n"
            "else:\n"
            "    child = subprocess.Popen([sys.executable, __file__, 'child', sys.argv[2]])\n"
            "    while not pathlib.Path(sys.argv[2]).exists(): time.sleep(0.01)\n"
            "    with open(sys.argv[2], 'a') as file: file.write(' ' + str(os.getpid()))\n"
            "    if sys.argv[1] == 'exit': sys.exit(0)\n"
            "    time.sleep(60)\n"
        )

    def command(self, mode="wait") -> list[str]:
        return [sys.executable, str(self.script), mode, str(self.pids)]

    def tree_ready(self) -> bool:
        try:
            return len(self.pids.read_text().split()) == 2
        except FileNotFoundError:
            return False

    def assert_tree_stopped(self) -> None:
        self.assertTrue(self.pids.exists(), "renderer did not start its child")
        pids = [int(value) for value in self.pids.read_text().split()]
        self.assertFalse([pid for pid in pids if alive(pid)])

    def test_timeout_stops_launcher_and_child_and_next_run_works(self) -> None:
        with self.assertRaises(subprocess.TimeoutExpired):
            run_process(self.command(), timeout=5, env=dict(os.environ))
        self.assert_tree_stopped()
        result = run_process([sys.executable, "-c", "print('ready')"], timeout=5, env=dict(os.environ))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "ready")

    def test_cancel_stops_launcher_and_child(self) -> None:
        cancel = threading.Event()
        def cancel_when_ready():
            deadline = time.monotonic() + 5
            while not self.tree_ready() and time.monotonic() < deadline:
                time.sleep(0.02)
            cancel.set()
        thread = threading.Thread(target=cancel_when_ready)
        thread.start()
        try:
            with self.assertRaises(ConversionCancelled):
                run_process(self.command(), timeout=10, env=dict(os.environ), cancel=cancel)
        finally:
            thread.join(timeout=5)
        self.assert_tree_stopped()

    def test_launcher_exit_does_not_leave_child_running(self) -> None:
        # Closed pipes let communicate return while a child is still alive.
        self.script.write_text(self.script.read_text().replace(
            "child = subprocess.Popen([sys.executable, __file__, 'child', sys.argv[2]])",
            "child = subprocess.Popen([sys.executable, __file__, 'child', sys.argv[2]], "
            "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)"))
        result = run_process(self.command("exit"), timeout=10, env=dict(os.environ))
        self.assertEqual(result.returncode, 0)
        self.assert_tree_stopped()

    def test_profile_is_released_after_tree_stops_and_can_be_reused(self) -> None:
        from doczap.converters.libreoffice import LibreOfficeConverter
        released = []
        @contextmanager
        def profile():
            try:
                yield self.folder
            finally:
                self.assert_tree_stopped()
                released.append(True)
        def renderer(command, **kwargs):
            return run_process(self.command(), **kwargs)
        with patch("doczap.converters.libreoffice.find_soffice", return_value=sys.executable):
            converter = LibreOfficeConverter(timeout_seconds=5)
        with patch("doczap.converters.libreoffice.libreoffice_profile", profile):
            with patch("doczap.converters.libreoffice.run_process", side_effect=renderer):
                with self.assertRaisesRegex(RuntimeError, "timed out"):
                    converter._run_soffice(Path("source.docx"), self.folder)
            with patch("doczap.converters.libreoffice.run_process", return_value=subprocess.CompletedProcess([], 0, "", "")):
                converter._run_soffice(Path("source.docx"), self.folder)
        self.assertEqual(len(released), 2)

    def test_cancel_before_start_does_not_launch(self) -> None:
        cancel = threading.Event()
        cancel.set()
        with patch("doczap.process.subprocess.Popen") as spawn:
            with self.assertRaises(ConversionCancelled):
                run_process(self.command(), timeout=5, env=dict(os.environ), cancel=cancel)
        spawn.assert_not_called()

    @unittest.skipIf(sys.platform == "win32", "Ctrl-C process signal test is POSIX")
    def test_cli_interrupt_stops_renderer_tree(self) -> None:
        runner = self.folder / "interrupt.py"
        runner.write_text(
            "import os, sys\nfrom doczap.process import run_process\n"
            "run_process(sys.argv[1:], timeout=60, env=dict(os.environ))\n")
        process = subprocess.Popen([sys.executable, str(runner), *self.command()],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 5
            while not self.tree_ready() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(self.pids.exists())
            process.send_signal(signal.SIGINT)
            _, stderr = process.communicate(timeout=10)
            self.assertNotEqual(process.returncode, 0)
            self.assertIn(b"KeyboardInterrupt", stderr)
            self.assert_tree_stopped()
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)


class EnvironmentTests(unittest.TestCase):
    def test_source_execution_preserves_environment(self) -> None:
        env = {"LD_LIBRARY_PATH": "/custom", "PATH": "/custom/bin"}
        with patch.object(sys, "frozen", False, create=True):
            self.assertEqual(renderer_environment(env), env)

    @unittest.skipIf(sys.platform in ("win32", "darwin"), "Linux library search")
    def test_frozen_execution_restores_original_library_path(self) -> None:
        env = {"LD_LIBRARY_PATH": "/bundle", "LD_LIBRARY_PATH_ORIG": "/system"}
        with patch.object(sys, "frozen", True, create=True):
            self.assertEqual(renderer_environment(env)["LD_LIBRARY_PATH"], "/system")
            self.assertNotIn("LD_LIBRARY_PATH", renderer_environment({"LD_LIBRARY_PATH": "/bundle"}))
        self.assertEqual(env["LD_LIBRARY_PATH"], "/bundle")

    def test_frozen_execution_removes_bundle_runtime_hook_paths(self) -> None:
        bundle = str(Path(tempfile.gettempdir()) / "frozen-bundle")
        custom = str(Path(tempfile.gettempdir()) / "custom")
        env = {"PATH": os.pathsep.join([bundle, str(Path(bundle) / "lib"), custom]),
               "DYLD_LIBRARY_PATH": str(Path(bundle) / "lib")}
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "_MEIPASS", bundle, create=True):
            clean = renderer_environment(env)
        self.assertEqual(clean["PATH"], custom)
        self.assertEqual(clean["DYLD_LIBRARY_PATH"], "")


@unittest.skipIf(sys.platform == "win32", "POSIX process groups")
class ProcessGroupStateTests(unittest.TestCase):
    def test_permission_error_for_exited_group_is_not_a_cleanup_failure(self) -> None:
        process = Mock(pid=123)
        snapshot = subprocess.CompletedProcess([], 0, "123 Z\n456 S\n", "")
        with patch("doczap.process.os.killpg", side_effect=PermissionError()), patch(
            "doczap.process.subprocess.run", return_value=snapshot
        ):
            self.assertTrue(_wait_group(process, 0.1))

    def test_permission_error_does_not_hide_a_live_descendant(self) -> None:
        process = Mock(pid=123)
        snapshot = subprocess.CompletedProcess([], 0, "123 Z\n123 S\n", "")
        with patch("doczap.process.os.killpg", side_effect=PermissionError()), patch(
            "doczap.process.subprocess.run", return_value=snapshot
        ):
            self.assertFalse(_wait_group(process, 0.05))
