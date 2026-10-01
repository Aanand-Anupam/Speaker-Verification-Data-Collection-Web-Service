from __future__ import annotations

import io

import soundfile as sf


def validate_recording(payload: bytes, max_duration_seconds: float) -> float:
    if not payload or len(payload) > 10 * 1024 * 1024:
        raise ValueError("Recording is empty or exceeds the 10 MB upload limit.")
    try:
        info = sf.info(io.BytesIO(payload))
        if info.format != "WAV" or info.subtype != "PCM_16": raise ValueError("Upload must be 16-bit PCM WAV.")
        if info.samplerate != 16000 or info.channels != 1: raise ValueError("Upload must be mono at 16,000 Hz.")
        samples, _ = sf.read(io.BytesIO(payload), dtype="float32", always_2d=True)
        duration = len(samples) / info.samplerate
        if duration <= 0: raise ValueError("Recording has no audio samples.")
        if duration > max_duration_seconds + 0.05: raise ValueError(f"Recording exceeds the {max_duration_seconds:g}-second limit.")
        return duration
    except ValueError: raise
    except Exception as exc: raise ValueError("Upload is not a readable WAV recording.") from exc
