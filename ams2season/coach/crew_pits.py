"""Installed pit-stop phrases; original event logic remains in the native host."""
import json
from .crew_fuel import clean
from .crew_spotter import ASSETS

COMMANDS={key:tuple(phrases) for key,phrases in
          json.loads((ASSETS/'pit_speech.json').read_text(encoding='utf-8')).items()}
FOLDERS=tuple(json.loads((ASSETS/'pit_folders.json').read_text(encoding='utf-8')))


def command_for(text):
    text=clean(text)
    return next((key for key,phrases in COMMANDS.items() if text in map(clean,phrases)),None)
