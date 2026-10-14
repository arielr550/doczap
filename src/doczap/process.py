"""Run a renderer with bounded waits and ownership of its child processes."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Sequence


class ConversionCancelled(Exception):
    """The user stopped the current conversion."""


def check_cancelled(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise ConversionCancelled("Conversion cancelled.")


def renderer_environment(env: dict[str, str]) -> dict[str, str]:
    """Undo PyInstaller's library search changes for the external renderer."""
    env = env.copy()
    if not getattr(sys, "frozen", False):
        return env
    if sys.platform not in ("win32", "darwin"):
        if "LD_LIBRARY_PATH_ORIG" in env:
            env["LD_LIBRARY_PATH"] = env["LD_LIBRARY_PATH_ORIG"]
        else:
            env.pop("LD_LIBRARY_PATH", None)
    # Some runtime hooks add paths inside the frozen bundle. Do not pass those
    # to LibreOffice, which ships or installs its own libraries.
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        for key in ("PATH", "DYLD_LIBRARY_PATH"):
            if key in env:
                env[key] = os.pathsep.join(
                    item for item in env[key].split(os.pathsep)
                    if item and not os.path.abspath(item).startswith(str(bundle) + os.sep)
                    and os.path.abspath(item) != str(bundle)
                )
    return env


def _group_is_running(group: int) -> bool:
    # macOS can return EPERM for a group containing only exited/zombie
    # processes. Those processes cannot run or hold the LibreOffice profile.
    result = subprocess.run(
        ["/bin/ps", "-axo", "pgid=,stat="], capture_output=True,
        text=True, check=True, timeout=2,
    )
    return any(
        fields[0] == str(group) and not fields[1].startswith("Z")
        for line in result.stdout.splitlines()
        if len(fields := line.split()) >= 2
    )


def _wait_group(process: subprocess.Popen[str], timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        process.poll()  # Reap the launcher while children finish.
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            if not _group_is_running(process.pid):
                return True
        time.sleep(0.02)
    return False


def _stop_group(process: subprocess.Popen[str]) -> None:
    """Stop descendants and wait for the group, even after the launcher exits."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError:
        if not _group_is_running(process.pid):
            return
        raise
    if _wait_group(process, 1):
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except PermissionError:
        if not _group_is_running(process.pid):
            return
        raise
    # A child can close its captured pipes before it exits. Waiting only for
    # communicate() would release the profile while that child still exists.
    if not _wait_group(process, 5):
        raise RuntimeError("Timed out waiting for the renderer process group to stop.")


def run_process(
    command: Sequence[str], *, timeout: float, env: dict[str, str],
    cancel: threading.Event | None = None,
) -> subprocess.CompletedProcess[str]:
    """Stop the full process tree before returning, including on Ctrl-C."""
    check_cancelled(cancel)
    env = renderer_environment(env)
    job = None
    if sys.platform == "win32":
        from doczap.windows_process import WindowsJob
        job = WindowsJob()
        try:
            process = job.start(command, env)
        except BaseException:
            job.close()
            raise
    else:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=env, start_new_session=True,
        )
    deadline = time.monotonic() + timeout
    try:
        while True:
            check_cancelled(cancel)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout)
            try:
                stdout, stderr = process.communicate(timeout=min(0.1, remaining))
                check_cancelled(cancel)
                return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                continue
    finally:
        # This runs inside the caller's profile lock and temporary directory.
        try:
            if job is not None:
                job.close()
            else:
                _stop_group(process)
        finally:
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            finally:
                for pipe in (process.stdout, process.stderr):
                    if pipe is not None:
                        pipe.close()
