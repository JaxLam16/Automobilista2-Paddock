"""Archive superseded update bundles without deleting data or changing backup paths."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
LEGACY = [
    'bop_update', 'car_conversion_update', 'payload', 'preview', 'manifest.json',
    'INTEGRATION.patch', 'VALIDATION.md', 'README_INSTALL.md',
    'README_Install_Car_Conversion.md',
    'Install_Balance_of_Performance.bat', 'install_bop_update.py',
    'Install_Car_Conversion.bat', 'install_car_conversion.py',
    'Install_Donor_Baseline.bat', 'install_donor_baseline.py',
    'Install_Donor_Source_Fix.bat', 'install_donor_source_fix.py',
    'Install_Telemetry_Fixes.bat', 'install_telemetry_fixes.py',
    'Install_Weekend_RD.bat', 'install_weekend_rd.py',
    'Camaro_Diagnostics_20261007T063743.zip', 'README_Camaro_Diagnostics.txt',
    'Collect_Camaro_Diagnostics.bat', 'collect_camaro_diagnostics.py',
]
GUIDES = ['BALANCE_OF_PERFORMANCE_README.md', 'CAR_CONVERSION_README.md',
          'LIVERY_EDITOR_README.md']


def safe(path):
    resolved = path.resolve()
    if not resolved.is_relative_to(ROOT) or resolved == ROOT:
        raise ValueError(f'Path escapes workspace: {path}')
    if path.is_symlink():
        raise ValueError(f'Refusing a symlink: {path}')
    return resolved


def main():
    archive = safe(ROOT / 'archive' / ('pre-alpha-' + datetime.now().strftime('%Y%m%d-%H%M%S')))
    actions = [(ROOT / name, archive / name) for name in LEGACY if (ROOT / name).exists()]
    actions += [(ROOT / name, ROOT / 'docs' / name) for name in GUIDES if (ROOT / name).exists()]
    records = []
    for source, destination in actions:
        safe(source)
        safe(destination)
        if destination.exists():
            raise ValueError(f'Destination already exists: {destination}')
        files = sorted(source.rglob('*')) if source.is_dir() else [source]
        for file in files:
            safe(file)
            if file.is_file():
                target = destination / file.relative_to(source) if source.is_dir() else destination
                record = {'original': file.relative_to(ROOT).as_posix(),
                          'archived': target.relative_to(ROOT).as_posix(),
                          'sha256': hashlib.sha256(file.read_bytes()).hexdigest()}
                if source.name in GUIDES:
                    record['current_doc'] = record['archived']
                    record['archived'] = (archive / source.name).relative_to(ROOT).as_posix()
                records.append(record)
    archive.mkdir(parents=True)
    old_readme = ROOT / 'README.md'
    shutil.copy2(old_readme, archive / 'README.previous.md')
    records.append({'original': 'README.md',
                    'archived': (archive / 'README.previous.md').relative_to(ROOT).as_posix(),
                    'sha256': hashlib.sha256(old_readme.read_bytes()).hexdigest(), 'copied': True})
    (archive / 'cleanup-manifest.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    for source, destination in actions:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.name in GUIDES:
            shutil.copy2(source, archive / source.name)
        shutil.move(str(source), str(destination))
    for record in records:
        actual = hashlib.sha256((ROOT / record['archived']).read_bytes()).hexdigest()
        if actual != record['sha256']:
            raise RuntimeError(f"Archive verification failed: {record['archived']}")
    (archive / 'ARCHIVE.md').write_text(
        '# Historical update files\n\n'
        'Preserved before alpha packaging. These installers and payloads are superseded; '
        'do not run them to install the alpha. Some payloads represent different update versions.\n\n'
        'Original backup folders remain at the workspace root because restore guards require those paths. '
        'For an intentional historical restore, use the relevant Python installer with '
        '`--root "J:\\Tools\\AMS2\\ams2season" --restore "<original backup folder>"`; '
        'its checksum guard still applies. Do not use the archived batch launchers.\n\n'
        '`cleanup-manifest.json` maps original file locations to their preserved locations and hashes.\n',
        encoding='utf-8')
    print(json.dumps({'archive': str(archive), 'verified_files': len(records)}))


if __name__ == '__main__':
    main()
