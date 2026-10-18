"""Installed lap-time grammar; assessment and frequency stay in original events."""
import json
from .crew_spotter import ASSETS
from .crew_fuel import clean

COMMANDS={k:tuple(v) for k,v in json.loads((ASSETS/'laptime_speech.json').read_text(encoding='utf-8')).items()}
FOLDERS=tuple(json.loads((ASSETS/'laptime_folders.json').read_text(encoding='utf-8')))

def command_for(text):
    text=clean(text)
    return next((k for k,v in COMMANDS.items() if text in map(clean,v)),None)
