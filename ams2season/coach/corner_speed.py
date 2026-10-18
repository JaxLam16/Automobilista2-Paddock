"""Past-only local corner-speed comparisons; no road-edge map or cause inferred."""
from collections import Counter,deque
from dataclasses import replace
from statistics import median

from .apex import ApexWatch
from .gaps import CrossingClock
from .model import finite, PRACTICE_SUMMARY_S


class CornerSpeedWatch:
    def __init__(self):
        self.diagnostics=Counter();self.clear()

    def clear(self,reason='learning'):
        self.history=deque(maxlen=8);self.completed=0;self.bends=[];self.last_interval=None
        self._reset_current(reason)

    def _reset_current(self,reason):
        self.clock=CrossingClock();self.anchor=None;self.previous=None;self.cells={}
        self.clean=True;self.patterns={};self.reason=reason

    def suspend(self,reason):
        self._reset_current(reason)
        if not self.history or self.history[-1]['clean']:self.history.append({'clean':False})

    @staticmethod
    def safe(tick,player):
        speed=finite(tick.local.get('speed'));steering=finite(tick.local.get('steering'))
        return (ApexWatch.safe(tick,player,positions=False) and speed is not None and 5<=speed<=160
                and steering is not None and -1<=steering<=1)

    def feed(self,tick,player,*,active=True,reason='inactive'):
        if not active or tick.session!='practice':
            self.suspend(reason if not active else 'practice_only');return []
        if player is None or player.distance is None or not 0<=player.distance<=tick.length+1:
            self.suspend('position_unknown');return []
        safe=self.safe(tick,player)
        if not safe:
            self.clean=False;self.patterns={};self.diagnostics['unsafe_or_traffic_samples']+=1
        car=replace(player,distance=min(player.distance,tick.length))
        if not self.clock.feed(tick.t,car,tick.length):
            self.suspend('geometry_or_capture_discontinuity');return []
        previous=self.previous
        if previous and tick.t-previous[0]>.25:
            self.clean=False;self.patterns={}
        speed=finite(tick.local.get('speed'));steer=finite(tick.local.get('steering'))
        brake=finite(tick.local.get('brake'))
        self.previous=(tick.t,car.distance,speed,steer,brake)
        events=[]
        if self.clock.crossings:
            crossing=self.clock.crossings[-1]
            if self.anchor is None or crossing.t>self.anchor.t:
                if self.anchor:
                    record={'lap':crossing.lap,'start_t':self.anchor.t,'end_t':crossing.t,
                            'seconds':crossing.t-self.anchor.t,'clean':self.clean,'cells':self.cells}
                    record['clean'] &= (10<=record['seconds']<=1800 and len(self.cells)>=tick.length/5*.85)
                    self.history.append(record);self.completed+=int(record['clean'])
                    self.last_interval={k:v for k,v in record.items() if k!='cells'}
                    self.last_interval['measured_bins']=len(self.cells)
                    events=self._patterns(tick)
                self.anchor=crossing;self.cells={};self.clean=safe
        if previous:
            stamp,old,old_speed,old_steer,old_brake=previous;dt=tick.t-stamp
            if safe and old_speed is not None and old_steer is not None and 0<dt<=.25 and 0<car.distance-old<=max(20,dt*180):
                # Interpolate exact5m crossing times; sample phase must not become time loss.
                for index in range(int(old//5)+1,int(car.distance//5)+1):
                    part=(index*5-old)/(car.distance-old)
                    self.cells[index]={'speed':old_speed+(speed-old_speed)*part,
                                       'steering':abs(old_steer+(steer-old_steer)*part),
                                       'brake':old_brake+(brake-old_brake)*part
                                           if old_brake is not None and brake is not None else None,
                                       'sample_lo_m':old,'sample_hi_m':car.distance,
                                       't':stamp+dt*part}
        self.reason='measuring' if safe else 'unsafe_or_traffic'
        return events

    @staticmethod
    def section(record,index):
        cells=record['cells']
        required=range(index-8,index+9)
        if not all(i in cells for i in required):return None
        return {'lap':record['lap'],'start_t':cells[index-8]['t'],'end_t':cells[index+8]['t'],
                'minimum_m_s':min(cells[i]['speed'] for i in range(index-3,index+4)),
                'steering_peak':max(cells[i]['steering'] for i in range(index-4,index+5)),
                'seconds':cells[index+8]['t']-cells[index-8]['t']}

    def comparison_set(self,tick):
        """Discover repeatable bends using only intervals preceding the recent three."""
        self.bends=[];history=list(self.history)
        if len(history)<5 or not all(r['clean'] for r in history[-3:]):return history,[],[]
        earlier=[r for r in history[:-3] if r['clean'] and tick.t-r['end_t']<=900]
        if len(earlier)<2:return history,earlier,[]
        discovery=sorted(earlier,key=lambda r:r['seconds'])[:2]
        cells=discovery[0]['cells'];candidates=[]
        for index in sorted(cells):
            d=index*5
            if not 80<d<tick.length-80 or abs(d-tick.length/2)<80:continue
            if not all(i in cells for i in range(index-12,index+13)):continue
            speed=median(cells[i]['speed'] for i in range(index-1,index+2))
            if speed>min(cells[i]['speed'] for i in range(index-7,index+8))+.1:continue
            entry=median(cells[i]['speed'] for i in range(index-12,index-8))
            exit=median(cells[i]['speed'] for i in range(index+9,index+13))
            drop=min(entry,exit)-speed
            if drop<3 or max(cells[i]['steering'] for i in range(index-4,index+5))<.08:continue
            other=self.section(discovery[1],index)
            if not other or other['steering_peak']<.08 or abs(other['minimum_m_s']-speed)>.6:continue
            candidates.append((drop,index))
        chosen=[]
        for _,index in sorted(candidates,reverse=True):
            if all(abs(index-old)*5>=120 for old in chosen):chosen.append(index)
            if len(chosen)==20:break
        self.bends=[{'distance_m':index*5,'source':'earlier_local_speed_and_steering'} for index in sorted(chosen)]
        return history,earlier,sorted(chosen)

    def _patterns(self,tick):
        self.patterns={};history,earlier,chosen=self.comparison_set(tick)
        events=[]
        for index in chosen:
            refs=[]
            for record in sorted(earlier,key=lambda r:r['seconds']):
                section=self.section(record,index)
                if section:refs.append(section)
                if len(refs)==2:break
            recent=[self.section(r,index) for r in history[-3:]]
            if len(refs)<2 or any(r is None for r in recent):continue
            if abs(refs[0]['minimum_m_s']-refs[1]['minimum_m_s'])>.6:continue
            baseline=min(r['minimum_m_s'] for r in refs);typical=median(r['seconds'] for r in refs)
            for r in recent:
                r['minimum_down_kph']=(baseline-r['minimum_m_s'])*3.6
                r['slower_by_s']=r['seconds']-typical
            misses=[r for r in recent if r['minimum_down_kph']>=4 and r['slower_by_s']>=.15]
            if len(misses)<2 or recent[-1] not in misses:continue
            key=str(index);value={'key':key,'distance_m':index*5,'reference_sections':refs,'recent':recent,
                'source':'earlier_local_speed_and_steering','scope':'practice_local_self_comparison',
                'minimum_down_kph':min(r['minimum_down_kph'] for r in misses),
                'cause_attributed':False,'measured_t':tick.t,'token':f"speed:{index}:{history[-1]['lap']}:{tick.t}"}
            self.patterns[key]=value;events.append(value)
        self.diagnostics['confirmed_patterns']+=len(events)
        return sorted(events,key=lambda r:r['minimum_down_kph'],reverse=True)[:1]

    def token(self,key,tick,player):
        value=self.patterns.get(key)
        return value['token'] if value and self.safe(tick,player) and 0<=tick.t-value['measured_t']<PRACTICE_SUMMARY_S else None

    def status(self):
        return {'reason':self.reason,'clean_intervals_completed':self.completed,
                'learned_bends':self.bends,'diagnostics':dict(self.diagnostics)}
