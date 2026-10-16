"""Read the screen of, and inject keys into, another process's console (ctypes only).

Works for classic consoles and ConPTY terminals (VS Code, Windows Terminal) because
ConPTY keeps a real console buffer that AttachConsole can reach. Must run in a process
that has no console of its own (KeymouseGo is a windowed exe).

Elevated (Run as administrator) terminals can only be reached if this process is elevated
too; otherwise AttachConsole fails with ERROR_ACCESS_DENIED.
"""
import ctypes
import os
import threading
import time
from ctypes import wintypes

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
user32 = ctypes.WinDLL('user32', use_last_error=True)

TH32CS_SNAPPROCESS = 0x2
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
OPEN_EXISTING = 3
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
KEY_EVENT = 0x1
CTRL_C_EVENT, CTRL_BREAK_EVENT = 0, 1
ERROR_ACCESS_DENIED = 5

KEYS = {
    # name: (virtual key, character)
    'enter': (0x0D, '\r'),
    'esc': (0x1B, '\x1b'),
    'up': (0x26, '\x00'),
    'down': (0x28, '\x00'),
    'home': (0x24, '\x00'),
}
for _c in 'abcdefghijklmnopqrstuvwxyz':
    KEYS[_c] = (ord(_c.upper()), _c)
for _c in '0123456789':
    KEYS[_c] = (ord(_c), _c)


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
                ('th32ProcessID', wintypes.DWORD), ('th32DefaultHeapID', ctypes.c_size_t),
                ('th32ModuleID', wintypes.DWORD), ('cntThreads', wintypes.DWORD),
                ('th32ParentProcessID', wintypes.DWORD), ('pcPriClassBase', ctypes.c_long),
                ('dwFlags', wintypes.DWORD), ('szExeFile', wintypes.WCHAR * 260)]


class COORD(ctypes.Structure):
    _fields_ = [('X', wintypes.SHORT), ('Y', wintypes.SHORT)]


class SMALL_RECT(ctypes.Structure):
    _fields_ = [('Left', wintypes.SHORT), ('Top', wintypes.SHORT),
                ('Right', wintypes.SHORT), ('Bottom', wintypes.SHORT)]


class CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
    _fields_ = [('dwSize', COORD), ('dwCursorPosition', COORD), ('wAttributes', wintypes.WORD),
                ('srWindow', SMALL_RECT), ('dwMaximumWindowSize', COORD)]


class CHAR_INFO(ctypes.Structure):
    _fields_ = [('Char', wintypes.WCHAR), ('Attributes', wintypes.WORD)]


COMMON_LVB_TRAILING_BYTE = 0x0200


class KEY_EVENT_RECORD(ctypes.Structure):
    _fields_ = [('bKeyDown', wintypes.BOOL), ('wRepeatCount', wintypes.WORD),
                ('wVirtualKeyCode', wintypes.WORD), ('wVirtualScanCode', wintypes.WORD),
                ('uChar', wintypes.WCHAR), ('dwControlKeyState', wintypes.DWORD)]


class _EVENT_UNION(ctypes.Union):
    # Largest member of the real union is 16 bytes (KEY_EVENT_RECORD / MOUSE_EVENT_RECORD)
    _fields_ = [('KeyEvent', KEY_EVENT_RECORD), ('_pad', ctypes.c_byte * 16)]


class INPUT_RECORD(ctypes.Structure):
    _fields_ = [('EventType', wintypes.WORD), ('Event', _EVENT_UNION)]


kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                 wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.AttachConsole.argtypes = [wintypes.DWORD]
kernel32.GetConsoleWindow.restype = wintypes.HWND
kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                 wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
kernel32.GetConsoleScreenBufferInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(CONSOLE_SCREEN_BUFFER_INFO)]
kernel32.ReadConsoleOutputW.argtypes = [wintypes.HANDLE, ctypes.POINTER(CHAR_INFO), COORD, COORD,
                                        ctypes.POINTER(SMALL_RECT)]
kernel32.WriteConsoleInputW.argtypes = [wintypes.HANDLE, ctypes.POINTER(INPUT_RECORD), wintypes.DWORD,
                                        ctypes.POINTER(wintypes.DWORD)]
user32.MapVirtualKeyW.restype = wintypes.UINT
user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

_HANDLER_ROUTINE = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
_lock = threading.Lock()
_handler_ref = None


def _ctrl_handler(ctrl_type):
    # Ctrl+C / Ctrl+Break typed in the Codex terminal while we are briefly attached
    # must not kill KeymouseGo. Close/logoff events: block so the default handler
    # (ExitProcess) never runs; we detach within milliseconds anyway.
    if ctrl_type in (CTRL_C_EVENT, CTRL_BREAK_EVENT):
        return True
    while True:
        time.sleep(3600)


def _install_ctrl_handler():
    global _handler_ref
    if _handler_ref is None:
        _handler_ref = _HANDLER_ROUTINE(_ctrl_handler)
        kernel32.SetConsoleCtrlHandler(_handler_ref, True)


def list_processes(names):
    """Return [(pid, exe_name)] for processes whose exe name is in names (case-insensitive)."""
    wanted = {n.lower() for n in names}
    found = []
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE:
        return found
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() in wanted:
                found.append((entry.th32ProcessID, entry.szExeFile))
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return found


def process_path(pid):
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ''
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return ''
    finally:
        kernel32.CloseHandle(h)


class _Attached:
    """Context manager: attach to pid's console, yield (console_id, conout, conin), always detach."""

    def __init__(self, pid):
        self.pid = pid
        self.handles = []

    def __enter__(self):
        _lock.acquire()
        _install_ctrl_handler()
        if not kernel32.AttachConsole(self.pid):
            err = ctypes.get_last_error()
            _lock.release()
            raise OSError(err, f'AttachConsole({self.pid}) failed')
        try:
            console_id = int(kernel32.GetConsoleWindow() or 0)
            conout = self._open('CONOUT$')
            conin = self._open('CONIN$')
            return console_id, conout, conin
        except Exception:
            self.__exit__(None, None, None)
            raise

    def _open(self, name):
        h = kernel32.CreateFileW(name, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
                                 None, OPEN_EXISTING, 0, None)
        if h == INVALID_HANDLE_VALUE or not h:
            raise OSError(ctypes.get_last_error(), f'CreateFileW({name}) failed')
        self.handles.append(h)
        return h

    def __exit__(self, *exc):
        for h in self.handles:
            kernel32.CloseHandle(h)
        self.handles = []
        kernel32.FreeConsole()
        _lock.release()
        return False


def _read_window(conout):
    info = CONSOLE_SCREEN_BUFFER_INFO()
    if not kernel32.GetConsoleScreenBufferInfo(conout, ctypes.byref(info)):
        raise OSError(ctypes.get_last_error(), 'GetConsoleScreenBufferInfo failed')
    win = info.srWindow
    width = info.dwSize.X
    # Read row by row, cell by cell: a double-width char (CJK, emoji) occupies two cells, so
    # slicing a flat character read every `width` chars would shift all following rows.
    cells = (CHAR_INFO * width)()
    lines = []
    for y in range(win.Top, win.Bottom + 1):
        rect = SMALL_RECT(0, y, width - 1, y)
        if not kernel32.ReadConsoleOutputW(conout, cells, COORD(width, 1), COORD(0, 0), ctypes.byref(rect)):
            raise OSError(ctypes.get_last_error(), 'ReadConsoleOutputW failed')
        lines.append(''.join(c.Char for c in cells[:rect.Right + 1]
                             if not c.Attributes & COMMON_LVB_TRAILING_BYTE).rstrip())
    return lines


def read_screen(pid):
    """Return (console_id, [visible lines]) for the console that pid is attached to."""
    with _Attached(pid) as (console_id, conout, _conin):
        return console_id, _read_window(conout)


def _key_records(names):
    records = []
    for name in names:
        vk, ch = KEYS[name.lower()]
        scan = user32.MapVirtualKeyW(vk, 0)
        for down in (True, False):
            rec = INPUT_RECORD()
            rec.EventType = KEY_EVENT
            rec.Event.KeyEvent.bKeyDown = down
            rec.Event.KeyEvent.wRepeatCount = 1
            rec.Event.KeyEvent.wVirtualKeyCode = vk
            rec.Event.KeyEvent.wVirtualScanCode = scan
            rec.Event.KeyEvent.uChar = ch
            rec.Event.KeyEvent.dwControlKeyState = 0
            records.append(rec)
    return records


def send_keys(pid, names):
    """Write key down/up records for each key name straight into pid's console input (no focus needed)."""
    records = _key_records(names)
    arr = (INPUT_RECORD * len(records))(*records)
    with _Attached(pid) as (_cid, _conout, conin):
        written = wintypes.DWORD(0)
        if not kernel32.WriteConsoleInputW(conin, arr, len(records), ctypes.byref(written)):
            raise OSError(ctypes.get_last_error(), 'WriteConsoleInputW failed')
        return written.value == len(records)


def beep():
    user32.MessageBeep(0x30)  # MB_ICONWARNING


def foreground_exe():
    hwnd = user32.GetForegroundWindow()
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return os.path.basename(process_path(pid.value)).lower()
