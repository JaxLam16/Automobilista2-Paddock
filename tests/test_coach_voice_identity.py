"""Identical sentence text in different packs must never mix engineer voices."""
import hashlib
import json
import shutil

import pytest

from ams2season.coach.voice import VoiceCache
from test_coach_voice import voice_batch,audio


def install_fixture(root,voice_id,*,claimed_id=None):
    source,_=voice_batch(root/'staging')
    target=root/'private_coach/voice-packs'/voice_id
    shutil.copytree(source,target)
    data=json.loads((target/'manifest.json').read_text())
    pcm=audio(.8)
    (target/'sample.wav').write_bytes(pcm)
    data.update(voice_id=claimed_id or voice_id,voice_name='Original test voice')
    data['clips'][0].update(seconds=.8,radio_sha256=hashlib.sha256(pcm).hexdigest())
    (target/'manifest.json').write_text(json.dumps(data))
    return target


def test_same_words_resolve_only_from_the_selected_voice(tmp_path):
    voice_batch(tmp_path)
    install_fixture(tmp_path,'original-test')
    jim=VoiceCache(tmp_path);other=VoiceCache(tmp_path,voice_id='original-test')
    text='The car ahead is pitting.'
    assert jim.get(text).seconds==1.5 and other.get(text).seconds==.8
    assert jim.get(text).sha256!=other.get(text).sha256
    assert other.status()['voice_name']=='Original test voice'
    # A missing pack cannot fall back to Jim for the same words.
    missing=VoiceCache(tmp_path,voice_id='not-installed')
    assert missing.get(text) is None and not missing.index


def test_legacy_bank_cannot_silently_add_another_voice(tmp_path):
    voice_batch(tmp_path)
    target=install_fixture(tmp_path,'original-test')
    destination=tmp_path/'private_coach/voice-bank/wrong-voice'
    shutil.copytree(target,destination)
    voice=VoiceCache(tmp_path)
    assert voice.get('The car ahead is pitting.').seconds==1.5


def test_mislabeled_pack_and_unsafe_voice_ids_fail_closed(tmp_path):
    install_fixture(tmp_path,'original-test',claimed_id='different-person')
    cache=VoiceCache(tmp_path,voice_id='original-test')
    assert not cache.index and cache.errors
    for bad in ('../samples','GP/Bono','',None):
        with pytest.raises(ValueError):VoiceCache(tmp_path,voice_id=bad)
