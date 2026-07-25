"""
Where things live, whether running from source or from a frozen executable.

PyInstaller unpacks a one-file build into a temporary directory that is deleted
on exit, so `__file__` is useless for anything the user should keep.  Everything
that needs a real location goes through here.
"""

import os
import sys

APP_NAME = 'ProjectRioCustomMusic'


def is_frozen():
    return getattr(sys, 'frozen', False)


def bundle_dir():
    """Read-only directory holding our own code and bundled data."""
    if is_frozen():
        return getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(sys.executable)))
    return os.path.dirname(os.path.abspath(__file__))


def app_dir():
    """Directory the user actually launched -- next to the .exe, or the sources.

    This is where someone would drop an ffmpeg binary to be picked up.
    """
    if is_frozen():
        exe = os.path.abspath(sys.executable)
        d = os.path.dirname(exe)
        # Inside a macOS .app the executable is buried in Contents/MacOS.
        marker = os.path.join('Contents', 'MacOS')
        if d.endswith(marker):
            outer = os.path.dirname(os.path.dirname(os.path.dirname(d)))
            return outer or d
        return d
    return os.path.dirname(os.path.abspath(__file__))


def config_dir():
    """Per-user, writable, survives an app update."""
    if sys.platform == 'win32':
        base = os.environ.get('APPDATA') or os.path.expanduser('~')
        return os.path.join(base, APP_NAME)
    if sys.platform == 'darwin':
        return os.path.join(os.path.expanduser('~'), 'Library',
                            'Application Support', APP_NAME)
    base = os.environ.get('XDG_CONFIG_HOME') or os.path.join(
        os.path.expanduser('~'), '.config')
    return os.path.join(base, 'project-rio-custom-music')


def settings_path():
    """Preferred settings location, migrating a file left beside the sources."""
    new = os.path.join(config_dir(), 'settings.json')
    if os.path.isfile(new):
        return new
    legacy = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'settings.json')
    if os.path.isfile(legacy):
        try:
            os.makedirs(config_dir(), exist_ok=True)
            with open(legacy, 'rb') as src, open(new, 'wb') as dst:
                dst.write(src.read())
            return new
        except Exception:
            return legacy
    return new


def ensure_config_dir():
    try:
        os.makedirs(config_dir(), exist_ok=True)
        return True
    except Exception:
        return False


def hide_own_console():
    """Hide the console window, but only if we created it ourselves.

    The Windows build is a console binary so that command-line use behaves
    normally -- shells wait for it, and `> file` and `| grep` work.  The cost is
    a console window when someone double-clicks it, which this removes.  A
    console inherited from an existing shell belongs to that shell, so it is
    left alone.
    """
    if sys.platform != 'win32' or not is_frozen():
        return False
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if not hwnd:
            return False
        owner = ctypes.c_uint(0)
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != os.getpid():
            return False                      # launched from someone's shell
        ctypes.windll.user32.ShowWindow(hwnd, 0)      # SW_HIDE
        return True
    except Exception:
        return False


def reattach_console():
    """On Windows, a windowed build has no stdout; borrow the parent console.

    Lets one binary serve both the double-clicked GUI and command-line use.
    Returns True if a console is usable afterwards.
    """
    if sys.platform != 'win32' or not is_frozen():
        return sys.stdout is not None
    # If the caller redirected us to a file or a pipe those handles are already
    # valid; replacing them with CONOUT$ would send the output to the console
    # instead and quietly break `> out.txt` and `| grep`.
    if sys.stdout is not None and sys.stderr is not None:
        return True
    try:
        import ctypes
        ATTACH_PARENT_PROCESS = -1
        if not ctypes.windll.kernel32.AttachConsole(ATTACH_PARENT_PROCESS):
            return False
        for name, stream, mode in (('stdout', 'CONOUT$', 'w'),
                                   ('stderr', 'CONOUT$', 'w'),
                                   ('stdin', 'CONIN$', 'r')):
            if getattr(sys, name, None) is not None:
                continue
            try:
                setattr(sys, name, open(stream, mode, buffering=1))
            except Exception:
                pass
        return sys.stdout is not None
    except Exception:
        return False
