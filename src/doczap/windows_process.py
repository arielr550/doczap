"""Windows Job Object ownership; assign a suspended process before it can fork.

Uses documented Win32 APIs only. Popen closes the primary thread handle, so a
Toolhelp snapshot finds that thread before ResumeThread starts the renderer.
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from ctypes import wintypes as w

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
SIZE_T = ctypes.c_size_t
ULONG_PTR = ctypes.c_size_t


class BasicLimits(ctypes.Structure):
    _fields_ = [("ProcessTime", ctypes.c_int64), ("JobTime", ctypes.c_int64),
                ("LimitFlags", w.DWORD), ("MinWorkingSet", SIZE_T),
                ("MaxWorkingSet", SIZE_T), ("ActiveProcessLimit", w.DWORD),
                ("Affinity", ULONG_PTR), ("PriorityClass", w.DWORD),
                ("SchedulingClass", w.DWORD)]


class IOCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in
                ("ReadOperations", "WriteOperations", "OtherOperations",
                 "ReadBytes", "WriteBytes", "OtherBytes")]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [("Basic", BasicLimits), ("IO", IOCounters),
                ("ProcessMemory", SIZE_T), ("JobMemory", SIZE_T),
                ("PeakProcessMemory", SIZE_T), ("PeakJobMemory", SIZE_T)]


class Accounting(ctypes.Structure):
    _fields_ = [("UserTime", ctypes.c_int64), ("KernelTime", ctypes.c_int64),
                ("PeriodUserTime", ctypes.c_int64), ("PeriodKernelTime", ctypes.c_int64),
                ("PageFaults", w.DWORD), ("TotalProcesses", w.DWORD),
                ("ActiveProcesses", w.DWORD), ("TerminatedProcesses", w.DWORD)]


class ThreadEntry(ctypes.Structure):
    _fields_ = [("dwSize", w.DWORD), ("cntUsage", w.DWORD),
                ("threadID", w.DWORD), ("ownerPID", w.DWORD),
                ("basePriority", w.LONG), ("deltaPriority", w.LONG), ("flags", w.DWORD)]


for name, args, result in (
    ("CreateJobObjectW", [ctypes.c_void_p, w.LPCWSTR], w.HANDLE),
    ("SetInformationJobObject", [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD], w.BOOL),
    ("QueryInformationJobObject", [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p], w.BOOL),
    ("AssignProcessToJobObject", [w.HANDLE, w.HANDLE], w.BOOL),
    ("TerminateJobObject", [w.HANDLE, w.UINT], w.BOOL),
    ("CloseHandle", [w.HANDLE], w.BOOL),
    ("CreateToolhelp32Snapshot", [w.DWORD, w.DWORD], w.HANDLE),
    ("Thread32First", [w.HANDLE, ctypes.POINTER(ThreadEntry)], w.BOOL),
    ("Thread32Next", [w.HANDLE, ctypes.POINTER(ThreadEntry)], w.BOOL),
    ("OpenThread", [w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
    ("ResumeThread", [w.HANDLE], w.DWORD),
    ("GetDllDirectoryW", [w.DWORD, w.LPWSTR], w.DWORD),
    ("SetDllDirectoryW", [w.LPCWSTR], w.BOOL),
):
    fn = getattr(k32, name)
    fn.argtypes, fn.restype = args, result


_spawn_lock = threading.Lock()


def _check(value):
    if not value:
        raise ctypes.WinError(ctypes.get_last_error())
    return value


def _resume(pid: int) -> None:
    snapshot = k32.CreateToolhelp32Snapshot(4, 0)  # TH32CS_SNAPTHREAD
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = ThreadEntry()
        entry.dwSize = ctypes.sizeof(entry)
        found = k32.Thread32First(snapshot, ctypes.byref(entry))
        while found:
            if entry.ownerPID == pid:
                thread = _check(k32.OpenThread(2, False, entry.threadID))  # THREAD_SUSPEND_RESUME
                try:
                    if k32.ResumeThread(thread) == 0xFFFFFFFF:
                        raise ctypes.WinError(ctypes.get_last_error())
                finally:
                    k32.CloseHandle(thread)
                return
            entry.dwSize = ctypes.sizeof(entry)
            found = k32.Thread32Next(snapshot, ctypes.byref(entry))
        raise RuntimeError("Cannot find the renderer's suspended primary thread.")
    finally:
        k32.CloseHandle(snapshot)


class WindowsJob:
    def __init__(self) -> None:
        self.handle = _check(k32.CreateJobObjectW(None, None))
        limits = ExtendedLimits()
        limits.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        try:
            _check(k32.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)))
        except BaseException:
            k32.CloseHandle(self.handle)
            self.handle = None
            raise

    def start(self, command: Sequence[str], env: dict[str, str]) -> subprocess.Popen[str]:
        process = None
        try:
            with _spawn_lock:
                frozen = getattr(sys, "frozen", False)
                directory = ctypes.create_unicode_buffer(32768)
                if frozen:
                    k32.GetDllDirectoryW(len(directory), directory)
                    _check(k32.SetDllDirectoryW(None))
                try:
                    process = subprocess.Popen(
                        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True, env=env,
                        creationflags=subprocess.CREATE_NO_WINDOW | 4,  # CREATE_SUSPENDED
                    )
                finally:
                    if frozen:
                        _check(k32.SetDllDirectoryW(directory.value or None))
            _check(k32.AssignProcessToJobObject(self.handle, w.HANDLE(int(process._handle))))
            _resume(process.pid)
        except BaseException:
            if process is not None:
                process.kill()
                process.communicate(timeout=5)
            raise
        return process

    def close(self) -> None:
        if self.handle is None:
            return
        try:
            _check(k32.TerminateJobObject(self.handle, 1))
            # Wait for all descendants to stop before releasing the LO profile.
            deadline = time.monotonic() + 5
            while True:
                info = Accounting()
                _check(k32.QueryInformationJobObject(self.handle, 1, ctypes.byref(info), ctypes.sizeof(info), None))
                if info.ActiveProcesses == 0:
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError("Timed out waiting for the renderer process tree to stop.")
                time.sleep(0.02)
        finally:
            k32.CloseHandle(self.handle)
            self.handle = None
