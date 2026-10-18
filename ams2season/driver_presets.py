"""Offline, season-labelled sources for individual championship driver names."""
from functools import lru_cache
import json
from pathlib import Path


@lru_cache(maxsize=1)
def catalogue():
    data = json.loads((Path(__file__).parent / 'assets/driver_name_presets.json').read_text(encoding='utf-8'))
    if data.get('version') != 1 or not data.get('groups'):
        raise ValueError('The driver name preset catalogue is unavailable.')
    return data
