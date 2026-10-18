"""Explicit process isolation for tests that edit only generated game fixtures."""
import pytest

@pytest.fixture
def closed_synthetic_game(monkeypatch):
    monkeypatch.setattr('ams2season.liveries._game_running',lambda:False)
    monkeypatch.setattr('ams2season.bop_files._game_running',lambda:False)
