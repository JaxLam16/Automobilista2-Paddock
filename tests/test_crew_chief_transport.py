"""Real child pipe saturation and failure cleanup, with no game or audio."""
import json,subprocess,sys,time
from pathlib import Path
import pytest
from ams2season.coach.crew_mapper import Mapper
from ams2season.coach.crew_spotter import Spotter

NATIVE=pytest.mark.skipif(sys.platform!='win32',reason='Windows helper process transport')


def helper(monkeypatch,tmp_path,code):
    original=subprocess.Popen
    def launch(*args,**kwargs):
        return original([sys.executable,'-u','-c',code],**kwargs)
    monkeypatch.setattr(subprocess,'Popen',launch)
    host=Mapper(root=tmp_path,sounds=tmp_path/'sounds');host.start()
    assert host.ready.wait(5),host.error
    return host


@NATIVE
def test_original_diagnostics_cannot_fill_pipe_and_block_live_reply(monkeypatch,tmp_path):
    host=helper(monkeypatch,tmp_path,"""
import sys,json
print('{"ready":true}',flush=True)
for line in sys.stdin:
    sys.stderr.write('diagnostic '*20000);sys.stderr.flush()
    print('{"ok":true}',flush=True)
""")
    process=host.process;readers=host._readers
    try:
        assert host._request({'op':'test'})=={'ok':True}
        assert 0<len(host.stderr_tail)<=4096
        assert host.request_timeout==.5
    finally:host.close()
    assert process.poll() is not None and all(not t.is_alive() for t in readers)


@NATIVE
def test_helper_failure_keeps_only_bounded_diagnostic_tail(monkeypatch,tmp_path):
    host=helper(monkeypatch,tmp_path,"""
import sys
print('{"ready":true}',flush=True)
sys.stdin.readline()
sys.stderr.write('diagnostic '*20000+' FINAL_FAILURE');sys.stderr.flush()
""")
    try:
        host.process.stdin.write('{}\n');host.process.stdin.flush()
        end=time.monotonic()+3
        while not host.error and time.monotonic()<end:time.sleep(.01)
        assert 'FINAL_FAILURE' in host.error
        assert len(host.error)<1100 and len(host.stderr_tail)<=4096
    finally:host.close()


@NATIVE
def test_timed_out_response_is_not_reused_after_explicit_restart(monkeypatch,tmp_path):
    host=helper(monkeypatch,tmp_path,"""
import sys,json,time
print('{"ready":true}',flush=True)
for line in sys.stdin:
    if json.loads(line).get('slow'):time.sleep(1)
    print('{"fresh":true}',flush=True)
""")
    process=host.process;readers=host._readers
    try:
        host.request_timeout=.03
        assert host._request({'slow':True}) is None
        assert 'stopped responding' in host.error
        assert host.process is None and process.poll() is not None
        assert all(not t.is_alive() for t in readers)
        host.error=None;host._starting=False;host._closing=False;host.request_timeout=.5
        host.start();assert host.ready.wait(5)
        assert host._request({})=={'fresh':True}
    finally:host.close()
