"""Windows console close/logoff/shutdown handling for graceful shutdown."""

from __future__ import annotations

import ctypes
import sys
import threading
from ctypes import wintypes

# Console control event types (wincon.h). CTRL+C and CTRL+BREAK stay on signals.
CTRL_CLOSE_EVENT = 2
CTRL_LOGOFF_EVENT = 5
CTRL_SHUTDOWN_EVENT = 6

GRACEFUL_CONSOLE_EVENTS = frozenset(
    {CTRL_CLOSE_EVENT, CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT}
)

# Windows allows roughly five seconds for CTRL_CLOSE handlers.
CONSOLE_HANDLER_WAIT_SECONDS = 4.5

_HANDLER_ROUTINE: ctypes._SimpleCData | None = None
_shutdown_requested: threading.Event | None = None
_cleanup_complete: threading.Event | None = None


def handle_console_control_event(
    ctrl_type: int,
    *,
    shutdown_requested: threading.Event,
    cleanup_complete: threading.Event,
    wait_timeout: float = CONSOLE_HANDLER_WAIT_SECONDS,
) -> bool:
    """Handle one console control event in the native callback path."""
    if ctrl_type not in GRACEFUL_CONSOLE_EVENTS:
        return False
    shutdown_requested.set()
    cleanup_complete.wait(timeout=wait_timeout)
    return True


def _native_console_ctrl_handler(ctrl_type: int) -> bool:
    if _shutdown_requested is None or _cleanup_complete is None:
        return False
    return handle_console_control_event(
        ctrl_type,
        shutdown_requested=_shutdown_requested,
        cleanup_complete=_cleanup_complete,
    )


def install_windows_console_shutdown_handler(
    shutdown_requested: threading.Event,
    cleanup_complete: threading.Event,
) -> None:
    """Register SetConsoleCtrlHandler for CLOSE/LOGOFF/SHUTDOWN on the main thread."""
    if sys.platform != "win32":
        return
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("Console ctrl handler must be installed from the main thread")

    global _HANDLER_ROUTINE, _shutdown_requested, _cleanup_complete
    _shutdown_requested = shutdown_requested
    _cleanup_complete = cleanup_complete

    handler_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
    _HANDLER_ROUTINE = handler_type(_native_console_ctrl_handler)
    if not ctypes.windll.kernel32.SetConsoleCtrlHandler(_HANDLER_ROUTINE, True):
        raise OSError("SetConsoleCtrlHandler failed")


def uninstall_windows_console_shutdown_handler() -> None:
    """Remove the native console control handler if it was installed."""
    global _HANDLER_ROUTINE, _shutdown_requested, _cleanup_complete
    if sys.platform != "win32":
        return
    if _HANDLER_ROUTINE is not None:
        ctypes.windll.kernel32.SetConsoleCtrlHandler(_HANDLER_ROUTINE, False)
    _HANDLER_ROUTINE = None
    _shutdown_requested = None
    _cleanup_complete = None
