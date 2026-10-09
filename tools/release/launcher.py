"""PyInstaller entry point. Double-click starts Paddock; CLI commands also work."""
from multiprocessing import freeze_support
import sys
from pathlib import Path
import traceback


if __name__ == '__main__':
    freeze_support()
    try:
        from ams2season.desktop import desktop_argv
        from ams2season.cli import main
        main(desktop_argv())
    except Exception:
        log = Path(sys.executable).resolve().parent / 'startup-error.log'
        detail = traceback.format_exc()
        try:
            log.write_text(detail, encoding='utf-8')
            message = f'Paddock could not start. Error details: {log}'
        except OSError:
            message = 'Paddock could not start. Extract it to a writable folder.\n\n' + detail
        if sys.platform == 'win32':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, 'AMS2 Paddock', 0x10)
        raise SystemExit(1)
