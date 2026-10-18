import copy
import pytest
from ams2season.skill_feedback import assessment
from ams2season.skills import CATALOG
from test_skills import measured


def test_unqualified_measurement_does_not_become_green_optimal_rating():
    m=assessment('steering',measured()['metrics']['steering'])
    assert m['scale']['fraction'] is None and m['feedback']=='Target needed'
    assert m['scale']['bands']=='red_yellow_green_yellow_red'


def test_release_feedback_is_centrally_good_only_for_supported_smooth_reduction():
    raw=measured()['metrics']['trail_braking'];m=assessment('trail_braking',raw)
    assert m['feedback']=='Great release' and m['scale']['fraction']==.5
    raw['release']['largest_drop_per_0_1s']=90
    bad=assessment('trail_braking',raw)
    assert bad['feedback']=='Ease off smoothly' and bad['scale']['fraction']<.15
    assert 'not_optimal_line' in bad['assessment_basis']


def test_no_power_exposure_does_not_earn_controlled_exit():
    m=measured()['metrics']['oversteer'];m['observed_power_s']=0
    assert assessment('oversteer',m)['feedback']=='Target needed'
    m['observed_power_s']=2
    assert assessment('oversteer',m)['feedback']=='Controlled exit'
    m['value']=1.5
    assert assessment('oversteer',m)['feedback']=='Settle the rear'


def test_brake_earlier_requires_chosen_qualified_layout_car_class_comparison():
    m=measured()['metrics']['brake_point'];ref=copy.deepcopy(m);ref['value']=m['value']-25
    assert assessment('brake_point',m)['feedback']=='Target needed'
    result=assessment('brake_point',m,reference=ref,reference_kind='same_class')
    assert result['feedback']=='Brake earlier'
    assert result['assessment_basis']=='same_class_chosen_comparison'
    exact=assessment('brake_point',m,reference=ref,reference_kind='exact_car')
    assert abs(result['scale']['fraction']-.5)<abs(exact['scale']['fraction']-.5)


def test_partial_or_unavailable_pass_never_says_great():
    m=measured()['metrics']['trail_braking']
    assert assessment('trail_braking',m,provisional=True)['feedback']=='Measuring'
    m['value']=None;assert assessment('trail_braking',m)['feedback']=='Not measured'
