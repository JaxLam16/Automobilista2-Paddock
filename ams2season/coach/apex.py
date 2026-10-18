"""Mapped apex coaching against earlier clean local full-lap intervals only.

No inferred/modelled road edges, other-layout map, rival controls or future laps.
"""
from collections import Counter, deque
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import re
from statistics import median

from .gaps import CrossingClock
from .model import finite, incident, PRACTICE_SUMMARY_S


def map_path(root, track, layout):
    slug=lambda s:re.sub(r'[^a-z0-9]+','-',str(s).lower()).strip('-') or 'track'
    return Path(root)/'tracks'/(slug(track)+'__'+slug(layout)+'.json')


def _point(samples, d):
    raw=[(p[0]-d,p[1],p[2]) for p in samples if abs(p[0]-d)<=15]
    groups={}
    for p in raw:groups.setdefault(math.floor((p[0]+d)/5),[]).append(p)
    # Mapping files contain repeated wheel crossings, not an ordered edge curve.
    # Equal-weight spatial medians stop a densely revisited patch dominating it.
    local=[tuple(median(p[i] for p in group) for i in range(3)) for group in groups.values()]
    if (len(raw)<4 or len(local)<3
            or min(p[0] for p in local)>-2 or max(p[0] for p in local)<2):
        raise ValueError('mapped_edge_coverage_insufficient')
    # Local least-squares curve tangent. Reject scattered or unrelated edge points.
    ds=[p[0] for p in local];mean=sum(ds)/len(ds)
    den=sum((v-mean)**2 for v in ds)
    coords=[]
    for axis in (1,2):
        values=[p[axis] for p in local];avg=sum(values)/len(values)
        slope=sum((v-mean)*(y-avg) for v,y in zip(ds,values))/den
        intercept=avg-slope*mean
        if sum((y-intercept-slope*v)**2 for v,y in zip(ds,values))/len(ds)>4:
            raise ValueError('mapped_edge_scatter')
        coords.append(intercept)
    return tuple(coords)


def _unit(x,z):
    norm=math.hypot(x,z)
    if norm<1e-6:raise ValueError('map_direction_unknown')
    return x/norm,z/norm


class ApexMap:
    def __init__(self,data,track,layout,length,digest):
        if (not isinstance(data,dict) or data.get('track')!=track or data.get('layout')!=layout
                or finite(data.get('length')) is None or abs(data['length']-length)>.5):
            raise ValueError('map_layout_or_length_mismatch')
        self.digest=digest;self.length=length;self.corners=[];self.rejected=Counter()
        samples={}
        for side in ('left','right'):
            rows=(data.get('samples') or {}).get(side,[])
            if not isinstance(rows,list) or len(rows)>100000:raise ValueError('map_samples_invalid')
            samples[side]=[tuple(finite(v) for v in row) for row in rows
                           if isinstance(row,list) and len(row)==3]
            if any(any(v is None for v in row) for row in samples[side]):raise ValueError('map_samples_invalid')
        names=set()
        corners=data.get('corners') or []
        if not isinstance(corners,list) or len(corners)>100:raise ValueError('map_corners_invalid')
        for corner in corners:
            try:
                name=corner.get('name');d=finite(corner.get('apex'))
                if not isinstance(name,str) or not 1<=len(name)<=60 or any(ord(c)<32 for c in name) or name in names:
                    raise ValueError('map_corner_name_invalid')
                names.add(name)
                # Keep the entire measured section on one side of the timing boundary.
                if d is None or not 60<d<length-60 or abs(d-length/2)<60:
                    raise ValueError('corner_crosses_timing_boundary')
                sections=[]
                for offset in (-40,-20,-10,0,10,20,40):
                    left,right=(_point(samples[s],d+offset) for s in ('left','right'))
                    width=math.dist(left,right)
                    if not 5<=width<=25:raise ValueError('mapped_width_invalid')
                    sections.append({'d':d+offset,'left':left,'right':right,
                                     'centre':tuple((a+b)/2 for a,b in zip(left,right)),'width':width})
                a,b,c=(sections[i]['centre'] for i in (0,3,6))
                u=_unit(b[0]-a[0],b[1]-a[1]);v=_unit(c[0]-b[0],c[1]-b[1])
                cross=u[0]*v[1]-u[1]*v[0]
                if abs(cross)<.04:raise ValueError('mapped_corner_direction_unknown')
                tangent=_unit(c[0]-a[0],c[1]-a[1]);sign=1 if cross>0 else -1
                normal=(-tangent[1]*sign,tangent[0]*sign)
                middle=sections[3]
                inside=max(('left','right'),key=lambda s:sum((p-q)*n for p,q,n in zip(middle[s],middle['centre'],normal)))
                self.corners.append({'name':name,'apex':d,'sections':sections,'inside':inside,
                                     'normal':normal,'tangent':tangent})
            except (ValueError,TypeError,KeyError,AttributeError) as exc:
                self.rejected[str(exc)]+=1

    @staticmethod
    def gap(corner,d,x,z):
        sections=corner['sections']
        a,b=next((a,b) for a,b in zip(sections,sections[1:]) if a['d']<=d<=b['d'])
        share=(d-a['d'])/(b['d']-a['d'])
        interp=lambda key:tuple(p+(q-p)*share for p,q in zip(a[key],b[key]))
        centre=interp('centre');edge=interp(corner['inside'])
        along=sum((p-q)*n for p,q,n in zip((x,z),centre,corner['tangent']))
        gap=sum((p-q)*n for p,q,n in zip(edge,(x,z),corner['normal']))
        if abs(along)>6 or not -.25<=gap<=max(a['width'],b['width'])+1:
            return None
        return max(0,gap)


class ApexMapStore:
    def __init__(self,root,*,frozen=False):
        self.root=Path(root).resolve();self.frozen=frozen;self.key=None;self.signature=None
        self.value=None;self.reason='map_not_loaded';self.source=None
        self.rejected={}

    def load(self,track,layout,length):
        key=(track,layout,length);path=map_path(self.root,track,layout)
        if self.frozen and self.key==key:return self.value
        try:
            stat=path.stat();signature=(stat.st_size,stat.st_mtime_ns)
            if self.key==key and self.signature==signature:return self.value
            self.key=key;self.signature=signature;self.value=None;self.source=None;self.rejected={}
            if path.is_symlink() or path.resolve().parent!=(self.root/'tracks').resolve() or stat.st_size>8<<20:
                raise ValueError('map_path_or_size_invalid')
            raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest()
            self.source={'file':str(path),'sha256':digest}
            self.value=ApexMap(json.loads(raw),track,layout,length,digest)
            self.rejected=dict(self.value.rejected)
            self.reason='mapped' if self.value.corners else 'no_supported_mapped_corners'
            if not self.value.corners:self.value=None
        except FileNotFoundError:
            self.key=key;self.signature=None;self.value=None;self.source=None;self.rejected={};self.reason='matching_edge_map_missing'
        except (OSError,ValueError,TypeError,KeyError) as exc:
            self.value=None;self.reason=str(exc)
        return self.value


class ApexWatch:
    def __init__(self):
        self.diagnostics=Counter();self.clear()

    def clear(self,reason='learning'):
        self.clock=CrossingClock();self.anchor=None;self.previous=None;self.cells={};self.clean=True
        self.history=deque(maxlen=8);self.patterns={};self.geometry=None;self.reason=reason
        self.completed=0;self.last_interval=None

    def suspend(self,reason):
        # Retain references as history, but break the recent repeated-lap pattern.
        self.clock=CrossingClock();self.anchor=None;self.previous=None;self.cells={};self.clean=True
        if not self.history or self.history[-1]['clean']:self.history.append({'clean':False})
        self.patterns={};self.reason=reason

    @staticmethod
    def safe(tick,player,*,positions=True):
        if (player is None or player.pit!=0 or player.race_state!=2 or player.invalid
                or player.flag_colour not in (0,1) or tick.local.get('local_lap_invalid') is not False
                or incident(tick.local.get('crash_state')) or tick.local.get('yellow_flag_state')!=0
                or finite(tick.local.get('rain_density')) is None or not 0<=tick.local['rain_density']<=1
                or (positions and (player.x is None or player.z is None)) or player.distance is None
                or not 0<=player.distance<=tick.length+1):return False
        for car in tick.cars:
            if car.identity==player.identity or car.pit in (1,2,3,4,5) or car.race_state!=2:continue
            if car.distance is None or not 0<=car.distance<=tick.length+1:return False
            gap=abs(min(car.distance,tick.length)-min(player.distance,tick.length))
            if min(gap,tick.length-gap)<=max(100,(player.speed or 0)*3):return False
        return True

    def feed(self,tick,player,geometry,*,active=True,reason='inactive'):
        if geometry is not self.geometry:
            self.clear('map_changed');self.geometry=geometry
        if not active or tick.session!='practice' or geometry is None:
            self.suspend(reason if not active else 'practice_only' if tick.session!='practice' else 'matching_edge_map_missing')
            return []
        safe=self.safe(tick,player)
        if not safe:
            self.clean=False;self.patterns={};self.diagnostics['unsafe_or_traffic_samples']+=1
        if player is None or player.distance is None or not 0<=player.distance<=tick.length+1:
            self.suspend('position_unknown');return []
        car=replace(player,distance=min(player.distance,tick.length))
        if not self.clock.feed(tick.t,car,tick.length):
            self.suspend('geometry_or_capture_discontinuity');return []
        previous=self.previous;self.previous=(tick.t,car.distance)
        events=[]
        if self.clock.crossings:
            crossing=self.clock.crossings[-1]
            if self.anchor is None or crossing.t>self.anchor.t:
                if self.anchor:
                    record={'lap':crossing.lap,'start_t':self.anchor.t,'end_t':crossing.t,
                            'seconds':crossing.t-self.anchor.t,'clean':self.clean,
                            'corners':{}}
                    for name,cell in self.cells.items():
                        if (not cell.get('bad') and cell.get('entry') is not None and cell.get('exit') is not None
                                and cell.get('count',0)>=5 and cell.get('lo',100)<=-8 and cell.get('hi',-100)>=8):
                            record['corners'][name]={'gap_m':cell['gap'],'seconds':cell['exit']-cell['entry']}
                    if not 10<=record['seconds']<=1800:record['clean']=False
                    self.history.append(record);self.completed+=int(record['clean'])
                    self.last_interval=record
                    events=self._patterns(tick,geometry)
                self.anchor=crossing;self.cells={};self.clean=safe
        if safe and previous:
            stamp,old=previous
            if 0<tick.t-stamp<=.5 and 0<=car.distance-old<=max(20,(tick.t-stamp)*180):
                for corner in geometry.corners:
                    d=car.distance;apex=corner['apex'];name=corner['name']
                    cell=self.cells.setdefault(name,{})
                    for key,line in (('entry',apex-40),('exit',apex+40)):
                        if old<line<=d and d>old:cell[key]=stamp+(tick.t-stamp)*(line-old)/(d-old)
                    if abs(d-apex)<=15:
                        gap=geometry.gap(corner,d,player.x,player.z)
                        if gap is None:cell['bad']=True
                        else:
                            cell['gap']=min(cell.get('gap',gap),gap);cell['count']=cell.get('count',0)+1
                            cell['lo']=min(cell.get('lo',100),d-apex);cell['hi']=max(cell.get('hi',-100),d-apex)
        self.reason='measuring' if safe else 'unsafe_or_traffic'
        return events

    def _patterns(self,tick,geometry):
        self.patterns={}
        history=list(self.history)
        if len(history)<5 or not all(r['clean'] for r in history[-3:]):return []
        events=[]
        for corner in geometry.corners:
            name=corner['name']
            references=sorted((r for r in history[:-3] if r['clean'] and name in r.get('corners',{})
                               and tick.t-r['end_t']<=900),key=lambda r:r['seconds'])[:2]
            if len(references)<2 or not all(name in r.get('corners',{}) for r in history[-3:]):continue
            ref=[r['corners'][name] for r in references]
            if max(r['gap_m'] for r in ref)>3 or abs(ref[0]['gap_m']-ref[1]['gap_m'])>1:continue
            baseline=max(r['gap_m'] for r in ref);typical=median(r['seconds'] for r in ref)
            recent=[{'lap':r['lap'],'start_t':r['start_t'],'end_t':r['end_t'],**r['corners'][name],
                     'wider_by_m':r['corners'][name]['gap_m']-baseline,
                     'slower_by_s':r['corners'][name]['seconds']-typical} for r in history[-3:]]
            misses=[r for r in recent if r['wider_by_m']>=1.5 and r['slower_by_s']>=.15]
            if len(misses)<2 or recent[-1] not in misses:continue
            value={'corner':name,'apex_m':corner['apex'],'map_sha256':geometry.digest,
                   'token':f"{geometry.digest}:{name}:{history[-1]['lap']}:{tick.t}",
                   'measured_t':tick.t,'reference_intervals':references,'recent':recent,
                   'wider_by_m':min(r['wider_by_m'] for r in misses),'source':'mapped_edge_and_earlier_clean_local_intervals',
                   'scope':'practice_local_self_comparison','timing_point_m':tick.length/2}
            self.patterns[name]=value;events.append(value)
        self.diagnostics['confirmed_patterns']+=len(events)
        return sorted(events,key=lambda v:v['wider_by_m'],reverse=True)[:1]

    def token(self,name,tick,player):
        value=self.patterns.get(name)
        return value['token'] if value and self.safe(tick,player) and 0<=tick.t-value['measured_t']<PRACTICE_SUMMARY_S else None

    def status(self):
        return {'reason':self.reason,'clean_intervals_completed':self.completed,'history_intervals':len(self.history),
                'supported_corners':[c['name'] for c in self.geometry.corners] if self.geometry else [],
                'diagnostics':dict(self.diagnostics)}
