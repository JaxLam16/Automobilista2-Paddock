"""Bundle Arrow codecs and native libraries without its development fixtures."""
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

hiddenimports = collect_submodules('pyarrow', filter=lambda name: '.tests' not in name)
datas = collect_data_files('pyarrow', excludes=['tests/**', '**/__pycache__/**'])
binaries = collect_dynamic_libs('pyarrow')
