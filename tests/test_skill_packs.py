import base64
from copy import deepcopy
import gzip
import http.client
import json
from pathlib import Path
import threading
import zlib

import pytest

from ams2season.skill_packs import (PackStore,MAX_COMPRESSED,MAX_RAW,canonical,
                                  decode,encode,from_report,report as pack_report)
from ams2season.skills import report
from ams2season.skill_references import compare
from ams2season.app import App,make_handler,_make_server
from test_skills import lap
from test_skill_overlay import model,samples


def example():
    skills=report([lap()],[{'name':'T1','apex':300}],1000,racing={(1,'T1'):False})
    meta={'track_location':'Track','track_variation':'GP','track_length':1000,
          'local':{'name':'Reference driver','car':'Mustang','car_class':'GT3'},'started_at':'2026-10-17T12:00:00'}
    trace={'corner':'T1','lap':1,'x':[-10.,0.,10.],'brake':[20.,10.,0.],
           'throttle':[0.,20.,50.],'steering':[-5.,0.,5.],'speed':[90.,91.,92.]}
    return from_report(meta,{'skills':skills},'reference-session',traces=[trace])


def test_private_pack_round_trip_rebuilds_targets_and_preserves_trace_data(tmp_path):
    data=example();encoded=encode(data);read=decode(encoded)
    assert read==data and encode(data)==encoded
    result=pack_report(read)
    assert result['targets']['T1']['brake_point']['lap']==1 and result['traces']==data['traces']
    assert not result['optimality_scored'] and 'not_raw_reanalysis' in result['reference_verification']
    store=PackStore(tmp_path);first=store.add(encoded);path=store.directory/(first['id'][5:]+'.paddockref')
    original=path.read_bytes();second=store.add(encoded)
    assert not first['already_imported'] and second['already_imported'] and path.read_bytes()==original
    assert store.get(first['id'])==data
    assert not (tmp_path/'recordings').exists() and not (tmp_path/'championships').exists()
    assert len(store.matching(data['meta']))==1
    other=deepcopy(data['meta']);other['track_variation']='Other';assert store.matching(other)==[]


@pytest.mark.parametrize('mutation',[
    lambda d:d.update(version=999),lambda d:d.update(targets={}),
    lambda d:d['source'].update(raw_recording_included=True),
    lambda d:d['meta'].update(track_length=0),
    lambda d:d['passes'][0].update(lap=True),lambda d:d['passes'][0].update(provisional=True),
    lambda d:d['passes'][0].update(ranking_time_s=1),
    lambda d:d['passes'][0].update(linked_corners=['T1','missing']),
    lambda d:d['passes'][0]['metrics']['brake_point'].update(value=float('nan')),
    lambda d:d['passes'][0]['metrics']['steering'].update(value=50,status='unavailable'),
    lambda d:d['passes'][0]['metrics']['steering'].update(feedback='Fake instruction'),
    lambda d:d['passes'][0]['metrics']['minimum_speed'].update(unit='mph'),
    lambda d:d['passes'][0]['metrics']['minimum_speed'].update(value=1000),
    lambda d:d['passes'][0]['metrics']['minimum_speed'].update(label='Different skill'),
    lambda d:d['traces'][0].update(x=[0,0,10]),
    lambda d:d['traces'][0].update(brake=[0,200,50]),
    lambda d:d['traces'][0].update(lap=2),
])
def test_bad_schema_or_fabricated_derived_fields_do_not_enter_store(tmp_path,mutation):
    data=example();mutation(data)
    encoded=gzip.compress(json.dumps(data,allow_nan=True).encode())
    with pytest.raises(ValueError):PackStore(tmp_path).add(encoded)
    assert not PackStore(tmp_path).directory.exists()


@pytest.mark.parametrize('data',[
    b'not gzip',gzip.compress(b'{}')+gzip.compress(b'{}'),
    gzip.compress(b'{"format":"a","format":"b"}'),
    gzip.compress(b'x'*(MAX_RAW+1)),b'x'*(MAX_COMPRESSED+1),
    gzip.compress(b'[]'),gzip.compress(b'['*40+b'0'+b']'*40),
],ids=['plain','concatenated','duplicate_keys','decompression_limit','compressed_limit','array_root','nesting_limit'])
def test_malformed_compressed_bomb_duplicate_or_concatenated_data_is_rejected(data):
    with pytest.raises(ValueError):decode(data)


@pytest.mark.parametrize('token',['../file','pack:../file','pack:'+('a'*63),'pack:'+('A'*64),'pack:a/b'])
def test_pack_identifier_cannot_address_other_files(tmp_path,token):
    with pytest.raises(ValueError):PackStore(tmp_path).get(token)


def test_tampered_stored_pack_cannot_silently_replace_original(tmp_path):
    store=PackStore(tmp_path);r=store.add(encode(example()));path=store.directory/(r['id'][5:]+'.paddockref')
    altered=example();altered['meta']['local']['name']='Changed';path.write_bytes(encode(altered))
    with pytest.raises(ValueError,match='checksum'):store.get(r['id'])
    assert store.matching(example()['meta'])==[]


def test_imported_pack_can_be_live_reference_without_copying_recording(tmp_path):
    o=model(tmp_path);pack=PackStore(tmp_path).add(encode(example()))
    o.configure({'reference':pack['id'],'selected':'brake_point'})
    s=samples()[0];o.update(s,now=0)
    assert o.reference_targets and o.reference_info['source']=='imported_pack'
    assert 'not independently reanalysed' in o.reference_info['verification']
    assert not (tmp_path/'recordings').exists()


def test_library_comparison_includes_imported_source_and_selected_raw_trace(tmp_path):
    app=App(tmp_path);directory=app.lib.recordings_dir/'current';directory.mkdir()
    meta=deepcopy(example()['meta']);meta['status']='complete';(directory/'session.json').write_text(json.dumps(meta))
    own=report([lap()],[{'name':'T1','apex':300}],1000)
    app.lib.technique_cached=lambda path:{'skills':own,'driver':'Player'}
    result=PackStore(tmp_path).add(encode(example()))
    choices=app.lib.skill_references('current')['references'];assert result['id'] in {r['id'] for r in choices}
    comparison=app.lib.skill_references('current',result['id'])
    assert comparison['differences'] and comparison['reference_source']=='imported_pack'
    assert comparison['reference_traces'][0]['brake']==[20.,10.,0.]
    assert not comparison['quality_scores']


def test_http_pack_round_trip_origin_and_bounds_without_user_data(tmp_path):
    app=App(tmp_path);encoded=encode(example());app.lib.export_skill_pack=lambda _:encoded
    server=_make_server(0,make_handler(app));threading.Thread(target=server.serve_forever,daemon=True).start();port=server.server_address[1]
    def req(method,path,body=None,origin=None):
        c=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
        headers={'Content-Type':'application/json'}
        if origin:headers['Origin']=origin
        c.request(method,path,body=json.dumps(body) if body is not None else None,headers=headers)
        r=c.getresponse();result=(r.status,r.getheader('Content-Type'),r.read());c.close();return result
    try:
        payload={'data':base64.b64encode(encoded).decode()}
        assert req('POST','/api/skills/packs/import',payload,'http://untrusted.test')[0]==403
        code,ctype,data=req('GET','/api/skills/packs/export?recording=current')
        assert code==200 and ctype=='application/gzip' and decode(data)==example()
        code,_,data=req('POST','/api/skills/packs/import',payload)
        assert code==200 and json.loads(data)['uploaded'] is False
        assert req('POST','/api/skills/packs/import',{'data':'x'*(769<<10)})[0]==413
        assert req('POST','/api/skills/overlay',{'corners':['x'*17000]})[0]==413
    finally:server.shutdown();server.server_close()
