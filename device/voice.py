#!/usr/bin/env python3
"""
Orpheus TTS voice test — send text, play back audio.

Usage:
    python voice.py "Hello, this is a test of the Orpheus TTS system."
    python voice.py --url http://10.0.0.5:5005 "Check out this brand!"
    python voice.py --voice tara --speed 1.2 "Fast speech test"

Requires: pip install sounddevice numpy scipy httpx
"""

from __future__ import annotations

import argparse
import io
import sys
import wave
from typing import Optional, Sequence

import numpy as np

try:
    import httpx
except ImportError:
    sys.exit("httpx is required.  pip install httpx")

try:
    import sounddevice as sd
except ImportError:
    sys.exit("sounddevice is required.  pip install sounddevice")


def synthesize(
    text: str,
    *,
    base_url: str = "http://localhost:11434",
    voice: str = "dan",
    speed: float = 1.0,
    timeout: float = 60.0,
) -> tuple[np.ndarray, int]:
    """Call the Orpheus TTS endpoint and return (samples, sample_rate)."""
    payload = {
        "model": "orpheus",
        "input": text,
        "voice": voice,
        "response_format": "wav",
        "speed": speed,
    }
    url = f"{base_url.rstrip('/')}/api/generate"
    print(f"[voice] POST {url}  voice={voice} speed={speed}")
    print(f"[voice] Text: {text!r}")

    with httpx.Client(timeout=httpx.Timeout(timeout)) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()

    # Parse the WAV bytes
    buf = io.BytesIO(resp.content)
    with wave.open(buf, "rb") as wf:
        n_channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sample_rate = wf.getframerate()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    # Convert raw PCM to numpy float32
    if sample_width == 2:
        dtype = np.int16
    elif sample_width == 4:
        dtype = np.int32
    else:
        dtype = np.uint8

    samples = np.frombuffer(raw, dtype=dtype).astype(np.float32)
    # Normalize to [-1, 1]
    max_val = float(np.iinfo(dtype).max)
    samples /= max_val

    if n_channels > 1:
        samples = samples.reshape(-1, n_channels)

    print(f"[voice] Received {n_frames} frames, {n_channels}ch, {sample_rate}Hz, {sample_width*8}bit")
    return samples, sample_rate


def play(samples: np.ndarray, sample_rate: int) -> None:
    """Play audio through the default output device and block until done."""
    duration = len(samples) / sample_rate
    print(f"[voice] Playing {duration:.1f}s of audio...")
    sd.play(samples, samplerate=sample_rate)
    sd.wait()
    print("[voice] Done.")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    import os

    p = argparse.ArgumentParser(description="Orpheus TTS voice test")
    p.add_argument("text", nargs="?", default="Hello! This is a test of the Orpheus text to speech system.",
                   help="Text to synthesize.")
    p.add_argument("--url", default=os.getenv("ORPHEUS_URL", "http://localhost:5005"),
                   help="Orpheus TTS server URL (or set ORPHEUS_URL env var).")
    p.add_argument("--voice", default="dan", help="Voice name (default: dan).")
    p.add_argument("--speed", type=float, default=1.0, help="Speed factor 0.5–1.5.")
    p.add_argument("--save", metavar="FILE", default=None,
                   help="Also save the WAV to a file.")
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    samples, sr = synthesize(
        args.text,
        base_url=args.url,
        voice=args.voice,
        speed=args.speed,
    )

    if args.save:
        import scipy.io.wavfile as wavfile
        # Convert back to int16 for saving
        int_samples = (samples * 32767).astype(np.int16)
        wavfile.write(args.save, sr, int_samples)
        print(f"[voice] Saved to {args.save}")

    play(samples, sr)


if __name__ == "__main__":
    main()
