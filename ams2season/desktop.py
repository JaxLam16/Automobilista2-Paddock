"""Portable desktop launch helpers, shared by source and frozen builds."""
import sys
from pathlib import Path


def desktop_argv(argv=None, *, executable=None, frozen=None):
    """Double-click defaults to app mode and stores data beside the portable EXE."""
    args = list(sys.argv[1:] if argv is None else argv)
    frozen = getattr(sys, 'frozen', False) if frozen is None else frozen
    executable = Path(executable or sys.executable)
    if not args or args[0].startswith('--'):
        args.insert(0, 'app')
    if frozen and args[0] == 'app' and not any(a == '--root' or a.startswith('--root=') for a in args):
        args.extend(['--root', str(executable.resolve().parent)])
    return args


def shortcut_command(root=None):
    executable = Path(sys.executable)
    if getattr(sys, 'frozen', False):
        arguments = 'app' if root is None else f'app --root "{Path(root).resolve()}"'
        return executable, arguments
    pythonw = executable.with_name('pythonw.exe')
    return (pythonw if pythonw.exists() else executable), '-m ams2season app'
