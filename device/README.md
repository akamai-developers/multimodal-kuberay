## Live Commentary Client

Real-time video → VLM → TTS streaming commentary.  Captures webcam frames, sends them to a Qwen3-VL vision-language model via the Ray Serve pipeline, and plays synthesized speech narration through the speakers — providing continuous live commentary of what the camera sees.

```
┌──────────┐  JPEG frame   ┌────────────────────┐  WAV audio  ┌──────────┐
│  Webcam  │──────────────►│ /v1/audio/describe │────────────►│ Speakers │
│ (OpenCV) │   (base64)    │  VLM → TTS server  │  (httpx)    │ (sd/pyau)│
└──────────┘               └────────────────────┘             └──────────┘
```

Three threads run concurrently:

1. **Capture** — grabs frames from the webcam, picks one every *N* seconds
2. **Infer** — sends the frame to the server, receives WAV audio back
3. **Playback** — plays received audio clips through the speakers

---

### Install

Requires Python 3.10+.

```sh
cd device
pip install -e '.[all]'        # includes WebSocket support (recommended)
# — or, HTTP-only (no websocket-client) —
pip install -e .
```

> **System dependency:** `sounddevice` needs PortAudio.
> - macOS: `brew install portaudio`
> - Ubuntu/Debian: `sudo apt install libportaudio2`

---

### Quick start

1. Set the Ray Serve gateway endpoint (skip for `--offline` dry runs):

   ```sh
   export VISION_VOICE_URL="http://<gateway-ip>"
   export OPENAI_API_KEY="<your-bearer-token>"
   ```

2. Run:

   ```sh
   live-commentary                     # WebSocket mode (default, lower latency)
   live-commentary --mode http         # HTTP fallback (one request per frame)
   ```

   Or run directly without installing:

   ```sh
   python streaming.py
   ```

An OpenCV window labeled **LIVE COMMENTARY** shows the camera feed with a latency HUD overlay. Press **q** in the window to quit.

---

### Offline dry run

Verify camera access and speaker playback without a running backend:

```sh
live-commentary --offline
```

This skips all network calls and plays a short sine-wave test tone for each frame interval.

---

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--url` | `$VISION_VOICE_URL` | Gateway base URL |
| `--token` | `$OPENAI_API_KEY` | Bearer token for gateway auth |
| `--mode` | `ws` | Transport: `ws` (WebSocket streaming) or `http` |
| `--model` | `qwen3-vl-8b-instruct` | VLM model ID |
| `--voice` | `alloy` | TTS voice (`alloy`, `echo`, `fable`, `onyx`, `nova`, `shimmer`) |
| `--language` | `en` | TTS language code |
| `--max-tokens` | `50` | Max VLM response tokens |
| `--speed` | `1.1` | TTS speech speed multiplier |
| `--interval` | `5.0` | Seconds between commentary frames |
| `--camera` | `0` | Camera device index |
| `--jpeg-quality` | `70` | JPEG quality (1–100) |
| `--max-width` | `512` | Max frame width sent to VLM |
| `--headless` | off | Disable the OpenCV preview window |
| `--system-prompt` | — | Optional system prompt prepended to each VLM call |
| `--timeout` | `120` | HTTP/WebSocket request timeout (seconds) |
| `--offline` | off | Skip server calls, play test tones |
| `--log-level` | `INFO` | `DEBUG`, `INFO`, or `QUIET` |

---

### Examples

```sh
# Custom endpoint, faster commentary
live-commentary --url http://172.105.12.119 --interval 3 --voice echo --max-tokens 80

# Headless (no GUI) — e.g. for SSH sessions
live-commentary --headless --mode http --log-level DEBUG

# Different camera
live-commentary --camera 1 --interval 10
```
