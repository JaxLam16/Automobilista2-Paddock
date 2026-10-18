from ams2season.driver_presets import catalogue
from ams2season.app import App


def test_presets_are_season_labelled_independent_name_sources(tmp_path):
    data = App(tmp_path).route('GET', '/api/driver-name-presets', {}, {})
    groups = {g['id']: g for g in data['groups']}
    assert len(groups['f1-2026']['names']) == 22
    assert 'Ayrton Senna' in groups['f1-legends']['names']
    assert 'Scott Dixon' in groups['indycar-legends']['names']
    assert 'Tom Kristensen' in groups['lemans-legends']['names']
    assert 'Chris Lulham' in groups['gtwc-portimao-2026']['names']
    assert len(groups['gtwc-portimao-2026']['names']) == 183
    assert all(g['sources'] and g['checked'] for g in groups.values())
    assert all(g['season'] == 2026 for g in groups.values() if g['season'])
    assert len({n.casefold() for g in groups.values() for n in g['names']}) >= 350
    # Reading suggestions never adds drivers or changes an existing championship.
    assert not list((tmp_path / 'championships').glob('*.db'))
