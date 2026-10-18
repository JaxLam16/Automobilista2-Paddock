"""Original start/lap folders; no substitute event or live synthesis."""
import json
from .crew_spotter import ASSETS

FOLDERS=tuple(json.loads((ASSETS/'lapcounter_folders.json').read_text(encoding='utf-8')))
