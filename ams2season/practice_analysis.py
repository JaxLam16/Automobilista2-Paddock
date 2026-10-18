"""Session telemetry for practice pages, without race positions, passes or awards."""
from types import SimpleNamespace
import numpy as np
import pandas as pd
from .derive import add_distance,effective_track_length,reference_lap_xy,speed_profile,curvature_profile,custom_corners,detect_corners
from .quali import session_laps
from .race import incidents_from_events,_norm


def analyze_practice_telemetry(session,humans=None,corners_override=None,mode='reduced',track_samples=None,track_width=None):
    length,_=effective_track_length(session.frames,session.L)
    fr=add_distance(session.frames,length)
    records=[];stats=[];entrants=[]
    local=(session.meta.get('local') or {}).get('name')
    human_names={_norm(n) for n in humans or ()}|{_norm(local)}
    for name,g in fr.groupby('name',sort=False):
        laps=session_laps(g,length)
        row=g.iloc[-1]
        ai=_norm(name) not in human_names
        entrants.append({'name':name,'car':row.get('car',''),'car_class':row.get('car_class',''),'is_ai':ai})
        good=laps[laps.valid] if len(laps) else laps
        if len(good):good=good[good.time<=good.time.min()*1.07]
        good_ids=set(good.k) if len(good) else set()
        for lp in laps.itertuples():
            records.append({'name':name,'lap':int(lp.k)+1,'t_start':lp.t0,'t_end':lp.t1,'time':lp.time,
                            'valid':bool(lp.valid),'clean':lp.k in good_ids,'pit':not bool(lp.valid),
                            's1':lp.s1,'s2':lp.s2,'s3':lp.s3,'position':np.nan})
        stats.append({'name':name,'is_ai':ai,'finish':np.nan,'median_clean':float(good.time.median()) if len(good) else np.nan,
                      'best_lap':float(good.time.min()) if len(good) else np.nan,'top_speed_kph':float(g.speed.max()*3.6)})
    lap_table=pd.DataFrame(records,columns=['name','lap','t_start','t_end','time','valid','clean','pit','s1','s2','s3','position'])
    entrants=pd.DataFrame(entrants)
    stats=pd.DataFrame(stats)
    classification=entrants.merge(stats[['name','best_lap']],on='name').sort_values('best_lap',na_position='last')
    profile=speed_profile(fr,length)
    xy=reference_lap_xy(fr,lap_table)
    curvature=curvature_profile(*xy,length) if xy else None
    corners=custom_corners(corners_override,profile,curvature) if corners_override else detect_corners(profile,curvature=curvature)
    from .metrics import driving_metrics,strength_columns
    edges=None
    if xy:
        from .trackmap import track_geometry,recording_edge_samples
        geometry=track_geometry(fr,*xy,length,normal={(r.name,int(r.lap)-1) for r in lap_table[lap_table.clean].itertuples()},
                                samples=track_samples,width=track_width,extra_samples=recording_edge_samples(session),cloud_points=0)
        if geometry.get('offsets'):edges=dict(geometry['offsets'],source=geometry.get('edges',{}).get('source','estimated'))
    dm,speeds=driving_metrics(fr,lap_table,corners,length,xy,edges,mode=mode)
    if len(dm):stats=stats.merge(dm,on='name',how='left')
    if len(speeds):stats=stats.merge(strength_columns(stats,lap_table,speeds,corners),on='name',how='left')
    from .technique import technique_report,throttle_consistency_summary
    pedal=technique_report(session,corners_override,mode=mode)
    measured=stats.name==pedal.get('driver')
    scores=throttle_consistency_summary(pedal)
    stats['throttle_rating_source']='acceleration'
    if measured.any():
        stats.loc[measured,'throttle_rating_source']='pedals' if scores.get(mode) is not None else 'unavailable'
        stats.loc[measured,'throttle_consistency']=scores.get(mode,np.nan)
        for key in ('equal','reduced','excluded'):stats.loc[measured,'throttle_consistency_'+key]=scores.get(key,np.nan)
    return SimpleNamespace(session=session,frames=fr,laps=lap_table,entrants=entrants,classification=classification,
                           stats=stats,corners=corners,corner_speeds=speeds,racing_mode=mode,
                           passes=pd.DataFrame(columns=['t','passer','passed','kind']),incidents=incidents_from_events(session))
