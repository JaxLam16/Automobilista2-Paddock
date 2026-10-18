"""Offline clip mastering: usable PCM, speech-band emphasis and safe levels."""
import wave

import numpy as np
import pytest

from ams2season.coach_audio import master_radio, read_wav, speech_rms, write_wav


def tone(rate=22050, seconds=1):
    t = np.arange(int(rate * seconds)) / rate
    return .15 * np.sin(2 * np.pi * 1000 * t)


def test_pcm_roundtrip_and_source_unchanged(tmp_path):
    source = tmp_path / "raw.wav"
    write_wav(source, tone(), 22050)
    original = source.read_bytes()
    audio, rate = read_wav(source)
    processed, output_rate = master_radio(audio, rate)
    write_wav(tmp_path / "radio.wav", processed, output_rate)
    assert source.read_bytes() == original
    assert np.max(np.abs(audio - tone())) < 1 / 16000
    with wave.open(str(tmp_path / "radio.wav")) as clip:
        assert (clip.getnchannels(), clip.getsampwidth(), clip.getframerate()) == (1, 2, 22050)
    assert np.isfinite(processed).all()
    assert np.max(np.abs(processed)) <= 10 ** (-1 / 20) + 1e-12
    assert speech_rms(processed) == pytest.approx(.12, abs=.003)


def test_radio_emphasizes_speech_over_bass_and_trims_padding():
    rate = 22050
    t = np.arange(rate) / rate
    source = .1 * (np.sin(2 * np.pi * 100 * t) + np.sin(2 * np.pi * 1500 * t))
    padded = np.r_[np.zeros(rate), source, np.zeros(rate)]
    original = padded.copy()
    processed, _ = master_radio(padded, rate, strength=1)
    assert np.array_equal(padded, original)
    assert 1 < len(processed) / rate < 1.17
    spectrum = np.abs(np.fft.rfft(processed))
    freqs = np.fft.rfftfreq(len(processed), 1 / rate)
    bass = spectrum[(freqs > 95) & (freqs < 105)].max()
    speech = spectrum[(freqs > 1495) & (freqs < 1505)].max()
    assert speech > bass * 8
    assert processed[0] == processed[-1] == 0


@pytest.mark.parametrize("source", [[], [float("nan")], [float("inf")], np.zeros(22050)])
def test_unusable_speech_rejected(source):
    with pytest.raises(ValueError):
        master_radio(source, 22050)


def test_peak_limited_for_loud_transients():
    source = tone()
    source[1000] = 10
    result, _ = master_radio(source, 22050, target_rms=.3)
    assert np.abs(result).max() <= 10 ** (-1 / 20) + 1e-12


def test_resample_when_runtime_has_scipy():
    pytest.importorskip("scipy.signal")
    result, rate = master_radio(tone(24000), 24000)
    assert rate == 22050 and abs(len(result) - rate) < 4
    assert np.abs(result).max() <= 10 ** (-1 / 20) + 1e-12
