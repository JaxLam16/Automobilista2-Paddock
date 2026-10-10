"""Rollback a designer save if any texture, list or manifest step fails."""
from contextvars import ContextVar
from pathlib import Path
import shutil
import tempfile

_active = ContextVar('designer_transaction', default=None)


def track_write(path):
    current = _active.get()
    if current is not None:
        current.track(path)


class Transaction:
    def __init__(self, game, cache):
        self.root = Path(game.root).resolve()
        Path(cache).mkdir(parents=True, exist_ok=True)
        self.stage = tempfile.TemporaryDirectory(prefix='save-', dir=cache)
        self.before = {}

    def track(self, path):
        path = Path(path).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError('Livery writes must stay inside the selected game folder.')
        if path not in self.before:
            saved = Path(self.stage.name) / str(len(self.before)) if path.exists() else None
            if saved is not None:
                shutil.copy2(path, saved)
            self.before[path] = saved

    def __enter__(self):
        self.token = _active.set(self)
        return self

    def __exit__(self, kind, error, traceback):
        try:
            if kind is not None:
                for path, saved in reversed(list(self.before.items())):
                    if saved is None:
                        path.unlink(missing_ok=True)
                    else:
                        shutil.copy2(saved, path)
        finally:
            _active.reset(self.token)
            self.stage.cleanup()
