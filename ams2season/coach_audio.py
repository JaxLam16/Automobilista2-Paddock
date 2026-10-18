"""Offline radio mastering for prepared coaching clips; no speech model dependency."""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np


def read_wav(path):
    with wave.open(str(path), 'rb') as source:
        if source.getsampwidth() != 2 or source.getcomptype() != 'NONE':
            raise ValueError('Expected uncompressed 16-bit PCM WAV audio.')
        audio = np.frombuffer(source.readframes(source.getnframes()), dtype='<i2').astype(float) / 32768
        audio = audio.reshape(-1, source.getnchannels()).mean(axis=1)
        return audio, source.getframerate()


def write_wav(path, audio, rate):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    audio = np.asarray(audio, float).reshape(-1)
    if not len(audio) or not np.isfinite(audio).all() or rate < 8000:
        raise ValueError('Audio must contain finite samples at a supported rate.')
    with wave.open(str(path), 'wb') as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(int(rate))
        target.writeframes((np.clip(audio, -1, 1) * 32767).round().astype('<i2').tobytes())


def speech_rms(audio):
    audio = np.asarray(audio, float)
    active = np.abs(audio) > 0.01
    return float(np.sqrt(np.mean(audio[active] ** 2))) if active.any() else 0.0


def master_radio(audio, rate, *, strength=0.35, target_rms=0.12):
    """Gentle speech-band EQ/saturation, retaining raw masters separately.

    References may already contain radio filtering, so the default mix is modest.
    No noise or beeps are baked in: Crew Chief supplies its radio channel effects.
    """
    audio = np.asarray(audio, float).reshape(-1)
    if not len(audio) or not np.isfinite(audio).all() or rate < 8000:
        raise ValueError('Invalid source audio.')
    if not 0 <= strength <= 1 or not 0 < target_rms < 0.5:
        raise ValueError('Invalid radio mastering settings.')
    threshold = max(0.003, float(np.max(np.abs(audio))) * 0.01)
    active = np.flatnonzero(np.abs(audio) > threshold)
    if not len(active):
        raise ValueError('Source audio is silent.')
    pad = int(rate * 0.08)
    audio = audio[max(0, active[0] - pad):min(len(audio), active[-1] + pad + 1)].copy()
    audio -= audio.mean()
    # Zero-phase EQ is appropriate for offline rendering; padding limits edges.
    n = 1 << (len(audio) + int(rate * 0.2) - 1).bit_length()
    freq = np.fft.rfftfreq(n, 1 / rate)
    db = np.interp(freq, [0, 100, 250, 450, 1500, 3000, 5000, 8000, 24000],
                   [-50, -24, -10, -2, 0, 3, -6, -18, -50])
    filtered = np.fft.irfft(np.fft.rfft(audio, n) * 10 ** (db / 20), n)[:len(audio)]
    filtered = np.tanh(filtered * 1.8) / 1.8
    result = (1 - strength) * audio + strength * filtered
    rms = speech_rms(result)
    if rms <= 0:
        raise ValueError('No speech energy after mastering.')
    result *= target_rms / rms
    peak = float(np.max(np.abs(result)))
    result *= min(1, 10 ** (-1 / 20) / max(peak, 1e-9))
    fade = min(int(rate * 0.008), len(result) // 2)
    if fade:
        result[:fade] *= np.linspace(0, 1, fade)
        result[-fade:] *= np.linspace(1, 0, fade)
    # Polyphase resampling avoids aliasing in 22.05 kHz Crew Chief audio.
    out_rate = 22050
    if rate != out_rate:
        from fractions import Fraction
        # scipy belongs to the isolated generation runtime, not Paddock itself.
        from scipy.signal import resample_poly
        ratio = Fraction(out_rate, int(rate))
        result = resample_poly(result, ratio.numerator, ratio.denominator)
    # Resampling can introduce inter-sample peaks above the pre-resample limit.
    result *= min(1, 10 ** (-1 / 20) / max(float(np.max(np.abs(result))), 1e-9))
    return result, out_rate
