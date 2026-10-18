"""On-demand jobs keep the previous voice usable through cancellation and failure."""
from dataclasses import replace
import json
from pathlib import Path
import threading
import time

import pytest

from ams2season.app import App
from ams2season.coach.packs import PackStore
from test_coach_packs import archive, Opener, Response
from test_coach_service import app_with_current, wait_until
from test_coach_voice import voice_batch


class PausedOpener(Opener):
    def __init__(self, body):
        super().__init__(body)
        self.entered, self.release = threading.Event(), threading.Event()

    def open(self, request, timeout):
        self.requests.append(request.full_url)
        opener = self

        class PausedResponse(Response):
            def read(self, size=-1):
                opener.entered.set()
                assert opener.release.wait(5), 'Test download was not released'
                return super().read(size)

        return PausedResponse(self.body)


def downloadable(app, root, *, paused=False):
    path, spec = archive(root, approved=True)
    spec = replace(spec, url='https://github.com/JaxLam16/Automobilista2-Paddock/releases/download/voices-v1/original-test.zip')
    opener = (PausedOpener if paused else Opener)(path.read_bytes())
    app.coach.pack_store.opener = opener
    app.coach.pack_catalogue = (spec,)
    return spec, opener


def finished(app):
    wait_until(lambda: not app.coach.status()['voice_packs']['busy'])
    return app.coach.status()


def test_download_activate_persist_and_prune_only_after_success(tmp_path):
    voice_batch(tmp_path)
    app = App(tmp_path)
    old, old_spec = archive(tmp_path, 'old-original')
    old_key = app.coach.pack_store.install(old, old_spec)
    app.coach.select_voice(old_key)
    spec, opener = downloadable(app, tmp_path, paused=True)
    try:
        before = (tmp_path/'private_coach/settings.json').read_bytes()
        state = app.route('POST', '/api/coach/voice/select', {}, {'key': spec.key})
        assert state['voice_packs']['busy'] and state['voice_packs']['selected'] == old_key
        assert opener.entered.wait(2)
        assert app.coach.voice.voice_id == 'old-original'
        assert (tmp_path/'private_coach/settings.json').read_bytes() == before
        assert (app.coach.pack_store.base/old_key).exists()
        opener.release.set()
        state = finished(app)
        assert state['voice_packs']['job']['state'] == 'complete'
        assert state['voice_packs']['selected'] == spec.key
        assert state['voice_packs']['job']['received_bytes'] == spec.archive_bytes
        assert state['voice']['voice_id'] == spec.voice_id
        assert not (app.coach.pack_store.base/old_key).exists()
        assert (tmp_path/'private_coach/samples/sample.wav').exists()
        assert json.loads((tmp_path/'private_coach/settings.json').read_text())['voice_pack'] == spec.key
        restored = App(tmp_path)
        assert restored.coach.voice_selection == spec.key
        assert restored.coach.voice.get('The car ahead is pitting.').seconds == .8
        restored.coach.close()
    finally:
        opener.release.set()
        app.coach.close()


def test_cancel_keeps_old_settings_and_allows_a_later_retry(tmp_path):
    voice_batch(tmp_path)
    app = app_with_current(tmp_path)
    app.coach.configure({'mode': 'quiet'})
    spec, opener = downloadable(app, tmp_path, paused=True)
    before = (tmp_path/'private_coach/settings.json').read_bytes()
    try:
        app.coach.select_voice(spec.key)
        assert opener.entered.wait(2)
        for operation in (lambda: app.coach.start(), lambda: app.coach.select_voice('jim-private'),
                          lambda: app.coach.configure({'voice_pack': spec.key}),
                          lambda: app.coach.configure({'reload_voice': True})):
            with pytest.raises(ValueError, match='voice change'):
                operation()
        started = time.perf_counter()
        state = app.route('POST', '/api/coach/voice/cancel', {}, {})
        assert time.perf_counter()-started < .5
        assert state['voice_packs']['job']['state'] == 'cancelling'
        opener.release.set()
        state = finished(app)
        assert state['voice_packs']['job']['state'] == 'cancelled'
        assert state['voice_packs']['selected'] == 'jim-private'
        assert (tmp_path/'private_coach/settings.json').read_bytes() == before
        assert not list(app.coach.pack_store.base.glob('.download-*'))
        assert not app.coach.pack_store.installed()
        app.coach.select_voice(spec.key)
        retried = finished(app)
        assert retried['voice_packs']['selected'] == spec.key, json.dumps(retried['voice_packs'],indent=2)
    finally:
        opener.release.set()
        app.coach.close()


def test_failed_checksum_preserves_old_voice_and_settings(tmp_path):
    voice_batch(tmp_path)
    app = App(tmp_path)
    app.coach.configure({'mode': 'coach'})
    before = (tmp_path/'private_coach/settings.json').read_bytes()
    spec, opener = downloadable(app, tmp_path)
    app.coach.pack_catalogue = (replace(spec, archive_sha256='0'*64),)
    try:
        app.coach.select_voice(app.coach.pack_catalogue[0].key)
        state = finished(app)
        assert state['voice_packs']['job']['state'] == 'failed'
        assert 'checksum' in state['voice_packs']['job']['error']
        assert state['voice_packs']['selected'] == 'jim-private' and state['voice']['clips'] == 1
        assert (tmp_path/'private_coach/settings.json').read_bytes() == before
        assert not app.coach.pack_store.installed()
    finally:
        app.coach.close()


def test_activation_write_failure_cannot_prune_previous_pack(tmp_path, monkeypatch):
    voice_batch(tmp_path)
    app = App(tmp_path)
    old, old_spec = archive(tmp_path, 'old-original')
    old_key = app.coach.pack_store.install(old, old_spec)
    app.coach.select_voice(old_key)
    spec, _ = downloadable(app, tmp_path)
    before = (tmp_path/'private_coach/settings.json').read_bytes()
    original = Path.replace

    def failed_settings(path, target):
        if path.name == 'settings.tmp':
            raise OSError('Synthetic settings write failure')
        return original(path, target)

    monkeypatch.setattr(Path, 'replace', failed_settings)
    try:
        app.coach.select_voice(spec.key)
        state = finished(app)
        assert state['voice_packs']['job']['state'] == 'failed'
        assert state['voice_packs']['selected'] == old_key
        assert app.coach.voice.voice_id == 'old-original'
        assert (app.coach.pack_store.base/old_key).exists()
        assert (tmp_path/'private_coach/settings.json').read_bytes() == before
    finally:
        app.coach.close()


def test_shutdown_during_download_never_activates_after_close(tmp_path):
    voice_batch(tmp_path)
    app = App(tmp_path)
    spec, opener = downloadable(app, tmp_path, paused=True)
    try:
        app.coach.select_voice(spec.key)
        assert opener.entered.wait(2)
        app.coach.close()
        opener.release.set()
        app.coach.pack_thread.join(timeout=3)
        assert app.coach.pack_state['state'] == 'cancelled'
        assert app.coach.voice_selection == 'jim-private'
        assert not (tmp_path/'private_coach/settings.json').exists()
        with pytest.raises(ValueError, match='shutting down'):
            app.coach.select_voice(spec.key)
    finally:
        opener.release.set()
        app.coach.close()


def test_cancel_after_install_before_activation_keeps_previous_selection(tmp_path, monkeypatch):
    voice_batch(tmp_path)
    app = App(tmp_path)
    spec, _ = downloadable(app, tmp_path)
    installed, release = threading.Event(), threading.Event()
    original = app.coach.pack_store.download

    def hold_after_install(*args, **kwargs):
        key = original(*args, **kwargs)
        installed.set()
        assert release.wait(5)
        return key

    monkeypatch.setattr(app.coach.pack_store, 'download', hold_after_install)
    try:
        app.coach.select_voice(spec.key)
        assert installed.wait(2)
        app.coach.cancel_voice()
        release.set()
        assert finished(app)['voice_packs']['job']['state'] == 'cancelled'
        assert app.coach.voice_selection == 'jim-private'
        assert not (tmp_path/'private_coach/settings.json').exists()
        # A fully verified but unused cache may survive a late cancellation.
        assert app.coach.pack_store.cache(spec.key).index
    finally:
        release.set()
        app.coach.close()


def test_status_is_offline_and_client_cannot_supply_arbitrary_download_urls(tmp_path):
    app = App(tmp_path)
    spec, opener = downloadable(app, tmp_path)
    try:
        state = app.coach.status()['voice_packs']
        assert state['available'][0]['key'] == spec.key and 'url' not in state['available'][0]
        for key in ('../recordings', spec.url, {'url': spec.url}, None):
            with pytest.raises(ValueError):
                app.coach.select_voice(key)
        assert opener.requests == [] and not app.coach.pack_store.base.exists()
        app.coach.pack_catalogue = ()
        assert app.coach.status()['voice_packs']['available'] == []
    finally:
        app.coach.close()


def test_bad_catalogue_does_not_disable_local_voice_or_other_coach_controls(tmp_path, monkeypatch):
    voice_batch(tmp_path)
    def bad_catalogue():
        raise ValueError('Synthetic malformed catalogue')
    monkeypatch.setattr(PackStore, 'catalogue', staticmethod(bad_catalogue))
    app = App(tmp_path)
    try:
        status = app.coach.configure({'mode': 'quiet'})
        assert status['voice']['clips'] == 1
        assert status['voice_packs']['available'] == []
        assert 'malformed catalogue' in status['voice_packs']['catalogue_error']
    finally:
        app.coach.close()
