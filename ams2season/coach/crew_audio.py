"""Original read-only SoundSet/English number metadata, isolated from devices."""
from __future__ import annotations

import json
from pathlib import Path
import re

from .crew_spotter import ASSETS, Spotter

DEFAULTS=json.loads((ASSETS/'audio_defaults.json').read_text(encoding='utf-8'))


class AudioMetadata(Spotter):
    host_script='audio_host.ps1'
    host_name='audio'
    defaults_file='audio_defaults.json'

    def __init__(self, *, personalisation='', settings=None, **kwargs):
        super().__init__(**kwargs)
        self.settings=json.loads(json.dumps(DEFAULTS))
        if settings:
            for key,value in settings.items():
                if key in DEFAULTS and type(value) is type(DEFAULTS[key]): self.settings[key]=value
        if self.root is not None:
            try:
                from ..crew_chief import documents_folder,discover_exe
                values=json.loads((documents_folder()/'CrewChiefV4/Profiles/Paddock.json').read_text(encoding='utf-8-sig'))['userSettings']
                for key,default in DEFAULTS.items():
                    if type(values.get(key)) is type(default): self.settings[key]=values[key]
                paths=(Path(discover_exe()).parent/'sounds_config.txt',self.sounds.root.parent/'sounds_config.txt')
                for path in paths:
                    if not path.is_file(): continue
                    for line in path.read_text(encoding='utf-8-sig').splitlines():
                        if line.strip().startswith('#'): continue
                        key,_,value=line.partition('=');key,value=key.strip(),value.strip()
                        if key in self.settings['number_config'] and value.lower() in ('true','false'):
                            self.settings['number_config'][key]=value.lower()
            except (OSError,ValueError,KeyError,TypeError): pass
        self.settings['personalisation']=personalisation
        self.personalised_folders=set()
        try:
            version=float((self.sounds.root/'sound_pack_version_info.txt').read_text().strip())
            if 0<=version<=10000: self.settings['sound_pack_version']=version
        except (OSError,ValueError): pass

    def request(self,operation, *, fragments=(),folders=(),t=0,hundredths=False,oval=False):
        result=self._request({'op':operation,'fragments':list(fragments),'folders':list(folders),
                              't':t,'hundredths':hundredths,'oval':oval})
        if result is None: raise OSError(self.error or 'Original audio metadata host is not ready.')
        if result.get('error'): raise ValueError(result['error'])
        return result

    def prepare(self,folders):
        # Keep expensive directory scans out of live safety calls and bound each
        # IPC batch. No WAV device/player or synthesizer is created by the host.
        folders=list(folders)
        for start in range(0,len(folders),24):
            result=self.request('prepare',folders=folders[start:start+24])
            self.personalised_folders.update(result.get('personalised',()))


def number_caption(name):
    """English numeric folder semantics from NumberReaderEn (no speech guessing).

    Non-numeric recordings without subtitles must keep the exact original WAV.
    """
    from .numbers import integer_words
    words={'point':'point','oh':'oh','zerozero':'zero zero','double_oh':'oh oh',
           'hundred':'hundred','hundred_and':'hundred and','thousand':'thousand',
           'thousand_and':'thousand and','minus':'minus','minute':'minute','minutes':'minutes',
           'second':'second','seconds':'seconds','tenth':'tenth','tenths':'tenths','hour':'hour','hours':'hours'}
    if name in words: return words[name]
    if re.fullmatch(r'\d{1,2}',name):
        return ('oh '+integer_words(int(name))) if len(name)==2 and name[0]=='0' else integer_words(int(name))
    if re.fullmatch(r'point\d',name):
        return 'point '+integer_words(int(name[5:]))
    m=re.fullmatch(r'(\d{1,2})point(\d)(seconds)?',name)
    if m: return integer_words(int(m[1]))+' point '+integer_words(int(m[2]))+(' seconds' if m[3] else '')
    # Hundredth and combined-minute recordings have no local subtitles. Their
    # exact lexical variants are unknown; preserve the original WAV for those.
    return None


def time_number_phrase(name):
    """Canonical AI rendering of native English time values, not a WAV transcript.

    NumberReaderEn.GetMinutesAndSecondsWithFraction selects 1_01..2_59;
    GetSecondsWithHundredths preserves two fraction digits in point00..point99.
    The tenths suffix can explicitly include 'seconds'. Values and precision
    stay in the original reader; no native time/rounding decisions are changed.
    """
    from .numbers import integer_words
    match=re.fullmatch(r'([12])_(0[1-9]|[1-5]\d)',name)
    if match:
        seconds=int(match[2])
        return integer_words(int(match[1]))+' '+('oh ' if seconds<10 else '')+integer_words(seconds)
    match=re.fullmatch(r'point(\d{2})',name)
    if match:return 'point '+' '.join(integer_words(int(n)) for n in match[1])
    match=re.fullmatch(r'point(\d)seconds',name)
    if match:return 'point '+integer_words(int(match[1]))+' seconds'
    return None
