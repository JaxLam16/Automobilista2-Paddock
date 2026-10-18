"""Explicit comparison eligibility. A same-class lap is context, not an optimal target."""
from .coach.model import finite


def corner_targets(passes):
    """Each target is from a real fast clean pass; lower/higher is not inherently better.

    Timing includes the exit, and linked sequences share a ranking time. Skills
    with unambiguous event/shape indicators can select a cleaner example within
    0.2 s of the fastest eligible sequence. No synthetic impossible trace is made.
    """
    out={}
    for name in dict.fromkeys(p['corner'] for p in passes):
        rows=[p for p in passes if p['corner']==name and not p.get('provisional') and
              finite(p.get('ranking_time_s')) is not None and p['ranking_time_s']>0 and p.get('group_racing') is not True]
        if not rows:continue
        known=[p for p in rows if p.get('group_racing') is False]
        if known:rows=known
        fastest=min(p['ranking_time_s'] for p in rows)
        pool=sorted([p for p in rows if p['ranking_time_s']<=fastest+.2],key=lambda p:p['ranking_time_s'])[:5]
        targets={}
        for key in pool[0]['metrics']:
            supported=[p for p in pool if p['metrics'][key].get('value') is not None]
            if not supported:continue
            def quality(p):
                m=p['metrics'][key]
                if key=='trail_braking' and m.get('release'):
                    r=m['release'];return r['reapplication_points']/10+r['largest_drop_per_0_1s']/35
                if key in ('oversteer','throttle_application'):return m['value']
                return 0
            chosen=min(supported,key=lambda p:(quality(p),p['ranking_time_s']))
            targets[key]={'lap':chosen['lap'],'apex':chosen['apex'],'metric':chosen['metrics'][key],
                          'ranking_time_s':chosen['ranking_time_s'],'linked_corners':chosen.get('linked_corners',[name]),
                          'candidates':len(supported),'traffic_known':chosen.get('group_racing') is False,
                          'method':'measured_technique_among_fast_clean_passes' if key in ('trail_braking','oversteer','throttle_application') else 'fastest_eligible_corner_sequence'}
        if targets:out[name]=targets
    return out


def match(current, reference):
    for k in ('track_location','track_variation'):
        if not current.get(k) or current.get(k)!=reference.get(k):return None
    a,b=(finite(m.get('track_length')) for m in (current,reference))
    if a is None or b is None or abs(a-b)>.5:return None
    local,other=(m.get('local') or {} for m in (current,reference))
    if not other.get('name') or not other.get('car'):return None
    if any(r.get('name')==other['name'] and r.get('is_ai') is True for r in reference.get('final') or []):return None
    exact=bool(local.get('car') and local['car'].casefold()==other['car'].casefold())
    same=bool(local.get('car_class') and local['car_class'].casefold()==str(other.get('car_class','')).casefold())
    return 'exact_car' if exact else 'same_class' if same else None


def compare(current, reference, kind):
    """Best clean reference pass set; no cross-car quality grades or time-loss claims."""
    passes=reference.get('passes',[])
    laps={p['lap'] for p in passes}
    best=reference.get('best_lap')
    if best is None and laps:best=min(laps)
    targets=reference.get('targets') or corner_targets(passes)
    values=[]
    for p in current.get('passes',[]):
        corner=targets.get(p['corner']) or {}
        delta={}
        for key,met in p['metrics'].items():
            target=corner.get(key)
            if not target or abs(target['apex']-p['apex'])>10:continue
            other=target['metric']
            a,b=met.get('value'),other.get('value')
            if a is not None and b is not None and met['unit']==other.get('unit'):
                delta[key]={'difference':round(a-b,2),'reference_value':b,'unit':met['unit'],'reference_lap':target['lap'],
                            'method':target['method'],'linked_corners':target['linked_corners'],'traffic_known':target['traffic_known']}
        if delta:values.append({'corner':p['corner'],'lap':p['lap'],'metrics':delta})
    return {'kind':kind,'reference_lap':None,'reference_method':'corner_by_corner_per_skill','differences':values,'quality_scores':False,
            'note':('Same-class comparison: car-specific speed, brake/steering inputs and setup differ. ' if kind=='same_class' else 'Exact-car comparison: setup, tyres and conditions may differ. ')+
                   'Differences describe the laps; they do not prove a mistake, optimal technique or time loss.'}
