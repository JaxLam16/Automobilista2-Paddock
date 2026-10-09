"""Portable launch roots and shortcut commands must survive a frozen distribution."""
from pathlib import Path
import importlib.util
import sys

from ams2season.desktop import desktop_argv, shortcut_command


def test_portable_root_uses_executable_location_not_working_directory(tmp_path, monkeypatch):
    exe = tmp_path / 'portable folder' / 'AMS2 Paddock.exe'
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert desktop_argv([], executable=exe, frozen=True) == ['app', '--root', str(exe.parent)]
    assert desktop_argv(['--no-window'], executable=exe, frozen=True) == [
        'app', '--no-window', '--root', str(exe.parent)]


def test_explicit_root_and_other_cli_commands_are_preserved():
    for args in (['app', '--root', 'custom'], ['app', '--root=custom'],
                 ['simulate', '--out', 'synthetic'], ['--help']):
        result = desktop_argv(args, frozen=True)
        if args == ['--help']:
            assert result[0] == 'app'
        else:
            assert result == args


def test_frozen_shortcut_targets_executable_without_python_module_arguments(monkeypatch, tmp_path):
    exe = tmp_path / 'AMS2 Paddock.exe'
    monkeypatch.setattr(sys, 'executable', str(exe))
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    assert shortcut_command() == (exe, 'app')
    assert shortcut_command(tmp_path) == (exe, f'app --root "{tmp_path}"')
    monkeypatch.setattr(sys, 'frozen', False)
    assert shortcut_command() == (exe, '-m ams2season app')


def test_release_allowlist_excludes_installed_data_and_includes_ui_assets():
    script = Path(__file__).resolve().parents[1] / 'tools/release/build_windows.py'
    spec = importlib.util.spec_from_file_location('release_build', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    files = module.source_files()
    assert all(file.relative_to(module.ROOT).parts[0] == 'ams2season' for file in files)
    assert not any('__pycache__' in file.parts or file.suffix in ('.parquet', '.db') for file in files)
    names = {file.name for file in files}
    assert {'app_ui.html', 'bop_editor.js', 'development_ui.js', 'replay_timing.js',
            'livery_editor.css', 'icon.ico', 'LIVERY_EDITOR_NOTICES.txt', 'desktop.py'} <= names
