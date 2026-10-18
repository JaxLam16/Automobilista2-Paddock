"""Private portable corner statistics. Bounded data-only files; no network or raw archive import."""
from __future__ import annotations

import base64
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import re
import uuid
import zlib

from .skills import LABELS
from .skill_references import corner_targets, match

FORMAT='paddock-corner-reference'
VERSION=1
MAX_COMPRESSED=512*1024
MAX_RAW=8*1024*1024
TOKEN=re.compile(r'pack:([a-f0-9]{64})\Z')
UNITS={'turn_in':'m to landmark','brake_point':'m to landmark','throttle_onset':'m to landmark',
       'trail_braking':'s release','peak_brake':'%','minimum_speed':'km/h','understeer':'s','oversteer':'s',
       'apex':'m wheel clearance','exits':'m wheel clearance','steering':'% input/s',
       'gearing':'s near max RPM','throttle_application':'withdrawals'}


def _text(v,limit=200,*,empty=False):
    if not isinstance(v,str) or len(v)>limit or (not v and not empty) or any(ord(c)<32 for c in v):
        raise ValueError('Invalid reference text.')
    return v


def _number(v,low=-1e6,high=1e6,*,optional=False):
    import math
    if optional and v is None:return None
    if type(v) not in (int,float) or not math.isfinite(v) or not low<=v<=high:
        raise ValueError('Invalid reference measurement.')
    return v


def _tree(v,depth=0):
    if depth>10:raise ValueError('Reference nesting exceeds the limit.')
    if isinstance(v,dict):
        if len(v)>100:raise ValueError('Too many reference fields.')
        for k,x in v.items():_text(k,100);_tree(x,depth+1)
    elif isinstance(v,list):
        if len(v)>8192:raise ValueError('Reference array exceeds the limit.')
        for x in v:_tree(x,depth+1)
    elif isinstance(v,str):_text(v,1200,empty=True)
    elif v is not None and type(v) is not bool:_number(v)


def _pairs(pairs):
    d={}
    for k,v in pairs:
        if k in d:raise ValueError('Duplicate reference field.')
        d[k]=v
    return d


def _constant(value):raise ValueError('Non-finite reference measurement.')


def canonical(data):
    return json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')


def validate(data):
    if not isinstance(data,dict):raise ValueError('Reference must contain an object.')
    _tree(data)
    if set(data)!={'format','version','analysis_version','meta','source','passes','traces'} or data['format']!=FORMAT or type(data['version']) is not int or data['version']!=VERSION:
        raise ValueError('Unsupported Paddock reference format/version.')
    _number(data['analysis_version'],1,100000)
    meta=data['meta']
    if not isinstance(meta,dict) or set(meta)!={'track_location','track_variation','track_length','local','started_at'}:raise ValueError('Invalid reference identity.')
    for k in ('track_location','track_variation'):_text(meta[k])
    _number(meta['track_length'],100,100000)
    _text(meta['started_at'],100,empty=True)
    local=meta['local']
    if not isinstance(local,dict) or set(local)!={'name','car','car_class'}:raise ValueError('Invalid reference driver.')
    for k in local:_text(local[k],200,empty=k=='car_class')
    source=data['source']
    if not isinstance(source,dict) or set(source)!={'recording','provenance','private','raw_recording_included'} or source['private'] is not True or source['raw_recording_included'] is not False:
        raise ValueError('Reference packs contain private statistics/snippets, not raw recordings.')
    _text(source['recording']);_text(source['provenance'],200)
    passes=data['passes']
    if not isinstance(passes,list) or not 1<=len(passes)<=8192:raise ValueError('Reference needs bounded corner passes.')
    lookup={}
    for p in passes:
        if not isinstance(p,dict) or set(p)!={'corner','apex','lap','provisional','elapsed_s','ranking_time_s','linked_corners','racing','metrics'}:
            raise ValueError('Invalid reference corner pass.')
        _text(p['corner'],60);_number(p['apex'],0,meta['track_length'])
        if type(p['lap']) is not int or not 1<=p['lap']<=10000 or p['provisional'] is not False:raise ValueError('Reference pass must be a completed clean lap.')
        for k in ('elapsed_s','ranking_time_s'):_number(p[k],.001,3600,optional=True)
        if p['racing'] is not None and type(p['racing']) is not bool:raise ValueError('Invalid reference traffic status.')
        linked=p['linked_corners']
        if not isinstance(linked,list) or not 1<=len(linked)<=100 or len(set(linked))!=len(linked) or p['corner'] not in linked:raise ValueError('Invalid linked reference corners.')
        for c in linked:_text(c,60)
        if not isinstance(p['metrics'],dict) or set(p['metrics'])!=set(LABELS):raise ValueError('Reference skill schema does not match this build.')
        for key,m in p['metrics'].items():
            if not isinstance(m,dict) or set(m)-{'label','value','unit','detail','status','channels','scale','release','observed_power_s'} or not {'label','value','unit','detail','status','channels'}<=set(m):raise ValueError('Invalid reference skill fields.')
            _text(m['label'],100);_text(m['unit'],60,empty=True);_text(m['detail'],1200,empty=True)
            _number(m['value'],optional=True)
            if m['label']!=LABELS[key]:raise ValueError('Reference skill label does not match its channel.')
            if m['value'] is not None:
                if m['unit']!=UNITS[key]:raise ValueError('Reference measurement unit does not match its skill.')
                if key in ('turn_in','brake_point','throttle_onset'):_number(m['value'],-meta['track_length']/2,meta['track_length']/2)
                else:_number(m['value'],0,{'peak_brake':100,'minimum_speed':600,'apex':50,'exits':50,'steering':2000}.get(key,3600))
            if m['status'] not in ('measured','caution','unavailable'):raise ValueError('Invalid reference skill status.')
            if (m['value'] is None)!=(m['status']=='unavailable'):raise ValueError('Unavailable reference skill cannot have a value.')
            if not isinstance(m['channels'],list) or len(m['channels'])>16:raise ValueError('Invalid reference channels.')
            for c in m['channels']:_text(c,60)
            if m.get('release') is not None:
                r=m['release']
                if key!='trail_braking' or not isinstance(r,dict) or set(r)!={'seconds','distance_m','reapplication_points','largest_drop_per_0_1s','overlap_s'}:raise ValueError('Invalid brake release reference.')
                for k,v in r.items():_number(v,-100000 if k=='distance_m' else 0,100000,optional=k=='overlap_s')
            if 'observed_power_s' in m:_number(m['observed_power_s'],0,3600)
            if m.get('scale') is not None:
                sc=m['scale']
                if not isinstance(sc,dict) or set(sc)!={'fraction','left','right','kind'}:raise ValueError('Invalid measurement scale.')
                _number(sc['fraction'],0,1);_text(sc['left'],100);_text(sc['right'],100)
                if sc['kind']!='measurement':raise ValueError('Imported quality grades are not accepted.')
        key=(p['lap'],p['corner'])
        if key in lookup:raise ValueError('Duplicate reference corner pass.')
        lookup[key]=p
    for p in passes:
        group=[lookup.get((p['lap'],name)) for name in p['linked_corners']]
        if any(q is None or set(q['linked_corners'])!=set(p['linked_corners']) for q in group):raise ValueError('Incomplete linked reference sequence.')
        total=sum(q['elapsed_s'] for q in group) if all(q['elapsed_s'] is not None for q in group) else None
        if (total is None)!=(p['ranking_time_s'] is None) or total is not None and abs(total-p['ranking_time_s'])>.001:
            raise ValueError('Linked reference timing does not match the observed corner times.')
        p['group_racing']=True if any(q['racing'] is True for q in group) else False if all(q['racing'] is False for q in group) else None
    targets=corner_targets(passes)
    if not targets:raise ValueError('Reference contains no eligible complete timed corner targets.')
    traces=data['traces']
    if not isinstance(traces,list) or len(traces)>200:raise ValueError('Too many reference trace snippets.')
    for trace in traces:
        if not isinstance(trace,dict) or set(trace)!={'corner','lap','x','brake','throttle','steering','speed'}:raise ValueError('Invalid reference trace snippet.')
        if (trace['lap'],trace['corner']) not in lookup:raise ValueError('Trace has no matching corner pass.')
        xs=trace['x']
        if not isinstance(xs,list) or not 2<=len(xs)<=129:raise ValueError('Reference trace length exceeds the limit.')
        for x in xs:_number(x,-1000,1000)
        if any(b<=a for a,b in zip(xs,xs[1:])):raise ValueError('Reference trace distance must increase.')
        for k in ('brake','throttle','steering','speed'):
            v=trace[k]
            if not isinstance(v,list) or len(v)!=len(xs):raise ValueError('Reference trace channels must align.')
            for x in v:_number(x,-100 if k=='steering' else 0,600 if k=='speed' else 100,optional=True)
    # Remove the derived field from serialized input. Targets are always rebuilt
    # from validated passes, never accepted as an imported instruction/grade.
    for p in passes:p.pop('group_racing')
    return data


def report(data):
    passes=deepcopy(data['passes'])
    lookup={(p['lap'],p['corner']):p for p in passes}
    for p in passes:
        group=[lookup[(p['lap'],c)] for c in p['linked_corners']]
        p['group_racing']=True if any(q['racing'] is True for q in group) else False if all(q['racing'] is False for q in group) else None
    return {'passes':passes,'targets':corner_targets(passes),'traces':deepcopy(data['traces']),
            'reference_verification':'imported_statistics_not_raw_reanalysis','optimality_scored':False}


def decode(encoded):
    if not isinstance(encoded,bytes) or not 0<len(encoded)<=MAX_COMPRESSED:raise ValueError('Reference file must be at most512 KB.')
    try:
        stream=zlib.decompressobj(31);raw=stream.decompress(encoded,MAX_RAW+1)
        if len(raw)>MAX_RAW or stream.unconsumed_tail or not stream.eof or stream.unused_data:raise ValueError('Reference decompression exceeds its limit or contains extra data.')
        data=json.loads(raw.decode('utf-8'),parse_constant=_constant,object_pairs_hook=_pairs)
        return validate(data)
    except (zlib.error,UnicodeError,RecursionError,TypeError,KeyError) as exc:raise ValueError('Malformed Paddock reference file.') from exc


def encode(data):
    data=validate(deepcopy(data));raw=canonical(data)
    if len(raw)>MAX_RAW:raise ValueError('Reference statistics exceed8 MB. Choose a shorter recording.')
    encoded=gzip.compress(raw,mtime=0)
    if len(encoded)>MAX_COMPRESSED:raise ValueError('Reference file exceeds512 KB. Choose a shorter recording.')
    return encoded


def from_report(meta,technique,recording,*,traces=()):
    local=meta.get('local') or {}
    if match(meta,meta) is None:raise ValueError('A local non-AI driver recording is required.')
    keys=('corner','apex','lap','provisional','elapsed_s','ranking_time_s','linked_corners','racing','metrics')
    passes=[{k:deepcopy(p[k]) for k in keys} for p in (technique.get('skills') or {}).get('passes',[])]
    data={'format':FORMAT,'version':VERSION,'analysis_version':technique.get('_v',11),
          'meta':{k:meta.get(k) for k in ('track_location','track_variation','track_length')},
          'source':{'recording':recording,'provenance':'recording_driver_local_telemetry','private':True,'raw_recording_included':False},
          'passes':passes,'traces':list(traces)}
    data['meta'].update(local={k:str(local.get(k) or '') for k in ('name','car','car_class')},started_at=str(meta.get('started_at') or ''))
    from .report import _clean
    return validate(_clean(data,digits=None))


def selected_traces(path,technique):
    """5 m input snippets from actual target laps; no averages or complete recording."""
    import numpy as np
    from .technique import recording_laps,_trace
    from .derive import load_session
    skills=technique.get('skills') or {};targets=skills.get('targets') or {}
    requested={(c,t['lap']) for c,metrics in targets.items() for t in metrics.values()}
    if not requested:return []
    _,laps,length=recording_laps(load_session(path));by_lap={lp['n']:lp for lp in laps if lp['valid']}
    corners=sorted({p['corner']:p['apex'] for p in skills['passes']}.items(),key=lambda c:c[1])
    out=[]
    for i,(name,apex) in enumerate(corners):
        before=min(300.,(apex-corners[i-1][1])%length/2) if len(corners)>1 else 300.
        after=min(180.,(corners[(i+1)%len(corners)][1]-apex)%length/2) if len(corners)>1 else 180.
        xs=np.arange(-before,after+1e-6,5.)
        for corner,n in sorted(requested):
            if corner!=name or n not in by_lap:continue
            lp=by_lap[n];trace={'corner':name,'lap':n,'x':[round(float(x),3) for x in xs]}
            for key,channel in (('brake','brake'),('throttle','throttle'),('steering','steer'),('speed','speed')):
                values=_trace(lp,channel,apex,length,xs) if lp.get(channel) is not None else np.full(len(xs),np.nan)
                trace[key]=[round(float(v),3) if np.isfinite(v) else None for v in values]
            out.append(trace)
            if len(out)==200:return out
    return out


class PackStore:
    def __init__(self,root):self.directory=Path(root)/'private_coach/reference-packs'

    @staticmethod
    def identifier(token):
        m=TOKEN.fullmatch(token) if isinstance(token,str) else None
        if m is None:raise ValueError('Invalid reference pack identifier.')
        return m.group(1)

    def get(self,token):
        identifier=self.identifier(token);path=self.directory/(identifier+'.paddockref')
        if not path.is_file():raise LookupError('Reference pack not found.')
        if path.stat().st_size>MAX_COMPRESSED:raise ValueError('Stored reference exceeds the size limit.')
        data=decode(path.read_bytes())
        if hashlib.sha256(canonical(data)).hexdigest()!=identifier:raise ValueError('Stored reference checksum does not match.')
        return data

    def add(self,encoded):
        data=decode(encoded);identifier=hashlib.sha256(canonical(data)).hexdigest();token='pack:'+identifier
        self.directory.mkdir(parents=True,exist_ok=True);path=self.directory/(identifier+'.paddockref')
        existed=path.exists()
        if existed:self.get(token)
        else:
            tmp=self.directory/(identifier+'.'+uuid.uuid4().hex+'.tmp')
            try:
                tmp.write_bytes(encode(data));tmp.replace(path)
            finally:tmp.unlink(missing_ok=True)
        return {'id':token,'driver':data['meta']['local']['name'],'car':data['meta']['local']['car'],
                'passes':len(data['passes']),'traces':len(data['traces']),'already_imported':existed,
                'verification':'Imported statistics; raw telemetry was not independently reanalysed.','uploaded':False}

    def matching(self,current):
        if not self.directory.is_dir():return []
        rows=[]
        for path in sorted(self.directory.glob('*.paddockref'))[:1000]:
            try:
                token='pack:'+path.stem;data=self.get(token);kind=match(current,data['meta'])
                if kind:
                    local=data['meta']['local'];rows.append({'id':token,'kind':kind,'source':'imported_pack',
                        'driver':local['name'],'car':local['car'],'started_at':data['meta']['started_at']})
            except (OSError,ValueError,LookupError):continue
        return rows


def decode_upload(body):
    value=body.get('data') if isinstance(body,dict) else None
    if not isinstance(value,str) or not 0<len(value)<=((MAX_COMPRESSED+2)//3)*4:raise ValueError('Choose a Paddock reference file at most512 KB.')
    try:return base64.b64decode(value,validate=True)
    except (ValueError,TypeError) as exc:raise ValueError('Invalid reference file encoding.') from exc
