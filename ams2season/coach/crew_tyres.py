"""Installed tyre grammar; assessments stay in the original native TyreMonitor."""
import json
from .crew_spotter import ASSETS
from .crew_fuel import clean,NUMBER_PHRASES,PHRASES

COMMANDS={k:tuple(v) for k,v in json.loads((ASSETS/'tyre_speech.json').read_text(encoding='utf-8')).items()}
FOLDERS=tuple(json.loads((ASSETS/'tyre_folders.json').read_text(encoding='utf-8')))
ALIASES=('tyre status','tire status',"what's my tyre status","what's my tire status")

def normalise(text):return clean(text).replace('tyre','tire')

def command_for(text):
    text=normalise(text)
    if text in map(normalise,ALIASES):return 'PADDOCK_TYRE_STATUS'
    for prefix in COMMANDS['HOW_MANY_LAPS_ON_TYRE_SET']:
        prefix=normalise(prefix)
        if text.startswith(prefix+' '):
            number=text[len(prefix)+1:]
            if number in NUMBER_PHRASES or number.isdigit() and 1<=int(number)<=199:
                return 'HOW_MANY_LAPS_ON_TYRE_SET'
    return next((k for k,v in COMMANDS.items() if text in map(normalise,v)),None)

def listener_phrases():
    phrases=[p for v in COMMANDS.values() for p in v]+list(ALIASES)
    phrases += [prefix+' '+PHRASES[str(n)][0] for prefix in COMMANDS['HOW_MANY_LAPS_ON_TYRE_SET'] for n in range(1,200)]
    return sorted(set(phrases+[p.replace('tire','tyre') for p in phrases]))
