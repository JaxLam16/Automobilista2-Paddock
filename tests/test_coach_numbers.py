"""Speech formats at timing/unit boundaries; no guessed zero or fuel consumption."""
import pytest

from ams2season.coach.numbers import Numbers, Units


def test_gap_rounding_handles_ten_second_boundary_and_lap_time_carry():
    fmt=Numbers()
    assert fmt.gap(1.25).text=='1.3 s'
    assert fmt.gap(9.94).speech=='nine point nine seconds'
    assert fmt.gap(9.96).text=='10 s'
    assert fmt.gap(10.5).speech=='eleven seconds'
    assert fmt.lap_time(92.54).speech=='one thirty-two five'
    assert fmt.lap_time(121.4).speech=='two oh one four'
    assert fmt.lap_time(59.96).text=='1:00.0'
    assert fmt.lap_time(59.96).speech=='one zero zero zero'
    assert fmt.delta(-.04).speech=='zero point zero seconds'
    assert fmt.delta(.15).text=='+0.2 s'
    assert fmt.delta(-.15).speech=='minus zero point two seconds'


def test_conversions_keep_source_units_explicit_and_pressure_precision():
    metric=Numbers()
    assert metric.pressure_bar(1.855).text=='1.86 bar'
    assert metric.temperature_c(90.5).text=='91 °C'
    assert metric.distance_m(100).text=='100 m'
    imperial=Numbers(Units(distance='ft',pressure='psi',temperature='f',fuel='us_gallons'))
    assert imperial.pressure_bar(1.85).text=='26.8 psi'
    assert imperial.distance_m(100).text=='328 ft'
    assert imperial.temperature_c(90).text=='194 °F'
    assert imperial.fuel_litres(37.85411784).text=='10.0 US gal'
    assert imperial.examples()['pressure']['speech']=='twenty-six point eight P S I'


@pytest.mark.parametrize('bad',[None,True,float('nan'),float('inf'),'unknown',-1])
def test_unknown_or_invalid_gap_is_never_spoken_as_zero(bad):
    with pytest.raises(ValueError):Numbers().gap(bad)


def test_fuel_laps_require_supplied_measured_consumption():
    fmt=Numbers(Units(fuel='laps'))
    assert fmt.fuel_litres(20,litres_per_lap=2.5).speech=='eight point zero laps'
    for bad in (None,0,-1,float('nan')):
        with pytest.raises(ValueError):fmt.fuel_litres(20,litres_per_lap=bad)


def test_unit_preferences_are_independent_and_reject_unknown_options():
    original=Units()
    assert original.update({'pressure':'psi'}).distance=='m'
    assert original.pressure=='bar'
    for values in ({'pressure':'kpa'},{'distance':'yards'},{'unrecognised':'yes'},[],{'fuel':'gallons'}):
        with pytest.raises(ValueError):original.update(values)
