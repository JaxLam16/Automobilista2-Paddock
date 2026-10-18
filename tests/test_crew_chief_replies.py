"""Voice replies: Crew Chief macros that pass the driver's answer to Paddock (V-24)."""
import json

import pytest

import sys

from ams2season import crew_chief as cc
from ams2season.crew_chief import REPLY_MACROS, REPLY_PREFIX, ReplyKeyDecoder, reply_macros
from test_crew_chief import radio, configure  # noqa: F401  (fixture)

USER_MACROS = {'macros': [
    {'name': 'request pit', 'description': 'x', 'voiceTriggers': ['request pit', 'box this lap'],
     'confirmationMessage': 'mandatory_pit_stops/pit_stop_requested',
     'commandSets': [{'description': 'AMS2 version', 'gameDefinition': 'AMS2', 'actionSequence': ['KEY_Q'],
                      'waitBetweenEachCommand': 20, 'autoExecuteStartChatMacro': False, 'autoExecuteEndChatMacro': False}]}]}


def user_macros(radio, value=USER_MACROS):
    data = ('\ufeff' + json.dumps(value, indent=4)).encode('utf-8')  # CC writes a BOM
    radio.macros_path.write_bytes(data)
    return data


def test_setup_needs_the_connection_and_crew_chief_closed(radio, monkeypatch):  # noqa: F811
    with pytest.raises(ValueError, match='connection first'):
        radio.prepare_replies()
    configure(radio)
    monkeypatch.setattr(radio, '_is_running', lambda **kwargs: True)
    with pytest.raises(ValueError, match='Close Crew Chief'):
        radio.prepare_replies()
    assert not radio.macros_path.exists()


def test_setup_adds_reply_macros_and_restores_byte_for_byte(radio):  # noqa: F811
    configure(radio)
    profile_before = radio.profile_path.read_bytes()
    macros_before = user_macros(radio)
    status = radio.prepare_replies()
    assert status['voice_replies']['configured']
    macros = json.loads(radio.macros_path.read_text(encoding='utf-8-sig'))['macros']
    assert macros[0] == USER_MACROS['macros'][0]  # the driver's own macros are untouched
    ours = {m['name']: m for m in macros[1:]}
    assert set(ours) == {REPLY_PREFIX + t for t, _ in REPLY_MACROS}
    confirm = ours[REPLY_PREFIX + 'confirm']
    assert confirm['voiceTriggers'][0] == 'confirm' and confirm['commandSets'][0]['gameDefinition'] == 'AMS2'
    # Two spare keys, no command: nothing opens a window or takes focus from the game.
    assert confirm['commandSets'][0]['actionSequence'] == ['F24', 'F13']
    assert ours[REPLY_PREFIX + 'debrief']['commandSets'][0]['actionSequence'] == ['F24', 'F20']
    assert not any('DOS_COMMAND' in json.dumps(m) for m in ours.values())
    prefs = json.loads(radio.profile_path.read_text())['userSettings']
    assert prefs['enable_command_macros'] is True and 'enable_running_dos_commands_from_command_macros' not in prefs
    # Only the Paddock profile changes: the profile it was copied from is untouched.
    assert 'enable_command_macros' not in json.loads(
        (radio.documents / 'Profiles/defaultSettings.json').read_text())['userSettings']
    assert status['voice_replies']['method'] == 'keys-v2' and not status['voice_replies']['needs_update']
    assert radio.prepare_replies()['voice_replies']['configured']  # repeat is a no-op
    restored = radio.restore_replies()
    assert not restored['voice_replies']['configured']
    assert radio.macros_path.read_bytes() == macros_before
    assert radio.profile_path.read_bytes() == profile_before


def test_restore_keeps_macros_and_settings_added_after_setup(radio):  # noqa: F811
    configure(radio)
    user_macros(radio)
    radio.prepare_replies()
    current = json.loads(radio.macros_path.read_text(encoding='utf-8-sig'))
    current['macros'].append({'name': 'my new macro', 'voiceTriggers': ['wipers'], 'commandSets': []})
    radio.macros_path.write_text(json.dumps(current))
    profile = json.loads(radio.profile_path.read_text())
    profile['userSettings']['messages_volume'] = 0.5
    radio.profile_path.write_text(json.dumps(profile))
    radio.restore_replies()
    names = [m['name'] for m in json.loads(radio.macros_path.read_text(encoding='utf-8-sig'))['macros']]
    assert names == ['request pit', 'my new macro']
    prefs = json.loads(radio.profile_path.read_text())['userSettings']
    assert prefs['messages_volume'] == 0.5 and 'enable_running_dos_commands_from_command_macros' not in prefs
    assert 'enable_command_macros' not in prefs  # it was absent before setup


def test_without_a_user_macro_file_setup_copies_defaults_and_restore_removes_it(radio):  # noqa: F811
    configure(radio)
    install = radio.exe.parent
    (install / 'saved_command_macros.json').write_text(json.dumps(USER_MACROS))
    radio.prepare_replies()
    assert [m['name'] for m in json.loads(radio.macros_path.read_text())['macros']][0] == 'request pit'
    radio.restore_replies()
    assert not radio.macros_path.exists()


def test_a_phrase_already_used_by_a_driver_macro_is_refused(radio):  # noqa: F811
    configure(radio)
    clash = {'macros': USER_MACROS['macros'] + [{'name': 'mine', 'voiceTriggers': ['Debrief'], 'commandSets': []}]}
    before = user_macros(radio, clash)
    profile = radio.profile_path.read_bytes()
    with pytest.raises(ValueError, match='debrief'):
        radio.prepare_replies()
    assert radio.macros_path.read_bytes() == before and radio.profile_path.read_bytes() == profile


def test_full_connection_restore_also_removes_replies(radio):  # noqa: F811
    original = b'{ "Server": "previous", "Channels": [] }\n'
    radio.mqtt_path.write_bytes(original)
    configure(radio)
    macros = user_macros(radio)
    radio.prepare_replies()
    radio.restore()
    assert radio.mqtt_path.read_bytes() == original and not radio.profile_path.exists()
    assert radio.macros_path.read_bytes() == macros


def press(decoder, t, *keys, scan_only=False):
    out = []
    for key in keys:
        vk, scan = (0, cc.KEY_SCAN[key]) if scan_only else (cc.KEY_VK[key], cc.KEY_SCAN[key])
        out.append(decoder.feed(scan, vk, True, t))
        out.append(decoder.feed(scan, vk, False, t + .04))
        t += .07
    return [x for x in out if x]


def test_the_key_pair_names_the_reply():
    d = ReplyKeyDecoder()
    assert press(d, 0, 'F24', 'F13') == ['confirm']
    assert press(d, 5, 'F24', 'F20') == ['debrief']
    assert press(d, 9, 'F24', 'F18', scan_only=True) == ['plan']   # only a scan code reported
    assert press(d, 12, 'F13') == []                                # no F24 first: not a reply
    assert press(d, 14, 'F24') == [] and press(d, 16, 'F13') == []  # too long after F24
    assert press(d, 20, 'F24', 'F24', 'F14') == ['negative']
    # ordinary keys pass by; a key held down (auto-repeat) is one press
    assert d.feed(0x1E, 0x41, True, 30) is None
    assert d.feed(0x76, 0x87, True, 31) is None and d.feed(0x76, 0x87, True, 31.03) is None
    assert d.feed(0x64, 0x7C, True, 31.1) == 'confirm' and d.feed(0x64, 0x7C, True, 31.13) is None
    # a different key that happens to share a scan code is not mistaken for F13
    assert press(d, 40, 'F24') == [] and d.feed(0x64, 0x41, True, 40.1) is None


def test_key_replies_are_drained_once_and_only_while_listening(radio, monkeypatch):  # noqa: F811
    configure(radio)
    user_macros(radio)
    radio.prepare_replies()
    started = []

    class Listener:
        def __init__(self, on_key):
            self.on_key, self.error = on_key, None
            started.append(self)

        def start(self):
            pass

        def is_alive(self):
            return True

        def stop(self):
            started.remove(self)

    monkeypatch.setattr(cc, 'RawKeyListener', Listener)
    monkeypatch.setattr(cc.sys, 'platform', 'win32')
    radio._on_reply_key(0x76, 0x87, True, 0)      # before Paddock listens: not an answer
    radio._on_reply_key(0x64, 0x7C, True, .07)
    assert radio.poll_replies() == [] and len(started) == 1
    for t, (scan, vk) in enumerate([(0x76, 0x87), (0x66, 0x7E), (0x76, 0x87), (0x6B, 0x83)]):
        started[0].on_key(scan, vk, True, 10 + t * .1)
        started[0].on_key(scan, vk, False, 10 + t * .1 + .04)
    assert radio.poll_replies() == ['practice1', 'debrief']
    assert radio.poll_replies() == [] and len(started) == 1     # one listener
    assert radio.status()['voice_replies']['listening']
    radio.restore_replies()
    assert started == [] and radio.poll_replies() == []


def legacy_setup(radio):
    """Turn a fresh setup into what version 1 left behind: command macros, the DOS-command
    preference on, and a receipt without a method."""
    radio.prepare_replies()
    receipt = radio.settings['replies_receipt']
    receipt.pop('method')
    receipt['profile_values']['enable_running_dos_commands_from_command_macros'] = cc.MISSING
    profile = json.loads(radio.profile_path.read_text())
    profile['userSettings']['enable_running_dos_commands_from_command_macros'] = True
    radio.profile_path.write_text(json.dumps(profile))
    macros = json.loads(radio.macros_path.read_text(encoding='utf-8-sig'))
    for m in macros['macros']:
        if m['name'].startswith(REPLY_PREFIX):
            m['commandSets'][0]['actionSequence'] = ['{DOS_COMMAND,>>"x" echo ' + m['name'].split(': ')[1] + '}']
    radio.macros_path.write_text(json.dumps(macros))
    radio._save()


def test_a_version_one_setup_is_upgraded_in_place(radio):  # noqa: F811
    configure(radio)
    profile_before = radio.profile_path.read_bytes()
    macros_before = user_macros(radio)
    legacy_setup(radio)
    status = radio.status()['voice_replies']
    assert status['configured'] and status['needs_update'] and status['method'] == 'command-v1'
    status = radio.prepare_replies()['voice_replies']
    assert status['method'] == 'keys-v2' and not status['needs_update']
    prefs = json.loads(radio.profile_path.read_text())['userSettings']
    assert 'enable_running_dos_commands_from_command_macros' not in prefs   # back to how it was
    macros = json.loads(radio.macros_path.read_text(encoding='utf-8-sig'))['macros']
    assert macros[0] == USER_MACROS['macros'][0]
    assert not any('DOS_COMMAND' in json.dumps(m) for m in macros)
    assert len([m for m in macros if m['name'].startswith(REPLY_PREFIX)]) == len(REPLY_MACROS)
    radio.restore_replies()
    assert radio.macros_path.read_bytes() == macros_before and radio.profile_path.read_bytes() == profile_before


def test_version_one_reply_file_is_still_read_until_the_update(radio):  # noqa: F811
    configure(radio)
    user_macros(radio)
    legacy_setup(radio)
    path = radio.dir / 'voice_replies.txt'
    path.write_bytes(b'confirm\r\n')       # written before Paddock started: not an answer
    assert radio.poll_replies() == []
    with path.open('ab') as f:
        f.write(b'practice2\r\nrm -rf\r\nnegat')  # cmd writes CRLF; last line incomplete
    assert radio.poll_replies() == ['practice2']
    with path.open('ab') as f:
        f.write(b'ive\r\n')
    assert radio.poll_replies() == ['negative']
    path.write_bytes(b'debrief\r\n')  # truncated or replaced: read from the start
    assert radio.poll_replies() == ['debrief']


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows raw input')
def test_the_raw_input_listener_starts_and_stops_on_windows():
    listener = cc.RawKeyListener(lambda *args: None)
    listener.start()
    assert listener.ready.wait(5)
    assert listener.error is None and listener.is_alive()
    listener.stop()
    assert not listener.is_alive() and listener.error is None


def test_reply_phrases_are_unique():
    phrases = [p.lower() for _, group in REPLY_MACROS for p in group]
    assert len(phrases) == len(set(phrases))
    assert 'yes' not in phrases and 'say again' not in phrases  # Crew Chief's own commands


def test_spotter_only_turns_off_overlapping_calls_in_the_paddock_profile_and_restores_exactly(radio):  # noqa: F811
    configure(radio)
    user_macros(radio)
    before = radio.profile_path.read_bytes()
    assert radio.prepare_spotter_only()['spotter_only']
    prefs = json.loads(radio.profile_path.read_text())['userSettings']
    assert prefs['frequency_of_player_prac_and_qual_lap_time_reports'] == 0 and prefs['enable_tyre_temp_warnings'] is False
    assert 'enable_spotter' not in prefs or prefs['enable_spotter'] is not False      # the spotter stays
    radio.prepare_replies()   # other setups combine
    radio.restore_spotter_only()
    radio.restore_replies()
    assert radio.profile_path.read_bytes() == before and not radio.status()['spotter_only']
