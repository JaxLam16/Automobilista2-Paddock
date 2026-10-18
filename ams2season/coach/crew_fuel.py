"""Installed original fuel/time phrases; calculations stay in native events."""
import json
import re
from .crew_spotter import ASSETS

PHRASES=json.loads((ASSETS/'fuel_speech.json').read_text(encoding='utf-8'))
FUEL_KEYS=('HOWS_MY_FUEL','WHATS_MY_FUEL_LEVEL','WHATS_MY_FUEL_USAGE','HOW_MUCH_FUEL_TO_END_OF_RACE',
    'SET_FUEL_STRATEGY_RISKY','SET_FUEL_STRATEGY_CAUTIOUS','SET_FUEL_STRATEGY_RESET','CALCULATE_FUEL_FOR')
COMMANDS={key:tuple(PHRASES[key]) for key in FUEL_KEYS}
TIME_COMMANDS={key:tuple(PHRASES[key]) for key in ('HOW_LONGS_LEFT','WHAT_LAP_AM_I_ON','SESSION_STATUS')}
FOLDERS=tuple(json.loads((ASSETS/'fuel_folders.json').read_text(encoding='utf-8')))
NUMBER_PHRASES={phrase.lower():int(key) for key,values in PHRASES.items() if key.isdigit() for phrase in values}
UNIT_PHRASES=tuple(p for key in ('LAP','LAPS','MINUTE','MINUTES','HOUR','HOURS') for p in PHRASES[key])

def clean(text):return ' '.join(str(text).lower().strip().rstrip('?.!').split())

def command_for(text):
    text=clean(text)
    for key,phrases in {**COMMANDS,**TIME_COMMANDS}.items():
        if key!='CALCULATE_FUEL_FOR' and text in map(clean,phrases):return key
    for prefix in COMMANDS['CALCULATE_FUEL_FOR']:
        if not text.startswith(prefix+' '):continue
        rest=text[len(prefix)+1:]
        for unit in UNIT_PHRASES:
            if rest.endswith(' '+unit):
                number=rest[:-len(unit)-1]
                if number in NUMBER_PHRASES or number.isdigit() and 1<=int(number)<=199:
                    return 'CALCULATE_FUEL_FOR'
    return None

def request_text(text):
    text=clean(text)
    return re.sub(r'\b\d+\b',lambda m:PHRASES[str(int(m[0]))][0] if 1<=int(m[0])<=199 else m[0],text)

def listener_phrases():
    fixed=[phrase for key,phrases in {**COMMANDS,**TIME_COMMANDS}.items() if key!='CALCULATE_FUEL_FOR' for phrase in phrases]
    return fixed+[prefix+' '+PHRASES[str(n)][0]+' '+unit for prefix in COMMANDS['CALCULATE_FUEL_FOR']
                  for n in range(1,200) for unit in UNIT_PHRASES]
