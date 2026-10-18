"""Independent, passive skill display. No speech, game writes or coach lifecycle changes."""
from __future__ import annotations

from collections import deque
import json
from pathlib import Path
import threading
import time
import numpy as np

from . import shm as S
from .coach.model import finite
from .coach.apex import ApexMap, map_path
from .practice_overlay import NativeOverlay
from .skills import CATALOG, LABELS, CHANNELS, measure

DEFAULTS={'enabled':False,'selected':'trail_braking','skills':[k for k,_ in CATALOG],
          'corners':[],'timing':'exit','duration_s':6,'position':'center',
          'sessions':['practice'],'opacity':.95,'size':'compact','reference':''}


def sample(snap, now):
    """Recorder hook copies scalars only, never reads files or runs analysis."""
    i=int(snap.mViewedParticipantIndex)
    if not 0<=i<min(snap.mNumParticipants,S.STORED_PARTICIPANTS_MAX): return None
    p=snap.mParticipantInfo[i]
    if not p.mIsActive: return None
    text=lambda k:S.cstr(getattr(snap,k)).strip()
    return {'at':now,'t':now,'ld':finite(p.mCurrentLapDistance),'lap':int(p.mLapsCompleted),
        'driver':S.cstr(p.mName),'slot':i,'car':text('mCarName'),'car_class':S.cstr(snap.mCarClassNames[i]),'track':text('mTrackLocation'),
        'layout':text('mTrackVariation') or text('mTrackLocation'),'length':finite(snap.mTrackLength),
        'session':{S.SESSION_PRACTICE:'practice',S.SESSION_TEST:'practice',S.SESSION_QUALIFY:'qualify',S.SESSION_RACE:'race'}.get(snap.mSessionState),
        'active':snap.mGameState==S.GAME_INGAME_PLAYING and int(snap.mPitMode)==0,
        'valid':not bool(snap.mLapInvalidated) and not bool(snap.mLapsInvalidated[i]) and int(snap.mCrashState) in (0,1),
        'speed':finite(snap.mSpeed*3.6),'brake':finite(snap.mBrake*100),'throttle':finite(snap.mThrottle*100),
        'steer':finite(snap.mSteering*100),'gear':finite(snap.mGear),
        'yaw_rate':finite(snap.mAngularVelocity[1]),'acc_lat':finite(snap.mLocalAcceleration[0]),
        'acc_vert':finite(snap.mLocalAcceleration[1]),'acc_long':finite(snap.mLocalAcceleration[2]),
        'vel_lat':finite(snap.mLocalVelocity[0]),'vel_long':finite(snap.mLocalVelocity[2]),
        'rpm':finite(snap.mRpm),'max_rpm':finite(snap.mMaxRPM),
        'x':finite(p.mWorldPosition[0]),'z':finite(p.mWorldPosition[2]),'crash_state':int(snap.mCrashState)}


def as_lap(rows):
    return {'n':rows[-1]['lap']+1,'valid':all(s['valid'] for s in rows),
            **{k:np.asarray([s.get(k,np.nan) if s.get(k) is not None else np.nan for s in rows],float)
               for k in ('t','ld','speed','brake','throttle','steer','gear',*CHANNELS)}}


class SkillOverlay:
    def __init__(self,app,*,native_factory=None):
        self.app,self.root=app,app.lib.root
        self.lock=threading.RLock(); self.settings={**DEFAULTS,'skills':list(DEFAULTS['skills'])}
        self.samples=deque(maxlen=128); self.rows=[]; self.corners=[]; self.geometry=None
        self.identity=None;self.last=None;self.card=None;self.card_at=0;self.current=None
        self.reference_key=None;self.reference_info=None;self.reference_choices=[];self.reference_passes={};self.reference_targets={}
        self.visible=False;self.reason='disabled';self.error=None;self.dropped=0
        self.thread=None;self.halt=threading.Event();self.native=None
        self.native_factory=native_factory or (lambda root:NativeOverlay(root,kind='skills'))
        try:
            self.settings=self.validate(json.loads(self.path.read_text(encoding='utf-8')))
        except (OSError,ValueError,TypeError):pass

    @property
    def path(self):return self.root/'private_coach/skills/settings.json'

    def validate(self,body):
        if not isinstance(body,dict) or set(body)-set(DEFAULTS):raise ValueError('Unknown skill overlay setting.')
        data={**self.settings,**body}
        if not isinstance(data['enabled'],bool):raise ValueError('Choose skill overlay on/off.')
        for key,allowed in (('skills',LABELS),('sessions',('practice','qualify','race'))):
            v=data[key]
            if not isinstance(v,list) or not 1<=len(v)<=len(allowed) or any(s not in allowed for s in v) or len(set(v))!=len(v):raise ValueError('Choose at least one supported '+key+'.')
        if data['selected'] not in data['skills']:raise ValueError('Selected skill must be enabled for cycling.')
        if not isinstance(data['corners'],list) or len(data['corners'])>100 or any(not isinstance(c,str) or not 1<=len(c)<=60 or any(ord(v)<32 for v in c) for c in data['corners']):raise ValueError('Choose corner names or leave empty for all corners.')
        if data['timing'] not in ('live','exit','both') or data['position'] not in ('left','right','center') or data['size'] not in ('normal','compact'):raise ValueError('Invalid overlay display option.')
        if type(data['duration_s']) not in (int,float) or not 2<=data['duration_s']<=20:raise ValueError('Choose 2–20 seconds after each corner.')
        if type(data['opacity']) not in (int,float) or not .4<=data['opacity']<=1:raise ValueError('Choose opacity between 0.4 and 1.')
        ref=data['reference']
        if not isinstance(ref,str) or len(ref)>200:raise ValueError('Choose a saved recording reference.')
        if ref.startswith('pack:'):
            from .skill_packs import PackStore
            PackStore.identifier(ref)
        elif ref and (Path(ref).name!=ref or ref in ('.','..')):raise ValueError('Choose a saved recording reference.')
        return data

    def configure(self,body):
        with self.lock:
            data=self.validate(body);self.path.parent.mkdir(parents=True,exist_ok=True)
            if data['reference']!=self.settings['reference']:self.reference_key=None
            tmp=self.path.with_suffix('.tmp');tmp.write_text(json.dumps(data),encoding='utf-8');tmp.replace(self.path)
            self.settings=data;self.error=None
            if not data['enabled']:self.visible=False;self.reason='disabled'
            else:self.start()
            return self.status()

    def command(self,action):
        with self.lock:
            if action=='toggle':return self.configure({'enabled':not self.settings['enabled']})
            if action not in ('previous','next'):raise ValueError('Choose previous, next or toggle skill overlay.')
            skills=self.settings['skills'];i=skills.index(self.settings['selected'])
            return self.configure({'selected':skills[(i+(1 if action=='next' else -1))%len(skills)]})

    def feed(self,snap,now):
        if not self.settings['enabled']:return
        if len(self.samples)==self.samples.maxlen:self.dropped+=1
        self.samples.append(sample(snap,now))

    def _reset(self,identity=None):
        self.identity=identity;self.rows=[];self.corners=[];self.geometry=None
        self.card=None;self.current=None;self.visible=False
        self.reference_key=None;self.reference_info=None;self.reference_passes={};self.reference_targets={};self.reference_choices=[]

    def _reference(self,s):
        key=(self.identity,self.settings['reference'])
        if key==self.reference_key:return
        self.reference_key=key;self.reference_passes={};self.reference_targets={};self.reference_info=None;self.reference_choices=[]
        from .skill_references import match
        current={'track_location':s['track'],'track_variation':s['layout'],'track_length':s['length'],
                 'local':{'name':s['driver'],'car':s['car'],'car_class':s.get('car_class','')}}
        directory=getattr(self.app.lib,'recordings_dir',self.root/'recordings')
        matches={}
        for path in directory.iterdir() if directory.is_dir() else ():
            if not path.is_dir() or not (path/'session.json').is_file():continue
            try:meta=json.loads((path/'session.json').read_text(encoding='utf-8'))
            except (OSError,ValueError):continue
            kind=match(current,meta)
            if kind and meta.get('status')=='complete':
                matches[path.name]=(path,meta,kind)
                self.reference_choices.append({'id':path.name,'kind':kind,'driver':meta['local']['name'],'car':meta['local']['car']})
        from .skill_packs import PackStore,report as pack_report
        packs=PackStore(self.root)
        for row in packs.matching(current):
            pack=packs.get(row['id']);matches[row['id']]=(None,pack['meta'],row['kind'])
            self.reference_choices.append(row)
        self.reference_choices.sort(key=lambda r:(r['kind']!='exact_car',r['id']))
        selected=self.settings['reference']
        if not selected:return
        if selected not in matches:
            self.reference_info={'error':'Selected reference does not match this live layout, length and car/class.'};return
        path,meta,kind=matches[selected]
        try:
            report=pack_report(packs.get(selected)) if path is None else self.app.lib.technique_cached(path).get('skills') or {}
            self.reference_passes={p['corner']:p for p in report.get('passes',[]) if p['lap']==report.get('best_lap')}
            self.reference_targets=report.get('targets') or {}
            self.reference_info={'kind':kind,'recording':selected,'driver':meta['local']['name'],'car':meta['local']['car'],
                'source':'imported_pack' if path is None else 'local_recording',
                'verification':'Imported statistics; raw telemetry was not independently reanalysed.' if path is None else 'Calculated from this PC\'s recording.',
                'method':'corner_by_corner_per_skill','note':'Per-skill targets from fast clean corner passes, including linked sequences; setup, tyres and conditions are not normalized. Same-class comparisons use wider bands.'}
            if not self.reference_targets:self.reference_info={'error':'Reference has no complete clean timed corner passes.'}
        except (OSError,ValueError,LookupError) as exc:self.reference_info={'error':str(exc)[:160]}

    def _map(self,s):
        try:
            data=json.loads(map_path(self.root,s['track'],s['layout']).read_text(encoding='utf-8'))
            if data.get('track')!=s['track'] or data.get('layout')!=s['layout'] or abs(float(data['length'])-s['length'])>.5:return
            raw=data.get('corners',[])
            if not isinstance(raw,list) or len(raw)>100:return
            seen=set()
            for c in raw:
                name,d=c.get('name'),finite(c.get('apex'))
                if isinstance(name,str) and 1<=len(name)<=60 and name not in seen and d is not None and 0<=d<s['length']:
                    self.corners.append({'name':name,'apex':d});seen.add(name)
            self.corners.sort(key=lambda c:c['apex'])
            self.geometry=ApexMap(data,s['track'],s['layout'],s['length'],'live-measured-map')
        except (OSError,ValueError,TypeError,KeyError):pass

    def update(self,s,*,now=None,recorder_running=True):
        now=time.perf_counter() if now is None else now
        if not self.settings['enabled'] or not recorder_running or not s or not 0<=now-s['at']<=.75:
            self.visible=False;self.reason='disabled' if not self.settings['enabled'] else 'waiting_for_fresh_telemetry'
            self.rows=[];self.current=None;self.card=None;return self.status()
        self.last=s
        if not s['length'] or s['length']<100 or s['ld'] is None or not 0<=s['ld']<=s['length']:
            self.visible=False;self.reason='invalid_distance';self.rows=[];self.card=None;return self.status()
        identity=tuple(s[k] for k in ('track','layout','length','car','driver','slot','session'))
        if identity!=self.identity:self._reset(identity);self._map(s)
        self._reference(s)
        if s['session'] not in self.settings['sessions'] or not s['active'] or not s['valid']:
            self.visible=False;self.reason='pit_pause_invalid_or_session_excluded';self.rows=[];self.current=None;self.card=None;return self.status()
        if self.rows and s['t']!=self.rows[-1]['t']:
            prev=self.rows[-1];dt=s['t']-prev['t'];travel=(s['ld']-prev['ld'])%s['length']
            wrap=prev['ld']>s['length']*.85 and s['ld']<s['length']*.15 and 0<dt<=.35 and travel<max(20,dt*180)
            if wrap:
                if not self.corners and self.rows[0]['ld']<s['length']*.03 and prev['ld']>s['length']*.97:
                    from .technique import corners_from_laps
                    lp=as_lap(self.rows);lp['time']=prev['t']-self.rows[0]['t']
                    self.corners=corners_from_laps([lp],s['length'])
                self.rows=[];self.current=None;self.card=None
            elif not 0<dt<=.35 or travel>max(20,dt*180):
                self.rows=[];self.current=None;self.card=None
        if not self.rows or s['t']!=self.rows[-1]['t']:self.rows.append(s)
        if len(self.rows)>20000:self.rows=self.rows[-20000:]
        selected_corners=self.settings['corners']
        active=None
        for i,c in enumerate(self.corners):
            before=min(300.,((c['apex']-self.corners[i-1]['apex'])%s['length'])/2) if len(self.corners)>1 else 300.
            after=min(180.,((self.corners[(i+1)%len(self.corners)]['apex']-c['apex'])%s['length'])/2) if len(self.corners)>1 else 180.
            r=(s['ld']-c['apex']+s['length']/2)%s['length']-s['length']/2
            if -before<=r<=after and (not selected_corners or c['name'] in selected_corners):active=(c,before,after)
        if self.current and (not active or active[0]['name']!=self.current[0]['name']):
            c,b,a=self.current
            self.card=measure(as_lap(self.rows),c,s['length'],before=b,after=a,geometry=self.geometry);self.card_at=s['t'];self.current=None
        if active:
            self.current=active
            if self.settings['timing'] in ('live','both'):
                self.card=measure(as_lap(self.rows),active[0],s['length'],before=active[1],after=active[2],geometry=self.geometry,complete=False);self.card_at=s['t']
        self.visible=bool(self.card and (active and self.settings['timing'] in ('live','both') or
                         not self.card['provisional'] and self.settings['timing'] in ('exit','both') and s['t']-self.card_at<=self.settings['duration_s']))
        self.reason='ready' if self.visible else 'learning_corners_complete_one_clean_lap' if not self.corners else 'waiting_for_selected_corner'
        return self.status()

    def status(self):
        with self.lock:
            card=self.card
            metric=card['metrics'].get(self.settings['selected']) if card else None
            from .skill_feedback import assessment
            target=(self.reference_targets.get(card['corner']) or {}).get(self.settings['selected']) if card else None
            if target and abs(target['apex']-card['apex'])>10:target=None
            metric=assessment(self.settings['selected'],metric,reference=target['metric'] if target else None,
                reference_kind=(self.reference_info or {}).get('kind'),provisional=card['provisional']) if card else None
            return {'enabled':self.settings['enabled'],'visible':self.visible,'settings':dict(self.settings),
                'catalog':[{'id':k,'label':v} for k,v in CATALOG],'corners':[c['name'] for c in self.corners],
                'selected':self.settings['selected'],'corner':card['corner'] if card else None,
                'lap':card['lap'] if card else None,'provisional':card['provisional'] if card else False,
                'metric':metric,'reason':self.reason,'error':self.error,'dropped_samples':self.dropped,
                'position':self.settings['position'],'opacity':self.settings['opacity'],'size':self.settings['size'],
                'reference_info':self.reference_info,'reference_choices':list(self.reference_choices),
                'reference_corner_lap':target['lap'] if target else None,
                'reference':('Chosen reference • '+self.reference_info['driver'] if self.reference_info and self.reference_info.get('driver') else 'Telemetry • measured, no optimal-lap target')}

    def start(self):
        if self.thread is None or not self.thread.is_alive():
            self.halt.clear();self.thread=threading.Thread(target=self._run,name='skill-overlay',daemon=True);self.thread.start()

    def _run(self):
        try:
            while not self.halt.wait(.1):
                coach=getattr(self.app,'_coach',None)
                if coach is not None:
                    with coach.lock:
                        if not coach.running:
                            if coach.button_bindings:coach._ensure_buttons()
                            coach._service_buttons()
                with self.lock:
                    batch=[]
                    while self.samples:batch.append(self.samples.popleft())
                    if not batch:batch=[self.last]
                    for s in batch:self.update(s,recorder_running=self.app.recorder.running)
                    state=self.status()
                    if self.settings['enabled'] and self.native is None and not self.error:self.native=self.native_factory(self.root)
                    if self.native:
                        self.native.publish(state)
                        if not self.settings['enabled']:self.native.close();self.native=None
        except Exception as exc:
            self.error='Skill overlay stopped: '+str(exc)[:200];self.visible=False
        finally:
            if self.native:self.native.close();self.native=None

    def close(self):
        self.halt.set()
        if self.thread and self.thread is not threading.current_thread():self.thread.join(timeout=3)
