"""Original local subtitle variants rendered by the selected, cached Paddock voice.

No model or speech synthesizer runs in a safety-call path. An uncovered variant
uses its original local recording; the status panel reports incomplete coverage.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
import random
import io
import wave
import time

from .crew_spotter import CrewChiefSounds, WORDS
from .crew_position import FOLDERS as POSITION_FOLDERS
from .crew_lapcounter import FOLDERS as LAPCOUNTER_FOLDERS
from .crew_finish import FOLDERS as FINISH_FOLDERS
from .crew_timings import FOLDERS as TIMING_FOLDERS
from .crew_tyres import FOLDERS as TYRE_FOLDERS
from .crew_laptimes import FOLDERS as LAPTIME_FOLDERS
from .voice import text_key, pcm_wav, RATE


@dataclass(frozen=True)
class Phrase:
    folder: str
    filename: str
    text: str


class CrewChiefVoice:
    def __init__(self, sounds=None, *, settings=None):
        self.sounds = sounds or CrewChiefSounds()
        self.variants = {}
        self.uncaptioned = {}
        self.last = {}
        self.ready = {}
        self.prepared_for = None
        self.last_source = None
        self.errors = []
        self.settings = settings or {}
        self.native = None
        self.native_error = None
        self.personalisation = ''
        self.number_folders = ()
        self.time_numbers = {}

    def allowed(self, filename):
        return (self.settings.get('use_sweary_messages',False) or 'sweary' not in filename) and (
            not self.settings.get('block_male_sounds',False) or 'male' not in filename)

    def phrases(self, folder):
        if folder in self.variants:
            return self.variants[folder]
        # Only implemented event families can request local audio. No traversal,
        # arbitrary path, network access or modification of Crew Chief's files.
        bits = folder.split('/')
        if len(bits) != 2 or not all(b and b not in ('.','..') and Path(b).name==b
                                   and not any(ord(c)<32 for c in b) for b in bits):
            raise ValueError('Invalid Crew Chief sound folder.')
        if not (bits[0].startswith('spotter') and bits[1] in WORDS or
                bits[0] in ('engine_monitor','damage_reporting','fuel','race_time','mandatory_pit_stops','penalties','flags','conditions','rants','pearls_of_wisdom') or folder in POSITION_FOLDERS or folder in LAPCOUNTER_FOLDERS or folder in FINISH_FOLDERS or folder in TIMING_FOLDERS or folder in TYRE_FOLDERS or folder in LAPTIME_FOLDERS or bits[0]=='numbers' and all(c.isalnum() or c=='_' for c in bits[1]) or folder in ('battery/percent','battery/laps','battery/minutes','frozen_order/kilometres_per_hour','frozen_order/miles_per_hour','acknowledge/didnt_understand',
                    'acknowledge/no_data','acknowledge/yes','acknowledge/no','acknowledge/keepQuietEnabled',
                    'acknowledge/keepQuietDisabled','acknowledge/stand_by','mandatory_pit_stops/pit_this_lap')):
            raise ValueError('Unimplemented Crew Chief sound family.')
        base = (self.sounds.root/'voice'/folder).resolve()
        if not base.is_relative_to((self.sounds.root/'voice').resolve()):
            raise ValueError('Invalid Crew Chief sound path.')
        out = []
        path = base/'subtitles.csv'
        try:
            if path.is_file():
                if path.stat().st_size > 1 << 20:
                    raise ValueError('Crew Chief subtitles exceed the size limit.')
                stream = io.StringIO(path.read_text(encoding='utf-8-sig'), newline='')
                for row in csv.reader(stream):
                    if len(row) != 2:
                        continue
                    filename, text = row[0].strip(), row[1].strip()
                    if (Path(filename).name == filename and filename.lower().endswith('.wav')
                            and self.allowed(filename) and (base/filename).is_file() and 0 < len(text) <= 300
                            and not any(ord(c) < 32 for c in text)):
                        out.append(Phrase(folder, filename, text))
        except (OSError, UnicodeError, ValueError, csv.Error) as exc:
            self.errors.append(folder+': '+str(exc)[:200])
        if not out and bits[0]=='numbers':
            from .crew_audio import number_caption
            text=number_caption(bits[1])
            if text:
                out=[Phrase(folder,p.name,text) for p in sorted(base.glob('*.wav')) if self.allowed(p.name)]
        self.variants[folder] = tuple(out)
        known = {p.filename.casefold() for p in out}
        self.uncaptioned[folder] = tuple(folder+'/'+p.name for p in sorted(base.glob('*.wav'))
            if not p.name.startswith(('_', '.')) and self.allowed(p.name) and p.name.casefold() not in known)
        return self.variants[folder]

    def prepare(self, voice, folders):
        """Resolve every verified pack clip before live spotting, never Windows TTS."""
        if voice is not self.prepared_for:
            self.ready.clear()
            self.time_numbers.clear()
            self.errors.clear()
            self.prepared_for = voice
        for folder in folders:
            for phrase in self.phrases(folder):
                key = text_key(phrase.text)
                if key not in self.ready:
                    try:
                        clip = voice.get(phrase.text)
                        self.ready[key] = clip.data if clip else None
                    except (OSError, ValueError) as exc:
                        self.ready[key] = None
                        self.errors.append(str(exc)[:200])
            # These are value renderings defined by the native number-reader
            # contract, not inferred subtitles for unknown original recordings.
            from .crew_audio import time_number_phrase
            text=time_number_phrase(folder.removeprefix('numbers/')) if folder.startswith('numbers/') else None
            if text and folder not in self.time_numbers:
                try:
                    clip=voice.get(text)
                    self.time_numbers[folder]=(text,clip.data if clip else None)
                except (OSError,ValueError) as exc:
                    self.time_numbers[folder]=(text,None)
                    self.errors.append(str(exc)[:200])

    def choose(self, folder, *, selected=True, t=None):
        if self.native is not None:
            try:return self._native_render([folder],selected=selected,t=t)
            except OSError as exc:
                # A metadata transport failure must not remove urgent spotting.
                # Keep a complete unpersonalised original recording available.
                self.native_error=str(exc);self.close();selected=False
        variants = tuple(p for p in self.phrases(folder) if 'rq_prefix' not in p.filename and 'rq_suffix' not in p.filename)
        if not variants:
            numeric=self.time_numbers.get(folder) if selected else None
            if numeric and numeric[1] is not None:
                self.last_source='voice_pack'
                return numeric[0],numeric[1],self.last_source
            # A missing translation/subtitle must not remove an original warning.
            base = self.sounds.root/'voice'/folder
            files = sorted(p for p in base.glob('*.wav') if not p.name.startswith(('_','.')) and self.allowed(p.name)
                           and 'rq_prefix' not in p.name and 'rq_suffix' not in p.name)
            if not files:
                raise OSError('Original Crew Chief audio is unavailable: '+folder)
            self.last_source = 'crew_chief_recording'
            text = WORDS.get(folder.split('/')[-1], folder)
            return text, self.sounds.read_file(random.choice(files)), self.last_source
        phrase = random.choice([p for p in variants if p != self.last.get(folder)] or variants)
        self.last[folder] = phrase
        data = self.ready.get(text_key(phrase.text)) if selected else None
        if data is not None:
            self.last_source = 'voice_pack'
        else:
            self.last_source = 'crew_chief_recording'
            data = self.sounds.read_file(self.sounds.root/'voice'/folder/phrase.filename)
        return phrase.text, data, self.last_source

    def status(self, folders):
        folders = tuple(folders)
        phrases = {text_key(p.text) for folder in folders for p in self.phrases(folder)}
        missing = sorted(key for key in phrases if self.ready.get(key) is None)
        return {'variants': len(phrases), 'covered': len(phrases)-len(missing),
                'missing': missing, 'last_source': self.last_source, 'errors': list(self.errors),
                'uncaptioned_files': sum(len(self.uncaptioned.get(f, ())) for f in set(folders)),
                'uncaptioned_examples': [p for f in dict.fromkeys(folders)
                    for p in self.uncaptioned.get(f, ())][:80],
                'selection':'original_4.19.5.4' if self.native else 'legacy_variant_selection',
                'selection_error':self.native_error,
                'personalisation':self.personalisation,
                'uncaptioned_personalisation_files':len(self.personalisation_files()),
                'numeric':self._numeric_status()}

    def _numeric_status(self):
        phrases={text_key(p.text) for f in self.number_folders for p in self.phrases(f)}
        missing=sorted(key for key in phrases if self.ready.get(key) is None)
        # Files without known captions are never silently treated as AI covered.
        unknown=sum(not self.phrases(f) for f in self.number_folders)
        from .crew_audio import time_number_phrase
        times=[f for f in self.number_folders if time_number_phrase(f.removeprefix('numbers/'))]
        cached=[f for f in times if self.time_numbers.get(f,(None,None))[1] is not None]
        fallback=[f for f in self.number_folders if not self.phrases(f) and f not in cached]
        return {'variants':len(phrases),'covered':len(phrases)-len(missing),'missing':missing,
                'uncaptioned_folders':unknown,'time_values':len(times),'time_values_cached':len(cached),
                'time_values_missing':[f for f in times if f not in cached],
                'uncaptioned_fallback_folders':len(fallback),
                'time_rendering':'canonical_native_values_in_selected_cached_voice_not_original_WAV_transcripts'}

    def numeric_folders(self):
        base=self.sounds.root/'voice/numbers'
        return tuple('numbers/'+p.name for p in base.iterdir() if p.is_dir() and all(c.isalnum() or c=='_' for c in p.name)) if base.is_dir() else ()

    def personalisation_files(self):
        if not self.personalisation: return ()
        if Path(self.personalisation).name!=self.personalisation or self.personalisation in ('.','..'): return ()
        return tuple((self.sounds.root/'personalisations'/self.personalisation/'prefixes_and_suffixes').glob('*/*.wav'))

    def open_native(self,root,*,personalisation='',folders=(),voice=None):
        from .crew_audio import AudioMetadata
        self.close()
        self.personalisation=personalisation
        self.number_folders=self.numeric_folders()
        if voice is not None: self.prepare(voice,tuple(folders)+self.number_folders)
        native=AudioMetadata(root=root,sounds=self.sounds.root,personalisation=personalisation,settings=self.settings)
        native.start()
        if not native.ready.wait(5):
            self.native_error=native.error or 'Original audio metadata host did not start.';native.close();return False
        try: native.prepare(tuple(folders)+self.number_folders)
        except (OSError,ValueError) as exc:
            self.native_error=str(exc);native.close();return False
        self.native=native;self.native_error=None;return True

    def close(self):
        if self.native is not None: self.native.close();self.native=None

    def _native_render(self,fragments,*,selected,t=None):
        result=self.native.request('render',fragments=fragments,t=time.monotonic() if t is None else t)
        parts,texts,sources=[],[],set()
        for part in result['parts']:
            if 'pause_ms' in part:
                length=part['pause_ms']
                if type(length) is not int or not 0<=length<=10000: raise ValueError('Invalid original audio pause.')
                parts.append(b'\0\0'*round(length/1000*RATE));continue
            path=Path(part['file']).resolve();root=self.sounds.root.resolve()
            if not path.is_relative_to(root) or path.suffix.lower()!='.wav': raise ValueError('Invalid original audio file.')
            relative=path.relative_to(root)
            phrase=None
            if len(relative.parts)==4 and relative.parts[0]=='voice':
                folder='/'.join(relative.parts[1:3]);phrase=next((p for p in self.phrases(folder) if p.filename==path.name),None)
            data=self.ready.get(text_key(phrase.text)) if selected and phrase else None
            numeric=self.time_numbers.get(folder) if selected and not phrase and len(relative.parts)==4 and relative.parts[0]=='voice' else None
            if numeric and numeric[1] is not None:data=numeric[1]
            source='voice_pack' if data is not None else 'crew_chief_recording'
            if data is None: data=self.sounds.read_file(path)
            with wave.open(io.BytesIO(data)) as wav: parts.append(wav.readframes(wav.getnframes()))
            texts.append(phrase.text if phrase else numeric[0] if numeric and numeric[1] is not None else str(relative));sources.add(source)
        if not sources: raise ValueError('Original sound selection produced no playable audio.')
        self.last_source=next(iter(sources)) if len(sources)==1 else 'voice_pack_and_crew_chief_recording'
        return ' '.join(texts),pcm_wav(b''.join(parts)),self.last_source

    def render(self, call, voice, *, selected=True,t=None):
        """Preserve original event fragment order. No live TTS or partial replies."""
        if self.native is not None:
            return self._native_render(call['fragments'],selected=selected,t=t)
        from .numbers import integer_words
        parts, texts, sources = [], [], set()
        for item in call['fragments']:
            if isinstance(item,str) and item.startswith('insert_pause:'):
                length=item.removeprefix('insert_pause:')
                if not length.isdigit() or not 0<=int(length)<=10000: raise ValueError('Invalid original audio pause.')
                parts.append(b'\0\0'*round(int(length)/1000*RATE))
                continue
            elif isinstance(item, str):
                text, data, source = self.choose(item, selected=selected)
            elif type(item) in (int, float) and float(item).is_integer() and 0 <= item <= 999:
                text = integer_words(int(item))
                clip = voice.get(text) if selected else None
                if clip is not None:
                    data, source = clip.data, 'voice_pack'
                else:
                    _, data, source = self.choose('numbers/'+str(int(item)), selected=False)
            else:
                raise ValueError('Unsupported original engine message fragment.')
            with wave.open(io.BytesIO(data)) as wav:
                parts.append(wav.readframes(wav.getnframes()))
            texts.append(text)
            sources.add(source)
        self.last_source = next(iter(sources)) if len(sources)==1 else 'voice_pack_and_crew_chief_recording'
        gap=b'' if call.get('folders_resolved') else b'\0\0'*round(.05*RATE)
        return ' '.join(texts), pcm_wav(gap.join(parts)), self.last_source
