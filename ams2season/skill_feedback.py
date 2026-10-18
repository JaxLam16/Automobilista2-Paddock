"""Bounded one-phrase coaching. No arbitrary raw value becomes an ideal green score."""
from copy import deepcopy

AXES={
 'turn_in':('Earlier','Later'), 'brake_point':('Earlier','Later'),
 'throttle_onset':('Earlier','Later'), 'trail_braking':('Abrupt release','Reapplications'),
 'peak_brake':('Less input','More input'), 'minimum_speed':('Slower','Faster'),
 'understeer':('More rotation','Less response'), 'oversteer':('Controlled','Rear correction'),
 'apex':('Closer','Further away'), 'exits':('Wider','Narrower'),
 'steering':('Slower input','Faster input'), 'gearing':('Lower RPM','Higher RPM'),
 'throttle_application':('Fewer lifts','More lifts')}
SPANS={'turn_in':30,'brake_point':30,'throttle_onset':30,'trail_braking':1.,
       'peak_brake':25,'minimum_speed':20,'understeer':1,'oversteer':1,
       'apex':1.5,'exits':1.5,'steering':40,'gearing':2,'throttle_application':2}


def assessment(key,metric,*,reference=None,reference_kind=None,provisional=False):
    m=deepcopy(metric or {'label':'Skill','value':None,'status':'unavailable','detail':'Waiting for evidence.'})
    left,right=AXES[key]
    position=None;phrase='Target needed';basis='no_target';tone='neutral'
    if m.get('value') is None:phrase='Not measured'
    elif provisional:phrase='Measuring'
    elif key=='trail_braking' and m.get('release'):
        r=m['release'];drop=r['largest_drop_per_0_1s'];rises=r['reapplication_points']
        if drop>35:position=.5-min(.5,drop/100*.5);phrase='Ease off smoothly';tone='caution'
        elif rises>10:position=.5+min(.5,rises/30*.5);phrase='Smooth the release';tone='caution'
        else:position=.5;phrase='Great release';tone='good'
        basis='measured_release_shape_not_optimal_line'
    elif key=='oversteer' and (m.get('observed_power_s') or 0)>=.5:
        position=.5+min(.5,m['value']/2*.5)
        phrase='Settle the rear' if m['value']>=.25 else 'Controlled exit';tone='caution' if m['value']>=.25 else 'good'
        basis='sustained_body_motion_and_countersteer_not_rear_tyre_slip'
    elif key=='understeer' and m['value']>=.25:
        position=.5+min(.5,m['value']/2*.5);phrase='Check front grip';tone='caution';basis='steering_yaw_response_proxy'
    elif key=='gearing' and m['value']>.5:
        position=.5+min(.5,m['value']/3*.5);phrase='Watch the revs';tone='caution';basis='reported_max_rpm_not_optimal_shift_point'
    elif reference and reference.get('value') is not None:
        delta=m['value']-reference['value'];span=SPANS[key]*(1.5 if reference_kind=='same_class' else 1)
        position=max(0,min(1,.5+delta/(2*span)));basis=reference_kind+'_chosen_comparison'
        if abs(delta)<=span*.2:phrase='On target';tone='good'
        elif key=='brake_point':phrase='Brake earlier' if delta>0 else 'Brake later';tone='compare'
        elif key=='turn_in':phrase='Turn in earlier' if delta>0 else 'Turn in later';tone='compare'
        elif key=='throttle_onset':phrase='Earlier pickup' if delta>0 else 'Later pickup';tone='compare'
        elif key=='minimum_speed':phrase='Below reference' if delta<0 else 'Above reference';tone='compare'
        else:phrase='Below reference' if delta<0 else 'Above reference';tone='compare'
    m.update(scale={'fraction':position,'left':left,'right':right,'kind':'comparison' if reference else 'technique_indicator',
                    'bands':'red_yellow_green_yellow_red'},feedback=phrase,feedback_tone=tone,assessment_basis=basis)
    return m
