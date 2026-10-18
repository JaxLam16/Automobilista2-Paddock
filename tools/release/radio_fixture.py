"""Check the packaged local host without editing Crew Chief or producing audio."""
import json
import os
from pathlib import Path
import queue
import secrets
import socket
import subprocess
import threading


def verify_radio_host(portable, env):
    library = next((Path(base) / 'Britton IT Ltd/CrewChiefV4/MQTTnet.dll'
                    for base in (os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'), os.environ.get('ProgramFiles', r'C:\Program Files'))
                    if (Path(base) / 'Britton IT Ltd/CrewChiefV4/MQTTnet.dll').is_file()), None)
    if library is None:
        return False
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    windows = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    script = portable / '_internal/ams2season/assets/crew_chief_host.ps1'
    assert script.is_file() and script.with_suffix('.cs').is_file()
    process = subprocess.Popen([str(windows / 'System32/WindowsPowerShell/v1.0/powershell.exe'),
                                '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                                '-File', str(script), '-Library', str(library)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding='utf-8', env=env, creationflags=subprocess.CREATE_NO_WINDOW)
    events = queue.Queue()
    def read():
        for line in process.stdout:
            try:
                events.put(json.loads(line.lstrip('\ufeff')))
            except ValueError:
                pass
    threading.Thread(target=read, daemon=True).start()
    try:
        process.stdin.write(json.dumps({'port':port,'token':secrets.token_urlsafe(32)}) + '\n')
        process.stdin.flush()
        event = events.get(timeout=25)
        assert event['type'] == 'ready', event
        with socket.create_connection(('127.0.0.1',port),timeout=5):
            pass
    finally:
        process.stdin.close()
        try:
            assert process.wait(timeout=8) == 0
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)
            raise
    return True
