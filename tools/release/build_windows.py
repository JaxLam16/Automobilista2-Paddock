"""Build a portable Windows alpha from an explicit, data-free source snapshot."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[2]
RELEASE_NAME = 'AMS2-Paddock-0.1.0-alpha.3-Windows'
USER_DOCS = ('QUICKSTART.md', 'ALPHA_NOTES.md', 'BALANCE_OF_PERFORMANCE_README.md',
             'CAR_CONVERSION_README.md', 'LIVERY_EDITOR_README.md', 'CHAMPIONSHIP_LIVERIES.md')
DEPENDENCIES = ('numpy', 'pandas', 'pyarrow', 'pillow', 'pyinstaller',
                'pyinstaller-hooks-contrib', 'packaging', 'python-dateutil', 'pytz', 'tzdata', 'six', 'setuptools')


def sha(path):
    with path.open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def source_files():
    """Allow package source plus setuptools' declared package data; never runtime state."""
    package = ROOT / 'ams2season'
    files = set(package.rglob('*.py'))
    project = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
    for pattern in project['tool']['setuptools']['package-data']['ams2season']:
        files.update(p for p in package.glob(pattern) if p.is_file())
    for file in files:
        if file.is_symlink() or not file.resolve().is_relative_to(package.resolve()):
            raise ValueError(f'Invalid source path: {file}')
    return sorted(files)


def collect_notices(destination):
    destination.mkdir()
    versions = {}
    for name in DEPENDENCIES:
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        versions[name] = dist.version
        license_files = [file for file in dist.files or [] if any(
            part.lower().startswith(('license', 'licence', 'copying', 'notice')) for part in file.parts)]
        for index, file in enumerate(license_files):
            source = Path(dist.locate_file(file))
            if source.is_file() and source.suffix not in ('.py', '.pyc'):
                target = destination / name / f'{index:03d}-{source.name}'
                target.parent.mkdir(exist_ok=True)
                shutil.copy2(source, target)
        # Metadata preserves attribution and license descriptions where no file is exposed.
        target = destination / name / 'PACKAGE_METADATA.txt'
        target.parent.mkdir(exist_ok=True)
        target.write_text(dist.read_text('METADATA') or str(dist.metadata), encoding='utf-8')
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if not python_license.is_file():
        raise ValueError('Python LICENSE.txt was not found; cannot assemble runtime notices.')
    shutil.copy2(python_license, destination / 'PYTHON_LICENSE.txt')
    shutil.copy2(ROOT / 'ams2season' / 'LIVERY_EDITOR_NOTICES.txt', destination / 'PCarsTools_MIT.txt')
    (destination / 'README.txt').write_text(
        'Third-party notices for the bundled Python runtime and packages.\n'
        'Additional native library notices are retained with the bundled packages under _internal.\n'
        'Paddock does not bundle AMS2 game files or mod donor files.\n', encoding='utf-8')
    return versions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'releases' / RELEASE_NAME)
    args = parser.parse_args()
    if sys.platform != 'win32' or platform.architecture()[0] != '64bit':
        raise ValueError('Build with Windows x64 Python.')
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / 'releases'):
        raise ValueError('Output must be a new folder inside this workspace releases directory.')
    zip_path = output.with_name(output.name + '.zip')
    if output.exists() or zip_path.exists():
        raise ValueError('Release already exists. Use --output with a new candidate folder.')
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    stage = ROOT / 'build' / ('windows-' + stamp)
    snapshot = stage / 'source'
    snapshot.mkdir(parents=True)
    files = source_files()
    for file in files:
        target = snapshot / file.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, target)
    entry = snapshot / 'launcher.py'
    shutil.copy2(Path(__file__).with_name('launcher.py'), entry)
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onedir', '--windowed',
               '--name', 'AMS2 Paddock', '--paths', str(snapshot),
               '--distpath', str(stage / 'dist'), '--workpath', str(stage / 'work'),
               '--specpath', str(stage), '--icon', str(snapshot / 'ams2season/assets/icon.ico'),
               '--additional-hooks-dir', str(Path(__file__).with_name('hooks'))]
    for file in files:
        relative = file.relative_to(ROOT)
        if file.suffix == '.py':
            if file.name not in ('__main__.py', '__init__.py'):
                command += ['--hidden-import', '.'.join(relative.with_suffix('').parts)]
        else:
            command += ['--add-data', str(snapshot / relative) + ';' + relative.parent.as_posix()]
    # Pandas hooks otherwise pull optional scientific/notebook stacks from the build PC.
    for optional in ('matplotlib', 'scipy', 'IPython', 'pytest', 'tkinter', 'numba',
                     'tables', 'h5py', 'openpyxl', 'lxml', 'sympy'):
        command += ['--exclude-module', optional]
    # NumPy's recent extension modules import Python helpers dynamically. Older
    # PyInstaller hooks miss some of them even though source-mode tests pass.
    for file in metadata.distribution('numpy').files or []:
        if file.suffix == '.py' and file.parts[0] == 'numpy' and not any(
                part in ('tests', 'testing', 'f2py', 'distutils', '_pyinstaller', '__pycache__')
                for part in file.parts):
            parts = list(file.with_suffix('').parts)
            if parts[-1] == '__init__':
                parts.pop()
            command += ['--hidden-import', '.'.join(parts)]
    command.append(str(entry))
    log_path = stage / 'pyinstaller.log'
    with log_path.open('w', encoding='utf-8') as log:
        result = subprocess.run(command, cwd=snapshot, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f'PyInstaller failed. See {log_path}')
    output.parent.mkdir(exist_ok=True)
    shutil.copytree(stage / 'dist' / 'AMS2 Paddock', output)
    readme = (ROOT / 'README.md').read_text(encoding='utf-8').split('## Develop from this checkout')[0]
    (output / 'README.md').write_text(readme.rstrip() + '\n', encoding='utf-8')
    (output / 'docs').mkdir()
    for name in USER_DOCS:
        shutil.copy2(ROOT / 'docs' / name, output / 'docs' / name)
    versions = collect_notices(output / 'THIRD_PARTY_NOTICES')
    info = {'version': tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version'],
            'built_utc': datetime.now(timezone.utc).isoformat(), 'python': platform.python_version(),
            'architecture': platform.machine(), 'dependencies': versions,
            'source_files': {file.relative_to(ROOT).as_posix(): sha(snapshot / file.relative_to(ROOT)) for file in files},
            'launcher_sha256': sha(entry), 'signed': False,
            'personal_data_included': False, 'game_content_included': False}
    (output / 'BUILD_INFO.json').write_text(json.dumps(info, indent=2), encoding='utf-8')
    payload = sorted(file for file in output.rglob('*') if file.is_file())
    manifest = {file.relative_to(output).as_posix(): sha(file) for file in payload}
    (output / 'FILE_MANIFEST.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file in sorted(output.rglob('*')):
            if file.is_file():
                archive.write(file, (Path(output.name) / file.relative_to(output)).as_posix())
    zip_path.with_suffix('.zip.sha256').write_text(sha(zip_path) + '  ' + zip_path.name + '\n', encoding='ascii')
    print(json.dumps({'folder': str(output), 'zip': str(zip_path), 'zip_bytes': zip_path.stat().st_size,
                      'sha256': sha(zip_path), 'build_log': str(log_path)}, indent=2))


if __name__ == '__main__':
    main()
