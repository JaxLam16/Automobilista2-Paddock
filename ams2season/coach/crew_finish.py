"""Original finish folders. Selection stays in installed SessionEndMessages."""
import json
from .crew_spotter import ASSETS

FOLDERS=tuple(json.loads((ASSETS/'session_end_folders.json').read_text(encoding='utf-8')))
