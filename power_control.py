"""Testable countdown and platform commands; importing never performs an action."""
import math
import platform
import shutil
import subprocess
import time
import os
import sys
from datetime import datetime, timedelta


def scheduled_delay(value, now=None):
    """Return seconds until the next local HH:MM occurrence and its target."""
    now = now or datetime.now()
    try:
        parsed = datetime.strptime(value.strip(), "%H:%M")
    except ValueError:
        raise ValueError("Enter a valid local time as HH:MM (24-hour format).") from None
    target = now.replace(hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds(), target


def validate_minutes(value):
    try:
        minutes = int(str(value).strip())
    except ValueError:
        raise ValueError("Enter a whole number from 1 to 120 minutes.") from None
    if not 1 <= minutes <= 120:
        raise ValueError("Enter a whole number from 1 to 120 minutes.")
    return minutes


def power_command(action, system=None):
    if action not in ("shutdown", "restart"):
        raise ValueError("Unknown power action.")
    system = system or platform.system()
    if system == "Windows":
        executable = shutil.which("shutdown.exe")
        args = ["/s" if action == "shutdown" else "/r", "/t", "0"]
    elif system == "Linux":
        executable = shutil.which("systemctl")
        args = ["--no-ask-password", "poweroff" if action == "shutdown" else "reboot"]
    else:
        raise RuntimeError("Only Windows and Linux with systemd are supported.")
    if not executable:
        raise RuntimeError("Required system power command was not found.")
    return [executable] + args


def execute_power(command, dry_run=False):
    if dry_run:
        return "Dry run: " + " ".join(command)
    env = os.environ.copy()
    frozen = getattr(sys, "frozen", False)
    if frozen and sys.platform == "linux":
        # Host systemctl must load host libraries, not the bundled Python libraries.
        original = env.pop("LD_LIBRARY_PATH_ORIG", None)
        env.pop("LD_LIBRARY_PATH", None)
        if original is not None:
            env["LD_LIBRARY_PATH"] = original
    dll_directory = None
    if frozen and sys.platform == "win32":
        import ctypes
        dll_directory = ctypes.WinDLL("kernel32", use_last_error=True).SetDllDirectoryW
        dll_directory.argtypes = [ctypes.c_wchar_p]
        dll_directory.restype = ctypes.c_int
        if not dll_directory(None):
            raise RuntimeError("Cannot prepare system library paths for power command.")
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                errors="replace", timeout=30, check=False, env=env)
    except subprocess.TimeoutExpired:
        raise RuntimeError("Command timed out; the system action may already have been accepted.") from None
    except OSError as exc:
        raise RuntimeError("Cannot run power command: " + str(exc)) from exc
    finally:
        if dll_directory is not None:
            dll_directory(sys._MEIPASS)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip()
                           or "Power command failed (exit {}).".format(result.returncode))
    return "System accepted the power command."


class Countdown:
    """One local timer. Caller polls on the UI thread; no OS task is scheduled."""
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.deadline = None
        self.duration = 0
        self.action = None

    @property
    def active(self):
        return self.deadline is not None

    def start(self, seconds, action):
        if self.active:
            raise RuntimeError("A countdown is already active.")
        if action not in ("shutdown", "restart") or seconds <= 0:
            raise ValueError("Invalid countdown.")
        self.duration = seconds
        self.deadline = self.clock() + seconds
        self.action = action

    def snapshot(self):
        if not self.active:
            return 0, 0
        left = max(0, self.deadline - self.clock())
        return math.ceil(left), min(100, max(0, (1 - left / self.duration) * 100))

    def cancel(self):
        was_active = self.active
        self.deadline = None
        self.action = None
        return was_active

    def take_due(self):
        if not self.active or self.clock() < self.deadline:
            return None
        action = self.action
        self.cancel()
        return action


def close_windows_apps():
    """Request WM_CLOSE, without forcing or assuming that files were saved."""
    import ctypes
    import os
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetShellWindow.restype = wintypes.HWND
    user32.GetDesktopWindow.restype = wintypes.HWND
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    excluded = {user32.GetShellWindow(), user32.GetDesktopWindow()}

    @callback_type
    def callback(hwnd, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value != os.getpid() and hwnd not in excluded and user32.IsWindowVisible(hwnd):
            user32.PostMessageW(hwnd, 0x0010, 0, 0)
        return True

    if not user32.EnumWindows(callback, 0):
        raise ctypes.WinError(ctypes.get_last_error())
