"""Local-driver corner measurements shared by recordings and the passive skill overlay.

These are measurements and conservative event indicators, not an optimal-lap score.
All thresholds below detect sustained signals; they are not car-specific grip limits.
"""
from __future__ import annotations

import math
import numpy as np

CATALOG = (
    ('turn_in', 'Turn-in point'), ('brake_point', 'Braking point'),
    ('throttle_onset', 'Throttle onset'), ('trail_braking', 'Trail braking'),
    ('peak_brake', 'Peak brake input'), ('minimum_speed', 'Minimum corner speed'),
    ('understeer', 'Front response'), ('oversteer', 'Exit traction / rear control'),
    ('apex', 'Apex proximity'), ('exits', 'Exit use'),
    ('steering', 'Steering smoothness'), ('gearing', 'Gearing'),
    ('throttle_application', 'Throttle application'))
LABELS = dict(CATALOG)
CHANNELS = ('yaw_rate', 'acc_lat', 'acc_long', 'acc_vert', 'vel_lat', 'vel_long',
            'rpm', 'max_rpm', 'x', 'z', 'crash_state')


def _number(v):
    return round(float(v), 2) if v is not None and np.isfinite(v) else None


def _runs(mask):
    return list(zip(*[iter(np.flatnonzero(np.diff(np.r_[False, mask, False].astype(int))))]*2))


def measure(lap, corner, length, *, before=300., after=180., geometry=None, complete=True):
    """Measure one observed pass. Inputs follow technique.recording_laps units.

    Relative distances are to the configured/detected corner landmark, not a proven
    ideal apex. Complete entry/exit coverage and continuous, advancing telemetry are
    required. Live partial passes explicitly carry provisional=True.
    """
    result = {'corner': str(corner['name']), 'apex': float(corner['apex']),
              'lap': lap.get('n'), 'source': 'local_telemetry', 'reference': 'telemetry',
              'provisional': not complete, 'metrics': {}, 'elapsed_s':None}
    def put(key, value=None, unit='', detail='', status='measured', channels=(), scale=None):
        if value is not None and scale is None:
            if key in ('turn_in','brake_point','throttle_onset'):
                scale={'fraction':max(0.,min(1.,(value+before)/(before+after))),
                       'left':f'{before:.0f} m before landmark','right':f'{after:.0f} m after','kind':'measurement'}
            else:
                ranges={'minimum_speed':(300,'0 km/h','300 km/h'),
                        'understeer':(2,'No event','2 s+ response drop'),
                        'gearing':(5,'No event','5 s+ near max RPM'),
                        'throttle_application':(3,'No withdrawal','3+ withdrawals'),
                        'apex':(4,'At inside edge','4 m+ clearance'),
                        'exits':(4,'At outside edge','4 m+ clearance')}
                if key in ranges:
                    maximum,left,right=ranges[key]
                    scale={'fraction':max(0.,min(1.,value/maximum)),'left':left,'right':right,'kind':'measurement'}
        result['metrics'][key] = {'label': LABELS[key], 'value': _number(value), 'unit': unit,
            'detail': detail, 'status': status if value is not None else 'unavailable',
            'channels': list(channels), 'scale': scale}
    def unavailable(reason):
        for key, _ in CATALOG: put(key, detail=reason)
        return result
    if not np.isfinite(length) or not 100<=length<=100000 or before<=0 or after<=0:
        return unavailable('Invalid track length or corner window.')
    if not lap.get('valid', False): return unavailable('Lap invalid or incident affected; no skill judgment.')
    t, ld = (np.asarray(lap.get(k, []), float) for k in ('t', 'ld'))
    if len(t) < 8 or len(t) != len(ld) or not np.isfinite(t).all() or not np.isfinite(ld).all():
        return unavailable('Insufficient continuous local telemetry.')
    rel = (ld - float(corner['apex']) + length/2) % length - length/2
    take = (rel >= -before) & (rel <= after)
    indexes = np.flatnonzero(take)
    if len(indexes) < 8: return unavailable('Corner not yet measured.')
    # A lap straddling the timing line can have two disjoint time intervals. Never
    # splice them, or a dropout/reverse/teleport, into one corner measurement.
    times, x = t[take], rel[take]
    dt = np.diff(times)
    if (dt <= 0).any() or (dt > .35).any() or (np.diff(x) < -.5).any():
        return unavailable('Telemetry gap, reverse motion or timing boundary; pass withheld.')
    duration = np.r_[dt, 0.]
    def channel(key):
        a = lap.get(key)
        return np.asarray(a, float)[take] if a is not None and len(a)==len(t) else np.full(len(times), np.nan)
    speed, brake, throttle, steer = (channel(k) for k in ('speed','brake','throttle','steer'))
    if not all(np.isfinite(a).all() for a in (speed, brake, throttle)):
        return unavailable('Missing pedal or speed samples.')
    if (speed < 10).any() or x[0] > -min(before*.7, 45):
        return unavailable('Corner entry not covered continuously at driving speed.')
    if complete and x[-1] < min(after*.7, 35): return unavailable('Corner exit not covered.')
    a=max(0,int(indexes[0])-1);b=min(len(t),int(indexes[-1])+2)
    span=rel[a:b]
    if complete and len(span)>1 and (np.diff(span)>=0).all() and span[0]<=-before and span[-1]>=after:
        boundaries=np.interp([-before,after],span,t[a:b])
        result['elapsed_s']=round(float(boundaries[1]-boundaries[0]),4)
    def sustained(mask, seconds=.25):
        out = np.zeros(len(times), bool)
        for a,b in _runs(mask):
            if duration[a:b].sum() >= seconds: out[a:b] = True
        return out
    def first(mask):
        i=np.flatnonzero(sustained(mask)); return float(x[i[0]]) if len(i) else None
    def seconds(mask): return float(duration[sustained(mask)].sum())
    def gauge(v, maximum, left, right):
        return {'fraction': max(0.,min(1.,v/maximum)), 'left':left,'right':right,'kind':'measurement'}
    near = (x>=-min(before,100)) & (x<=min(after,70))
    vi = np.flatnonzero(near)
    if not len(vi): return unavailable('Corner centre not yet reached.')
    minimum = int(vi[np.argmin(speed[near])])
    put('minimum_speed', speed[minimum], 'km/h', 'Observed minimum; no optimal speed target.', channels=('speed',))
    entry=x<=min(0,x[minimum])
    from .technique import _brake_event
    padded=_brake_event(np.r_[x[0]-1,x],np.r_[brake[0],brake],(-before,min(20,after)))
    brake_event=(padded[0],*[i-1 for i in padded[1:]]) if padded else None
    onset=float(x[brake_event[1]]) if brake_event else None
    put('brake_point',onset,'m to landmark','Sustained input above 5%. '+('Already braking at window entry; no distinct onset.' if onset is None else 'Negative = before the corner landmark; no early/late target.'),channels=('brake',))
    peak=float(np.max(brake[entry])) if entry.any() else None
    put('peak_brake',peak,'%', 'Pedal input, not hydraulic pressure; no universal ideal peak.',channels=('brake',),scale=gauge(peak,100,'0% input','100% input') if peak is not None else None)
    turning=sustained((np.abs(steer)>2.5)&entry) if np.isfinite(steer).all() else np.zeros(len(times),bool)
    turn=first(turning) if np.isfinite(steer).all() and abs(steer[0])<=2.5 else None
    put('turn_in',turn,'m to landmark','Sustained steering beyond 2.5% input; linked turns may have no separate turn-in.',channels=('steering',))
    overlap=seconds((brake>5)&(np.abs(steer)>2.5)&(x<=20)) if np.isfinite(steer).all() else None
    # Inspect the actual reduction after the main peak, not just overlap time.
    # A monotone abrupt dump is not a smooth trail, and reapplications are distinct.
    pi=brake_event[2] if brake_event else int(np.argmax(np.where(entry,brake,-1)))
    off=np.flatnonzero(sustained((brake<=5)&(np.arange(len(times))>pi),.15))
    release=int(off[0]) if len(off) else None
    if brake_event and peak is not None and peak>10 and release is not None and release>pi:
        plateau=np.flatnonzero((brake>=brake[pi]-1)&(np.arange(len(times))>=pi)&(np.arange(len(times))<release))
        if len(plateau):pi=int(plateau[-1])
        sample_t=np.r_[np.arange(times[pi],times[release],.1),times[release]]
        sampled=np.interp(sample_t,times,brake)
        changes=np.diff(sampled)
        rises=float(np.maximum(0,changes-1).sum())
        largest=float(np.max(-changes)) if len(changes) else 0.
        release_s=float(times[release]-times[pi])
        put('trail_braking',release_s,'s release',f'Peak to ≤5%: {release_s:.2f} s; release at {x[release]:+.0f} m to landmark. Reapplications: {rises:.1f} input points; largest 0.1 s drop: {largest:.1f} points. '+
            (f'Brake/steering overlap: {overlap:.2f} s. ' if overlap is not None else '')+
            'Smoothness and release location are separate; no universal apex-release target.',status='caution' if largest>35 or rises>10 else 'measured',channels=('brake','steering'),scale=gauge(largest,100,'Gentler release','Larger 0.1 s drop'))
        result['metrics']['trail_braking']['release']={'seconds':_number(release_s),'distance_m':_number(x[release]),'reapplication_points':_number(rises),'largest_drop_per_0_1s':_number(largest),'overlap_s':_number(overlap)}
    else:
        put('trail_braking',detail='No complete main brake-release phase observed yet; a flat-out corner has no trail-braking requirement.')
    from .technique import _filter_throttle
    filtered,shift = _filter_throttle(lap)
    thr=np.asarray(filtered,float)[take]
    # A pickup needs an actual low-throttle phase followed by sustained power.
    # Constant modulation is not repeatedly starting/stopping a corner exit.
    low=np.flatnonzero((thr<15)&(np.arange(len(times))<=minimum))
    pickup=first((thr>20)&(np.arange(len(times))>low[-1])) if len(low) else None
    put('throttle_onset',pickup,'m to landmark','Shift cuts/blips filtered. '+('Continuously modulated or no distinct pickup.' if pickup is None else 'Observed pickup; no optimal timing target.'),channels=('throttle','gear'))
    exit_mask=(np.arange(len(times))>=minimum)&(x<=after)
    withdrawals=0;high=-1;start=None;counted=False
    for i in np.flatnonzero(exit_mask):
        if high<0 or thr[i]>thr[high]:high=i
        if start is None and thr[high]-thr[i]>=15:start=i
        if start is not None:
            if thr[i]>=thr[high]-5:high=i;start=None;counted=False
            elif not counted and times[i]-times[start]>=.25:withdrawals+=1;counted=True
    put('throttle_application',withdrawals,'withdrawals','Sustained drops ≥15 input points after minimum speed, with gear transients filtered. Modulation can be required; this is not a time-loss penalty.',channels=('throttle','gear'))
    if np.isfinite(steer).all():
        # Rate on a 0.15s time basis suppresses one-sample noise and is invariant
        # to 10/20/60Hz capture. No penalty for being "too smooth".
        prev=np.interp(times-.15,times,steer)
        rate=np.abs(steer-prev)/.15
        rate=rate[(times>=times[0]+.15)&near]
        value=float(np.percentile(rate,90)) if len(rate) else None
        put('steering',value,'% input/s','90th-percentile steering rate over 0.15 s. Corrections, chicanes and wheel settings affect it; lower is not automatically faster.',channels=('steering',),scale=gauge(value,150,'Slower input','Faster input') if value is not None else None)
    else: put('steering',detail='Steering input was not recorded.')
    yaw,lat,long,ay,az=(channel(k) for k in ('yaw_rate','vel_lat','vel_long','acc_lat','acc_vert'))
    shift_near=np.zeros(len(times),bool)
    gears=channel('gear')
    for i in np.flatnonzero(np.diff(gears)!=0)+1:
        if np.isfinite(gears[i-1:i+1]).all(): shift_near |= np.abs(times-times[i])<=.4
    if all(np.isfinite(a).all() for a in (yaw,lat,long,ay,az,steer)):
        slip=np.degrees(np.arctan2(np.abs(lat),np.maximum(np.abs(long),1)))
        calm=(np.abs(az)<18)&~shift_near
        counter=(steer*yaw>0)&(np.abs(steer)>2.5)&(np.abs(yaw)>.08)&(np.abs(ay)>3)&(speed>45)
        event=counter&(slip>5)&(thr>30)&exit_mask&calm
        value=seconds(event)
        put('oversteer',value,'s','Sustained on-power body-slip (>5°) with countersteer. Shifts and large vertical accelerations excluded. Indicates a correction, not measured rear-tyre slip or proof of excess throttle.',status='caution' if value else 'measured',channels=('steering','yaw_rate','vel_lat','vel_long','acc_lat','acc_vert','throttle','gear'),scale=gauge(value,2,'No event','2 s+ correction'))
        result['metrics']['oversteer']['observed_power_s']=_number(seconds((thr>30)&exit_mask&(speed>45)&calm))
        prior=np.searchsorted(times,times-.4)
        response=(np.abs(steer)-np.abs(steer[prior])>3)&(np.abs(yaw)<np.abs(yaw[prior])*.8)&(np.abs(speed-speed[prior])<5)&(steer*yaw<0)&(np.abs(ay)>4)&calm
        value=seconds(response&near)
        put('understeer',value,'s','Steering increases while yaw response falls at similar speed. A front-response proxy; cannot establish tyre grip limit or its cause.',status='caution' if value else 'measured',channels=('steering','yaw_rate','speed','acc_lat','acc_vert','gear'))
    else:
        put('oversteer',detail='Needs body velocity, yaw, acceleration and steering channels; no slide inferred from throttle alone.')
        put('understeer',detail='Needs yaw, acceleration, body velocity and steering; no front-grip estimate from pedals alone.')
    rpm,mx=channel('rpm'),channel('max_rpm')
    if np.isfinite(rpm).all() and np.isfinite(mx).all() and (mx>0).all():
        limited=seconds((rpm>=mx*.985)&(thr>80)&(gears>0))
        put('gearing',limited,'s near max RPM','Above 98.5% of reported maximum RPM on power. This is not a shift-light target; gearing/torque curves are car-specific.',status='caution' if limited>.5 else 'measured',channels=('rpm','max_rpm','gear','throttle'))
    else: put('gearing',detail='No complete RPM/maximum-RPM trace; optimal shift points and downshift instability cannot be inferred.')
    for key, zone in (('apex',np.abs(x)<=20),('exits',(x>=20)&(x<=40))):
        gaps=[]
        if geometry is not None:
            mapped=next((c for c in geometry.corners if c['name']==corner['name']),None)
            if mapped:
                xx,zz=channel('x'),channel('z')
                for i in np.flatnonzero(zone&np.isfinite(xx)&np.isfinite(zz)):
                    if not mapped['sections'][0]['d']<=ld[take][i]<=mapped['sections'][-1]['d']: continue
                    g=geometry.gap(mapped,float(ld[take][i]),float(xx[i]),float(zz[i]))
                    if g is not None:
                        if key=='exits':
                            # Gap from centre to inside + outside = measured local width.
                            section=min(mapped['sections'],key=lambda s:abs(s['d']-ld[take][i]))
                            g=section['width']-g
                        gaps.append(max(0.,g-.85))
        put(key,float(np.median(gaps)) if len(gaps)>=4 else None,'m wheel clearance',
            ('Measured inside-edge proximity near the landmark. ' if key=='apex' else 'Measured outside-edge proximity just after the landmark. Linked-corner compromises are not penalized. ')+
            'Uses an estimated 0.85 m half-width; not an optimal line or track-limits judgment.' if gaps else
            'Requires matching measured track edges and positions. No invented boundaries or wide-exit penalty.',channels=('x','z','measured_track_edges'))
    return result


def report(laps, corners, length, geometry=None, racing=None):
    clean=[lp for lp in laps if lp.get('valid')]
    passes=[]
    for lp in clean:
        for i,c in enumerate(corners):
            before=min(300.,((c['apex']-corners[i-1]['apex'])%length)/2) if len(corners)>1 else 300.
            after=min(180.,((corners[(i+1)%len(corners)]['apex']-c['apex'])%length)/2) if len(corners)>1 else 180.
            p=measure(lp,c,length,before=before,after=after,geometry=geometry)
            p['racing']=(racing or {}).get((lp['n'],c['name']))
            passes.append(p)
    # Rank linked sequences together, preserving the payoff in the next corner.
    groups={c['name']:{c['name']} for c in corners}
    if len(corners)>1:
        from .metrics import _linked_exit
        for i,c in enumerate(corners):
            nxt=corners[(i+1)%len(corners)]
            if c.get('exit_policy')=='compromise' or _linked_exit(c,nxt,length,None):
                merged=groups[c['name']]|groups[nxt['name']]
                for name in merged:groups[name]=merged
    lookup={(p['lap'],p['corner']):p for p in passes}
    for p in passes:
        linked=groups[p['corner']];rows=[lookup[(p['lap'],name)] for name in linked]
        p['linked_corners']=sorted(linked)
        p['ranking_time_s']=round(sum(q['elapsed_s'] for q in rows),4) if all(q['elapsed_s'] is not None for q in rows) else None
        p['group_racing']=True if any(q['racing'] is True for q in rows) else False if all(q['racing'] is False for q in rows) else None
    from .skill_references import corner_targets
    return {'catalog':[{'id':k,'label':v} for k,v in CATALOG], 'reference':'telemetry',
            'best_lap':min(clean,key=lambda p:p.get('time',float('inf')))['n'] if clean else None,
            'optimality_scored':False,'clean_laps':len(clean),'passes':passes,'targets':corner_targets(passes),
            'note':'Local driver only. Measurements and conservative indicators; no professional pace target is assumed.'}
