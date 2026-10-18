"""Voice activation persists only verified identities; missing packs never change voice silently."""
import json

import pytest

from ams2season.app import App
from test_coach_packs import archive
from test_coach_voice import voice_batch
from test_coach_service import app_with_current


def test_select_verified_voice_persist_and_return_to_preserved_private_pilot(tmp_path):
    voice_batch(tmp_path)
    app=App(tmp_path)
    path,spec=archive(tmp_path)
    key=app.coach.pack_store.install(path,spec)
    state=app.coach.select_voice(key)
    assert state['voice']['voice_id']=='original-test'
    assert state['voice_packs']['selected']==key
    reloaded=App(tmp_path)
    assert reloaded.coach.voice.get('The car ahead is pitting.').seconds==.8
    reloaded.coach.select_voice('jim-private')
    assert reloaded.coach.voice.get('The car ahead is pitting.').seconds==1.5
    assert not (app.coach.pack_store.base/key).exists()
    assert (tmp_path/'private_coach/samples/sample.wav').exists()
    app.coach.close();reloaded.coach.close()


def test_failed_or_missing_voice_preserves_preferences_and_never_falls_back_to_jim(tmp_path):
    voice_batch(tmp_path)
    app=App(tmp_path);path,spec=archive(tmp_path);key=app.coach.pack_store.install(path,spec)
    app.coach.select_voice(key)
    settings=tmp_path/'private_coach/settings.json';before=settings.read_bytes()
    with pytest.raises((ValueError,OSError)):app.coach.select_voice('../recordings')
    assert settings.read_bytes()==before and app.coach.voice.voice_id=='original-test'
    (app.coach.pack_store.base/key/'manifest.json').write_text('{}')
    reloaded=App(tmp_path)
    assert not reloaded.coach.voice.index and reloaded.coach.voice.errors
    assert reloaded.coach.voice_selection==key
    app.coach.close();reloaded.coach.close()


def test_live_coach_refuses_voice_swap_without_touching_saved_selection(tmp_path):
    app=app_with_current(tmp_path);path,spec=archive(tmp_path);key=app.coach.pack_store.install(path,spec)
    app.coach.start()
    try:
        with pytest.raises(ValueError,match='Stop the live coach'):app.coach.select_voice(key)
        assert app.coach.voice_selection=='jim-private'
    finally:app.coach.close()
