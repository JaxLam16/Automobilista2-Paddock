"""Verified local cached speech. No model, TTS service or network dependency."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import io
import json
import math
import re
from pathlib import Path
import unicodedata
import wave
from string import Formatter


def text_key(text):
    return " ".join(unicodedata.normalize("NFKC", text).replace("’", "'").casefold().split()).rstrip(".")


def tts_estimate(text):
    """Spoken length for Crew Chief's text-to-speech: no recording exists to measure.

    About 2.6 words a second plus start-up time, a little slower than the text
    preview so a call that only just fits a straight is not sent.
    """
    if not isinstance(text,str) or not text.strip():
        return None
    return max(1.,len(text.split())/2.6+.4)


def voice_identity(value):
    if not isinstance(value,str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}',value):
        raise ValueError('Invalid engineer voice identity.')
    return value


@dataclass(frozen=True)
class Clip:
    text: str
    data: bytes
    seconds: float
    sha256: str
    id: str


RATE = 22050
FRAGMENT_MIN_S = .05
# Silence between composed fragments: within a phrase, after a comma/colon, after a sentence.
GAP_S, COMMA_S, STOP_S = .025, .2, .32
MAX_FRAGMENT_WORDS = 24


def fragment_words(text):
    """Words to match against fragments, and the pause after each one from its punctuation.
    Apostrophes and hyphens belong to the word ("that's", "forty-six")."""
    words, pauses = [], []
    for raw in text_key(text).split():
        word = raw.strip('.,:;!?"()')
        if not word:
            if pauses:
                pauses[-1] = max(pauses[-1], STOP_S if raw[-1] in '.!?' else COMMA_S)
            continue
        words.append(word)
        end = raw[-1]
        pauses.append(STOP_S if end in '.!?' else COMMA_S if end in ',:;' else 0.)
    return words, pauses


def pcm_wav(frames):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        wav.writeframes(frames)
    return output.getvalue()


def wav_duration(data, minimum=.3):
    try:
        with wave.open(io.BytesIO(data)) as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getcomptype()) != (1, 2, 22050, "NONE"):
                raise ValueError("Cached speech must be mono16-bit22050Hz PCM WAV.")
            seconds = wav.getnframes() / wav.getframerate()
            if not minimum <= seconds <= 20 or len(wav.readframes(wav.getnframes())) != wav.getnframes()*2:
                raise ValueError("Cached speech is truncated or has an invalid length.")
            return seconds
    except (wave.Error,EOFError) as exc:
        raise ValueError('Invalid private WAV: '+str(exc)) from None


class VoiceCache:
    def __init__(self, root, *, memory_limit=32 << 20, voice_id='jim-private', pack_directory=None):
        self.voice_id = voice_identity(voice_id)
        self.voice_name = 'Private Jim pilot' if voice_id=='jim-private' else voice_id
        self.base = (Path(root) / "private_coach").resolve()
        self.pack_directory = Path(pack_directory).resolve() if pack_directory else None
        if self.pack_directory and not self.pack_directory.is_relative_to(self.base/'voice-packs'):
            raise ValueError('Voice pack must stay in the private managed cache.')
        self.index = {}
        self.fragments = {}      # word sequence -> index key, for composing lines from pieces
        self.loaded = OrderedDict()
        self.bytes_loaded = 0
        self.memory_limit = memory_limit
        self.errors = []
        self.reload()

    def reload(self):
        self.index.clear()
        self.fragments.clear()
        self.loaded.clear()
        self.bytes_loaded = 0
        self.errors = []
        # Explicit private batch locations, never walk the multi-GB model/runtime.
        if self.pack_directory:
            paths = [self.pack_directory/'manifest.json']
            if not paths[0].is_file():
                self.errors.append('The selected managed voice manifest is missing.')
        elif self.voice_id=='jim-private':
            paths = [self.base / "samples" / "manifest.json"]
            paths += sorted((self.base / "voice-bank").glob("*/manifest.json"))
        else:
            paths = [self.base/'voice-packs'/self.voice_id/'manifest.json']
        # Locally generated extensions belong to this exact identity. The managed
        # downloaded pack stays immutable and retains its original checksums.
        paths.append(self.base/'voice-supplements'/self.voice_id/'manifest.json')
        for manifest in paths:
            if not manifest.is_file():
                continue
            try:
                self._index_manifest(manifest)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.errors.append(manifest.name + ": " + str(exc))

    def _index_manifest(self, manifest):
        if not manifest.resolve().is_relative_to(self.base) or manifest.stat().st_size > 4 << 20:
            raise ValueError("Voice manifest is outside the private cache or too large.")
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if data.get("private") is not True or data.get("publish_allowed") is not False:
            raise ValueError("Expected a private voice batch.")
        identity = data.get('voice_id','jim-private')
        if identity!=self.voice_id:
            if self.voice_id=='jim-private':
                return  # another voice's legacy batch must never be mixed in
            raise ValueError('The installed pack belongs to a different engineer voice.')
        name = data.get('voice_name',self.voice_name)
        if not isinstance(name,str) or not 1<=len(name)<=100 or any(ord(c)<32 for c in name):
            raise ValueError('Invalid engineer voice name.')
        staged = {}
        for entry in data["clips"]:
            text = entry["text"]
            if not isinstance(text, str) or not 1 <= len(text) <= 300:
                raise ValueError("Invalid voice script.")
            path = (manifest.parent / entry["radio"]).resolve()
            digest = entry["radio_sha256"]
            if (not path.is_relative_to(manifest.parent.resolve()) or not path.is_relative_to(self.base)
                    or path.suffix != ".wav" or path.stat().st_size > 2 << 20):
                raise ValueError("Invalid private audio path.")
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != digest:
                raise ValueError("Voice clip checksum mismatch: " + path.name)
            fragment = entry.get('fragment') is True
            seconds = wav_duration(content, FRAGMENT_MIN_S if fragment else .3)
            claimed = float(entry['seconds'])
            if not math.isfinite(claimed) or abs(seconds - claimed) > .03:
                raise ValueError("Voice duration does not match the saved PCM.")
            staged[text_key(text)] = {"path": path, "sha256": digest, "seconds": seconds,
                                      "text": text, "id": str(entry["id"]), "fragment": fragment}
        self.index.update(staged)
        for key, entry in staged.items():
            words = fragment_words(entry['text'])[0]
            if words and len(words) <= MAX_FRAGMENT_WORDS:
                # A whole-line clip can also serve as a piece; a dedicated fragment wins a tie.
                current = self.fragments.get(' '.join(words))
                if current is None or entry['fragment'] and not self.index[current].get('fragment'):
                    self.fragments[' '.join(words)] = key
        self.voice_name = name

    def plan(self, text):
        """How a line is spoken from the pack: [(index key, pause after)] covering every word,
        longest pieces first, never across a punctuation pause; None if any word is missing."""
        words, pauses = fragment_words(text)
        if not words:
            return None
        pieces, i = [], 0
        while i < len(words):
            for j in range(min(len(words), i + MAX_FRAGMENT_WORDS), i, -1):
                if j - 1 > i and any(pauses[i:j - 1]):
                    continue
                key = self.fragments.get(' '.join(words[i:j]))
                if key is not None:
                    pieces.append((key, pauses[j - 1]))
                    i = j
                    break
            else:
                return None
        return pieces

    def duration(self, text):
        entry = self.index.get(text_key(text))
        if entry and not entry.get('fragment'):
            return entry["seconds"]
        pieces = self.plan(text)
        if pieces is None:
            return None
        frames = sum(round(self.index[key]['seconds'] * RATE) for key, _ in pieces)
        frames += sum(round((pause or GAP_S) * RATE) for _, pause in pieces[:-1])
        seconds = frames / RATE
        return seconds if .3 <= seconds <= 20 else None

    def _pcm(self, key):
        clip = self._load(key)
        with wave.open(io.BytesIO(clip.data)) as wav:
            return wav.readframes(wav.getnframes())

    def get(self, text):
        key = text_key(text)
        entry = self.index.get(key)
        if entry and not entry.get('fragment'):
            return self._load(key)
        if key in self.loaded:
            self.loaded.move_to_end(key)
            return self.loaded[key]
        pieces = self.plan(text)
        if pieces is None:
            return None
        frames = []
        for n, (piece, pause) in enumerate(pieces):
            frames.append(self._pcm(piece))
            if n < len(pieces) - 1:
                frames.append(b'\0\0' * round((pause or GAP_S) * RATE))
        data = pcm_wav(b''.join(frames))
        seconds = wav_duration(data)
        digest = hashlib.sha256(data).hexdigest()
        clip = Clip(text, data, seconds, digest, 'composed:' + digest[:16])
        self._remember(key, clip)
        return clip

    def _remember(self, key, clip):
        while self.loaded and self.bytes_loaded+len(clip.data) > self.memory_limit:
            _, old = self.loaded.popitem(last=False)
            self.bytes_loaded -= len(old.data)
        if len(clip.data) <= self.memory_limit:
            self.loaded[key] = clip
            self.bytes_loaded += len(clip.data)

    def _load(self, key):
        if key in self.loaded:
            self.loaded.move_to_end(key)
            return self.loaded[key]
        entry = self.index.get(key)
        if not entry:
            return None
        content = entry["path"].read_bytes()
        if hashlib.sha256(content).hexdigest() != entry["sha256"]:
            self.index.pop(key, None)
            raise ValueError("Cached voice changed since verification.")
        clip = Clip(entry["text"], content, entry["seconds"], entry["sha256"], entry["id"])
        self._remember(key, clip)
        return clip

    def status(self):
        return {"clips": len(self.index), "fragments": len(self.fragments), "bytes_loaded": self.bytes_loaded,
                "errors": list(self.errors), 'voice_id':self.voice_id,'voice_name':self.voice_name}

    def coverage(self, rules):
        """Phrase inventory, not a claim that telemetry or a radio window qualifies."""
        from .catalogue import CATALOGUE
        result = []
        for rule in rules:
            spec = CATALOGUE[rule['id']]
            matches = set()
            # Scripted lines (briefs, answers) are composed live: always text-to-speech.
            scripted = all(re.fullmatch(r'\{[a-z_]+\}', p) for p in spec.phrases)
            for phrase in () if scripted else spec.phrases:
                # Normalize the complete template first so spaces at slot boundaries survive.
                pattern = ''.join(re.escape(literal) + ('.+?' if field else '')
                                  for literal, field, _, _ in Formatter().parse(text_key(phrase)))
                matches.update(key for key in self.index if re.fullmatch(pattern, key))
            missing = []
            if spec.code == 'X-15':
                missing = [relation for relation in ('car ahead', 'car behind', 'class leader')
                           if not any(self.duration(phrase.format(relation=relation)) is not None for phrase in spec.phrases)]
            result.append({'id':spec.code,'label':rule['label'],'sessions':rule['sessions'],
                           'matching_clips':len(matches),
                           'coverage':'none' if not matches else 'all_relations' if spec.code=='X-15' and not missing else 'partial',
                           'missing_relations':missing,
                           'note':'Exact cached wording only; slot values and repeat variants can still be missing.'})
        return result


def silence_wav():
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setparams((1, 2, 22050, 0, "NONE", "not compressed"))
        wav.writeframes(b"\0" * 2204)  #50ms, avoids speaking an expired URL via a fallback.
    return output.getvalue()
