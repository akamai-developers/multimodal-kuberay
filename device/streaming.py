#!/usr/bin/env python3
"""
Live Video → VLM → TTS streaming commentary client.

Captures webcam frames, sends them to the Qwen3-VL vision-language model
via the /v1/audio/describe pipeline endpoint, and plays the synthesized
speech commentary through the speakers — providing continuous live
narration of what the camera sees.

Architecture:
    ┌──────────┐  JPEG frame   ┌───────────────────┐  WAV audio  ┌──────────┐
    │  Webcam  │──────────────►│  /v1/audio/describe │────────────►│ Speakers │
    │ (OpenCV) │   (base64)    │  VLM → TTS server  │  (httpx)    │ (sd/pyau)│
    └──────────┘               └───────────────────┘              └──────────┘

    Three threads run concurrently:
      1. Capture  — grabs frames from the webcam, picks one every N seconds
      2. Infer    — sends the frame to the server, receives WAV audio back
      3. Playback — plays received audio clips through the speakers

Usage:
    # Basic (uses gateway IP from kubectl):
    python streaming.py

    # WebSocket streaming mode (default — lower latency):
    python streaming.py --mode ws

    # HTTP fallback mode (one request per frame):
    python streaming.py --mode http

    # Specify endpoint manually:
    python streaming.py --url http://172.105.12.119 --token sk-your-key

    # Adjust commentary interval and voice:
    python streaming.py --interval 5 --voice echo --max-tokens 80

    # Offline dry-run (no server needed, plays a test tone):
    python streaming.py --offline

Requires:
    pip install opencv-python httpx sounddevice numpy websocket-client
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import queue
import signal
import struct
import sys
import threading
import time
import wave
from typing import Optional, Sequence

import cv2
import numpy as np

try:
    import httpx
except ImportError:
    sys.exit("httpx is required.  pip install httpx")

try:
    import sounddevice as sd
except ImportError:
    sys.exit("sounddevice is required.  pip install sounddevice")

try:
    import websocket as _ws_mod  # websocket-client
    _HAS_WEBSOCKET = True
except ImportError:
    _HAS_WEBSOCKET = False


# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────


class Config:
    """Runtime configuration populated from CLI args and env vars."""

    def __init__(self, args: argparse.Namespace):
        self.base_url: str = args.url
        self.token: str = args.token
        self.model: str = args.model
        self.voice: str = args.voice
        self.language: str = args.language
        self.max_tokens: int = args.max_tokens
        self.interval: float = args.interval
        self.camera: int = args.camera
        self.preview: bool = not args.headless
        self.offline: bool = args.offline
        self.jpeg_quality: int = args.jpeg_quality
        self.max_width: int = args.max_width
        self.system_prompt: str = args.system_prompt
        self.timeout: float = args.timeout
        self.log_level: str = args.log_level
        self.mode: str = args.mode  # "ws" or "http"


# ─────────────────────────────────────────────────────────────────────────────
# Logging helpers
# ─────────────────────────────────────────────────────────────────────────────

_QUIET = False


def log(tag: str, msg: str) -> None:
    if not _QUIET:
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] [{tag}] {msg}", flush=True)


def log_error(tag: str, msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] [{tag}] ERROR: {msg}", file=sys.stderr, flush=True)


# ─────────────────────────────────────────────────────────────────────────────
# Audio helpers
# ─────────────────────────────────────────────────────────────────────────────


def wav_bytes_to_numpy(data: bytes) -> tuple[np.ndarray, int]:
    """Parse WAV bytes into (float32 samples, sample_rate)."""
    buf = io.BytesIO(data)
    with wave.open(buf, "rb") as wf:
        n_channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sample_rate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())

    if sample_width == 2:
        dtype = np.int16
    elif sample_width == 4:
        dtype = np.int32
    else:
        dtype = np.uint8

    samples = np.frombuffer(raw, dtype=dtype).astype(np.float32)
    samples /= float(np.iinfo(dtype).max)

    if n_channels > 1:
        samples = samples.reshape(-1, n_channels)

    return samples, sample_rate


def generate_test_tone(duration: float = 1.5, freq: float = 440.0,
                       sample_rate: int = 22050) -> tuple[np.ndarray, int]:
    """Generate a short sine-wave tone for offline testing."""
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    samples = (0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return samples, sample_rate


# ─────────────────────────────────────────────────────────────────────────────
# Frame encoding
# ─────────────────────────────────────────────────────────────────────────────


def encode_frame(frame: np.ndarray, max_width: int = 512,
                 jpeg_quality: int = 70) -> str:
    """Resize + JPEG-encode a BGR frame and return a base64 data URI."""
    h, w = frame.shape[:2]
    if w > max_width:
        scale = max_width / w
        frame = cv2.resize(frame, (max_width, int(h * scale)))

    ok, jpg = cv2.imencode(".jpg", frame,
                           [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
    if not ok:
        raise RuntimeError("JPEG encoding failed")

    b64 = base64.b64encode(jpg.tobytes()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def encode_frame_bytes(frame: np.ndarray, max_width: int = 512,
                       jpeg_quality: int = 70) -> bytes:
    """Resize + JPEG-encode a BGR frame and return raw JPEG bytes."""
    h, w = frame.shape[:2]
    if w > max_width:
        scale = max_width / w
        frame = cv2.resize(frame, (max_width, int(h * scale)))

    ok, jpg = cv2.imencode(".jpg", frame,
                           [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return jpg.tobytes()


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline threads
# ─────────────────────────────────────────────────────────────────────────────

# Sentinel to signal threads to shut down
_STOP = object()


def capture_thread(
    cfg: Config,
    frame_queue: queue.Queue,
    latest_frame: list,
    stop_event: threading.Event,
) -> None:
    """Grab webcam frames, push one every `cfg.interval` seconds."""
    log("capture", f"Opening camera {cfg.camera}")
    cap = cv2.VideoCapture(cfg.camera)
    if not cap.isOpened():
        log_error("capture", f"Cannot open camera {cfg.camera}")
        stop_event.set()
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    last_push = 0.0
    frame_count = 0

    try:
        while not stop_event.is_set():
            ok, frame = cap.read()
            if not ok:
                log_error("capture", "Frame read failed, retrying...")
                time.sleep(0.1)
                continue

            frame_count += 1

            # Always update latest frame for preview
            latest_frame[0] = frame

            # Push a frame for inference every `interval` seconds
            now = time.monotonic()
            if now - last_push >= cfg.interval:
                # Non-blocking put — drop frame if queue is full
                try:
                    frame_queue.put_nowait(frame.copy())
                    last_push = now
                    log("capture", f"Frame #{frame_count} queued for inference")
                except queue.Full:
                    log("capture", "Inference queue full, skipping frame")

            # Small sleep to avoid busy-loop (targeting ~30 fps for preview)
            time.sleep(0.03)
    finally:
        cap.release()
        log("capture", "Camera released")


def infer_thread(
    cfg: Config,
    frame_queue: queue.Queue,
    audio_queue: queue.Queue,
    stop_event: threading.Event,
) -> None:
    """Take frames from the queue, call /v1/audio/describe, push audio."""
    headers = {"Content-Type": "application/json"}
    if cfg.token:
        headers["Authorization"] = f"Bearer {cfg.token}"

    url = f"{cfg.base_url.rstrip('/')}/v1/audio/describe"
    log("infer", f"Endpoint: {url}")

    client = httpx.Client(timeout=httpx.Timeout(cfg.timeout, connect=10.0))

    try:
        while not stop_event.is_set():
            try:
                frame = frame_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if frame is _STOP:
                break

            if cfg.offline:
                # Offline mode: skip server call, generate test tone
                log("infer", "[offline] Generating test tone")
                samples, sr = generate_test_tone()
                audio_queue.put((samples, sr, "(offline test tone)"))
                continue

            data_uri = encode_frame(frame, cfg.max_width, cfg.jpeg_quality)

            messages = []
            if cfg.system_prompt:
                messages.append({"role": "system", "content": cfg.system_prompt})

            messages.append({
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_uri}},
                    {"type": "text", "text": (
                        "You are a live sports-style commentator. "
                        "Describe what is happening in this camera frame "
                        "in 1-2 short, energetic sentences. Be concise "
                        "and engaging — this will be spoken aloud."
                    )},
                ],
            })

            payload = {
                "model": cfg.model,
                "messages": messages,
                "voice": cfg.voice,
                "language": cfg.language,
                "max_tokens": cfg.max_tokens,
                "response_format": "wav",
            }

            t0 = time.monotonic()
            try:
                resp = client.post(url, json=payload)
                elapsed = time.monotonic() - t0

                if resp.status_code != 200:
                    log_error("infer", f"HTTP {resp.status_code}: {resp.text[:200]}")
                    continue

                # Extract VLM text from header if available
                vlm_text = resp.headers.get("x-vlm-text", "")

                samples, sr = wav_bytes_to_numpy(resp.content)
                duration = len(samples) / sr
                log("infer",
                    f"Got {duration:.1f}s audio in {elapsed:.1f}s"
                    f" | VLM: {vlm_text[:80]}{'...' if len(vlm_text) > 80 else ''}")

                audio_queue.put((samples, sr, vlm_text))

            except httpx.TimeoutException:
                log_error("infer", f"Request timed out after {cfg.timeout}s")
            except httpx.RequestError as exc:
                log_error("infer", f"Connection error: {exc}")
            except Exception as exc:
                log_error("infer", f"Unexpected error: {exc}")

    finally:
        client.close()
        log("infer", "Client closed")


def playback_thread(
    audio_queue: queue.Queue,
    stop_event: threading.Event,
) -> None:
    """Play audio clips as they arrive."""
    log("playback", "Ready")

    while not stop_event.is_set():
        try:
            item = audio_queue.get(timeout=1.0)
        except queue.Empty:
            continue

        if item is _STOP:
            break

        samples, sr, text = item
        duration = len(samples) / sr
        log("playback", f"Playing {duration:.1f}s clip...")

        try:
            sd.play(samples, samplerate=sr)
            sd.wait()
        except Exception as exc:
            log_error("playback", f"Playback error: {exc}")

    log("playback", "Stopped")


# ─────────────────────────────────────────────────────────────────────────────
# WebSocket inference thread (low-latency streaming)
# ─────────────────────────────────────────────────────────────────────────────


def ws_infer_thread(
    cfg: Config,
    frame_queue: queue.Queue,
    audio_queue: queue.Queue,
    stop_event: threading.Event,
) -> None:
    """WebSocket mode: persistent connection, sentence-level audio chunks."""
    if not _HAS_WEBSOCKET:
        log_error("ws", "websocket-client not installed. pip install websocket-client")
        stop_event.set()
        return

    ws_url = cfg.base_url.replace("http://", "ws://").replace("https://", "wss://")
    ws_url = f"{ws_url.rstrip('/')}/v1/audio/stream"
    log("ws", f"Endpoint: {ws_url}")

    headers = []
    if cfg.token:
        headers.append(f"Authorization: Bearer {cfg.token}")

    config_msg = json.dumps({
        "model": cfg.model,
        "voice": cfg.voice,
        "language": cfg.language,
        "max_tokens": cfg.max_tokens,
    })

    while not stop_event.is_set():
        ws = None
        try:
            log("ws", "Connecting...")
            ws = _ws_mod.WebSocket()
            ws.settimeout(cfg.timeout)
            ws.connect(ws_url, header=headers)
            log("ws", "Connected")

            # Send initial config
            ws.send(config_msg)
            ack_data = ws.recv()
            log("ws", f"Config ack: {ack_data}")

            # Main loop: send frames, receive audio chunks
            while not stop_event.is_set():
                try:
                    frame = frame_queue.get(timeout=1.0)
                except queue.Empty:
                    continue

                if frame is _STOP:
                    return

                if cfg.offline:
                    log("ws", "[offline] Generating test tone")
                    samples, sr = generate_test_tone()
                    audio_queue.put((samples, sr, "(offline)"))
                    continue

                # Send JPEG frame as binary
                jpeg_bytes = encode_frame_bytes(
                    frame, cfg.max_width, cfg.jpeg_quality
                )
                t0 = time.monotonic()
                ws.send(jpeg_bytes, opcode=_ws_mod.ABNF.OPCODE_BINARY)

                # Receive sentence-level audio chunks until "done"
                vlm_text_parts = []
                chunk_count = 0
                while True:
                    opcode, data = ws.recv_data()

                    if opcode == _ws_mod.ABNF.OPCODE_TEXT:
                        msg = json.loads(data)
                        msg_type = msg.get("type", "")

                        if msg_type == "done":
                            elapsed = time.monotonic() - t0
                            full_text = " ".join(vlm_text_parts)
                            log("ws",
                                f"{chunk_count} audio chunks in {elapsed:.1f}s"
                                f" | {full_text[:80]}")
                            break

                        elif msg_type == "text":
                            vlm_text_parts.append(msg.get("content", ""))

                        elif msg_type == "error":
                            log_error("ws", msg.get("detail", "unknown error"))
                            break

                    elif opcode == _ws_mod.ABNF.OPCODE_BINARY:
                        # WAV audio chunk — queue for immediate playback
                        chunk_count += 1
                        try:
                            samples, sr = wav_bytes_to_numpy(data)
                            audio_queue.put((samples, sr, ""))
                        except Exception as exc:
                            log_error("ws", f"Bad audio chunk: {exc}")

        except _ws_mod.WebSocketException as exc:
            log_error("ws", f"WebSocket error: {exc}")
        except (ConnectionError, OSError) as exc:
            log_error("ws", f"Connection lost: {exc}")
        except Exception as exc:
            log_error("ws", f"Unexpected error: {exc}")
        finally:
            if ws:
                try:
                    ws.close()
                except Exception:
                    pass

        if not stop_event.is_set():
            log("ws", "Reconnecting in 3s...")
            time.sleep(3)


# ─────────────────────────────────────────────────────────────────────────────
# Preview window (runs on main thread)
# ─────────────────────────────────────────────────────────────────────────────


def show_preview(latest_frame: list, stop_event: threading.Event,
                 preview_width: int = 960) -> None:
    """Display the webcam feed with an overlay. Runs on the main thread."""
    WINDOW = "Live Commentary"
    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)

    while not stop_event.is_set():
        frame = latest_frame[0]
        if frame is None:
            time.sleep(0.05)
            continue

        h, w = frame.shape[:2]
        if w > preview_width:
            scale = preview_width / w
            display = cv2.resize(frame, (preview_width, int(h * scale)))
        else:
            display = frame.copy()

        # Overlay status text
        cv2.putText(display, "LIVE COMMENTARY", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        cv2.putText(display, "Press 'q' to quit", (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

        cv2.imshow(WINDOW, display)

        key = cv2.waitKey(33) & 0xFF  # ~30 fps
        if key == ord("q"):
            log("preview", "Quit requested")
            stop_event.set()
            break

    cv2.destroyAllWindows()


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Live video → VLM → TTS streaming commentary",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Usage:")[0],
    )

    # Connection
    p.add_argument(
        "--url",
        default=os.getenv("VISION_VOICE_URL", "http://172.105.12.119"),
        help="Gateway base URL (default: $VISION_VOICE_URL or gateway IP)",
    )
    p.add_argument(
        "--token",
        default=os.getenv("OPENAI_API_KEY", ""),
        help="Bearer token for gateway auth (default: $OPENAI_API_KEY)",
    )

    # Model
    p.add_argument("--model", default="qwen3-vl-8b-instruct",
                   help="VLM model ID (default: qwen3-vl-8b-instruct)")
    p.add_argument("--voice", default="alloy",
                   choices=["alloy", "echo", "fable", "onyx", "nova", "shimmer"],
                   help="TTS voice (default: alloy / Sofia)")
    p.add_argument("--language", default="en",
                   help="TTS language code (default: en)")
    p.add_argument("--max-tokens", type=int, default=80,
                   help="Max tokens for VLM response (default: 80)")

    # Capture
    p.add_argument("--camera", type=int, default=0,
                   help="Camera index (default: 0)")
    p.add_argument("--interval", type=float, default=5.0,
                   help="Seconds between commentary frames (default: 5.0)")
    p.add_argument("--jpeg-quality", type=int, default=70,
                   help="JPEG quality 1-100 (default: 70)")
    p.add_argument("--max-width", type=int, default=512,
                   help="Max frame width sent to VLM (default: 512px)")

    # Display
    p.add_argument("--headless", action="store_true",
                   help="Disable the OpenCV preview window")

    # Advanced
    p.add_argument("--system-prompt", default="",
                   help="Optional system prompt prepended to each VLM call")
    p.add_argument("--timeout", type=float, default=120.0,
                   help="HTTP request timeout in seconds (default: 120)")
    p.add_argument("--offline", action="store_true",
                   help="Offline mode — skip server, play test tones")
    p.add_argument("--mode", default="ws", choices=["ws", "http"],
                   help="Transport mode: ws (WebSocket streaming, lower "
                        "latency) or http (one request per frame) "
                        "(default: ws)")
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "QUIET"],
                   help="Log verbosity (default: INFO)")

    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    cfg = Config(args)

    global _QUIET
    _QUIET = cfg.log_level == "QUIET"

    log("main", "=" * 60)
    log("main", "  Live Commentary — Video → VLM → TTS")
    log("main", "=" * 60)
    log("main", f"  Endpoint : {cfg.base_url}")
    log("main", f"  Mode     : {cfg.mode}")
    log("main", f"  Model    : {cfg.model}")
    log("main", f"  Voice    : {cfg.voice} ({cfg.language})")
    log("main", f"  Interval : {cfg.interval}s")
    log("main", f"  Camera   : {cfg.camera}")
    log("main", f"  Offline  : {cfg.offline}")
    log("main", "=" * 60)

    # Shared state
    stop_event = threading.Event()
    frame_queue: queue.Queue = queue.Queue(maxsize=2)   # pending inference
    audio_queue: queue.Queue = queue.Queue(maxsize=5)   # pending playback
    latest_frame: list = [None]  # mutable container for preview

    # Graceful shutdown on Ctrl+C
    def on_signal(signum, _frame):
        log("main", "Shutting down...")
        stop_event.set()

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    # Start worker threads
    threads = []

    t_cap = threading.Thread(target=capture_thread, name="capture",
                             args=(cfg, frame_queue, latest_frame, stop_event),
                             daemon=True)
    t_cap.start()
    threads.append(t_cap)

    # Choose inference thread based on mode
    infer_fn = ws_infer_thread if cfg.mode == "ws" else infer_thread
    if cfg.mode == "ws" and not _HAS_WEBSOCKET:
        log("main", "websocket-client not installed, falling back to HTTP mode")
        infer_fn = infer_thread

    t_inf = threading.Thread(target=infer_fn, name="infer",
                             args=(cfg, frame_queue, audio_queue, stop_event),
                             daemon=True)
    t_inf.start()
    threads.append(t_inf)

    t_play = threading.Thread(target=playback_thread, name="playback",
                              args=(audio_queue, stop_event),
                              daemon=True)
    t_play.start()
    threads.append(t_play)

    # Run preview on the main thread (OpenCV requires it on macOS)
    if cfg.preview:
        show_preview(latest_frame, stop_event)
    else:
        # Headless: just wait for stop signal
        log("main", "Running headless. Press Ctrl+C to stop.")
        try:
            while not stop_event.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            stop_event.set()

    # Clean shutdown
    stop_event.set()
    frame_queue.put(_STOP)
    audio_queue.put(_STOP)

    for t in threads:
        t.join(timeout=5.0)

    log("main", "Done.")


if __name__ == "__main__":
    main()
