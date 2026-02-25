"""
MagpieTTS Ray Serve Application

OpenAI-compatible /v1/audio/speech endpoint using
NVIDIA MagpieTTS Multilingual 357M.

Supports both NeMo main branch (MagpieTTSModel with do_tts) and
NeMo v2.6.2 stable (MagpieTTS_Model with manual infer_batch).

Speakers: John (0), Sofia (1), Aria (2), Jason (3), Leo (4)
Languages: en, es, de, fr, vi, it, zh
"""

import asyncio
import base64
import io
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

import httpx
import numpy as np
import torch
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel, Field
from ray import serve

logger = logging.getLogger("ray.serve")

app = FastAPI(title="MagpieTTS", version="1.0.0")

# Map OpenAI voice names to MagpieTTS speaker indices
VOICE_MAP = {
    "alloy": 1,    # Sofia
    "echo": 0,     # John
    "fable": 2,    # Aria
    "onyx": 3,     # Jason
    "nova": 4,     # Leo
    "shimmer": 1,  # Sofia (fallback)
    # Direct MagpieTTS speaker names
    "john": 0,
    "sofia": 1,
    "aria": 2,
    "jason": 3,
    "leo": 4,
}

SUPPORTED_LANGUAGES = {"en", "es", "de", "fr", "vi", "it", "zh"}

# Internal K8s service URL for the VLM (Qwen3-VL)
VLM_SERVICE_URL = os.getenv(
    "VLM_SERVICE_URL",
    "http://ray-serve-llm-serve-svc:8000",
)

# Map language codes to NeMo tokenizer names (ordered by preference)
LANGUAGE_TOKENIZER_MAP = {
    "en": ["english_phoneme", "english"],
    "de": ["german_phoneme", "german"],
    "es": ["spanish_phoneme", "spanish"],
    "fr": ["french_chartokenizer", "french"],
    "it": ["italian_phoneme", "italian"],
    "vi": ["vietnamese_phoneme", "vietnamese"],
    "zh": ["mandarin_phoneme", "mandarin", "chinese"],
}

# Regex: find the last sentence boundary (punctuation followed by whitespace)
_SENTENCE_BOUNDARY = re.compile(r'[.!?]\s')


class SpeechRequest(BaseModel):
    """OpenAI-compatible TTS request."""

    model: str = Field(default="magpie-tts", description="Model ID")
    input: str = Field(..., description="Text to synthesize", max_length=4096)
    voice: str = Field(
        default="alloy",
        description="Voice: alloy|echo|fable|onyx|nova|shimmer "
        "or john|sofia|aria|jason|leo",
    )
    response_format: str = Field(
        default="wav", description="Audio format: wav or pcm"
    )
    speed: float = Field(
        default=1.0, ge=0.25, le=4.0,
        description="Speech speed multiplier (1.0 = normal)",
    )
    language: Optional[str] = Field(
        default="en", description="Language: en|es|de|fr|vi|it|zh"
    )


class DescribeAndSpeakRequest(BaseModel):
    """Pipeline request: send messages to VLM, speak the response."""

    messages: List[Dict[str, Any]] = Field(
        ..., description="OpenAI chat messages (supports text + image_url)"
    )
    model: str = Field(
        default="qwen3-vl-8b-instruct",
        description="VLM model ID for chat completions",
    )
    voice: str = Field(
        default="alloy",
        description="TTS voice: alloy|echo|fable|onyx|nova|shimmer",
    )
    language: Optional[str] = Field(
        default="en", description="TTS language: en|es|de|fr|vi|it|zh"
    )
    response_format: str = Field(
        default="wav", description="Audio format: wav or pcm"
    )
    max_tokens: int = Field(
        default=512, ge=1, le=4096,
        description="Max tokens for VLM response",
    )
    speed: float = Field(
        default=1.0, ge=0.25, le=4.0,
        description="Speech speed multiplier (1.0 = normal)",
    )


@serve.deployment(
    ray_actor_options={"num_gpus": 1, "num_cpus": 4},
    autoscaling_config={
        "min_replicas": 2,
        "max_replicas": 2,
        "target_ongoing_requests": 4,
    },
    max_ongoing_requests=8,
)
@serve.ingress(app)
class MagpieTTSDeployment:
    """Ray Serve deployment wrapping NVIDIA MagpieTTS Multilingual 357M."""

    def __init__(self):
        # Support both NeMo main branch (MagpieTTSModel) and v2.6.2 (MagpieTTS_Model)
        try:
            from nemo.collections.tts.models import MagpieTTSModel
            model_cls = MagpieTTSModel
            logger.info("Using NeMo main branch MagpieTTSModel")
        except ImportError:
            from nemo.collections.tts.models import MagpieTTS_Model
            model_cls = MagpieTTS_Model
            logger.info("Using NeMo v2.6.2 MagpieTTS_Model")

        logger.info("Loading MagpieTTS Multilingual 357M...")
        self.model = model_cls.from_pretrained(
            "nvidia/magpie_tts_multilingual_357m"
        )
        self.model.eval()
        self.sample_rate = getattr(
            self.model, "output_sample_rate", 22050
        )
        self._has_do_tts = hasattr(self.model, "do_tts")

        if not self._has_do_tts:
            # Cache tokenizer info for manual inference path (v2.6.2)
            self._available_tokenizers = list(
                self.model.tokenizer.tokenizers.keys()
            )
            logger.info(
                "do_tts not available — using infer_batch. "
                "Tokenizers: %s", self._available_tokenizers
            )

        # HTTP client for calling the VLM service
        self._vlm_client = httpx.AsyncClient(
            base_url=VLM_SERVICE_URL,
            timeout=httpx.Timeout(120.0, connect=10.0),
        )

        logger.info(
            "MagpieTTS ready (sample_rate=%d, do_tts=%s, vlm=%s)",
            self.sample_rate, self._has_do_tts, VLM_SERVICE_URL,
        )

    # ------------------------------------------------------------------
    # Tokenizer helpers (used when do_tts is not available)
    # ------------------------------------------------------------------

    def _find_tokenizer(self, language: str) -> str:
        """Find the appropriate NeMo tokenizer for the given language."""
        if language in LANGUAGE_TOKENIZER_MAP:
            for candidate in LANGUAGE_TOKENIZER_MAP[language]:
                if candidate in self._available_tokenizers:
                    return candidate
        # Fallback to first available tokenizer
        return self._available_tokenizers[0]

    # ------------------------------------------------------------------
    # HTTP endpoints
    # ------------------------------------------------------------------

    @app.post("/v1/audio/speech")
    async def create_speech(self, request: SpeechRequest) -> Response:
        """Generate speech from text (OpenAI-compatible)."""
        speaker_idx = VOICE_MAP.get(request.voice.lower(), 1)
        language = (
            request.language
            if request.language in SUPPORTED_LANGUAGES
            else "en"
        )

        loop = asyncio.get_running_loop()
        audio, audio_len = await loop.run_in_executor(
            None, self._synthesize, request.input, language, speaker_idx
        )

        audio_np = audio.cpu().numpy().flatten()
        if audio_len is not None:
            audio_np = audio_np[: int(audio_len)]
        audio_np = self._apply_speed(audio_np, request.speed)

        if request.response_format == "pcm":
            pcm = (audio_np * 32767).astype(np.int16).tobytes()
            return Response(content=pcm, media_type="audio/pcm")

        # Default: WAV
        import soundfile as sf

        buf = io.BytesIO()
        sf.write(buf, audio_np, self.sample_rate, format="WAV")
        buf.seek(0)
        return Response(content=buf.read(), media_type="audio/wav")

    @app.post("/v1/audio/describe")
    async def describe_and_speak(self, request: DescribeAndSpeakRequest) -> Response:
        """Pipeline: send messages to VLM, then speak the response.

        Accepts the same messages format as OpenAI chat completions
        (text, image_url, etc.), forwards to the Qwen3-VL model,
        and returns the spoken audio of the VLM's response.
        """
        # Step 1: Call the VLM for a text response
        vlm_payload = {
            "model": request.model,
            "messages": request.messages,
            "max_tokens": request.max_tokens,
            "stream": False,
        }
        try:
            vlm_resp = await self._vlm_client.post(
                "/v1/chat/completions", json=vlm_payload
            )
            vlm_resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error("VLM request failed: %s %s", exc.response.status_code, exc.response.text)
            return Response(
                content=exc.response.text,
                status_code=exc.response.status_code,
                media_type="application/json",
            )
        except httpx.RequestError as exc:
            logger.error("VLM connection error: %s", exc)
            return Response(
                content='{"error": "Failed to reach VLM service"}',
                status_code=502,
                media_type="application/json",
            )

        vlm_data = vlm_resp.json()
        text = vlm_data["choices"][0]["message"]["content"]
        logger.info("VLM response (%d chars): %.100s...", len(text), text)

        # Step 2: Synthesize the VLM text to speech
        speaker_idx = VOICE_MAP.get(request.voice.lower(), 1)
        language = (
            request.language
            if request.language in SUPPORTED_LANGUAGES
            else "en"
        )

        loop = asyncio.get_running_loop()
        audio, audio_len = await loop.run_in_executor(
            None, self._synthesize, text, language, speaker_idx
        )

        audio_np = audio.cpu().numpy().flatten()
        if audio_len is not None:
            audio_np = audio_np[: int(audio_len)]
        audio_np = self._apply_speed(audio_np, request.speed)

        if request.response_format == "pcm":
            pcm = (audio_np * 32767).astype(np.int16).tobytes()
            return Response(content=pcm, media_type="audio/pcm")

        import soundfile as sf

        buf = io.BytesIO()
        sf.write(buf, audio_np, self.sample_rate, format="WAV")
        buf.seek(0)

        # HTTP headers must be latin-1 safe; strip non-ASCII chars
        safe_text = text[:200].encode("ascii", errors="replace").decode("ascii")
        return Response(
            content=buf.read(),
            media_type="audio/wav",
            headers={"X-VLM-Text": safe_text},
        )

    # ------------------------------------------------------------------
    # Audio encoding
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_speed(audio_np: np.ndarray, speed: float) -> np.ndarray:
        """Adjust playback speed via linear interpolation.

        speed > 1.0 → faster/shorter, speed < 1.0 → slower/longer.
        This is a simple resample that shifts pitch proportionally,
        which sounds natural for commentary at speeds up to ~1.5x.
        """
        if abs(speed - 1.0) < 0.01:
            return audio_np
        orig_len = len(audio_np)
        new_len = max(1, int(orig_len / speed))
        indices = np.linspace(0, orig_len - 1, new_len)
        return np.interp(indices, np.arange(orig_len), audio_np).astype(np.float32)

    def _to_wav_bytes(self, audio_np: np.ndarray) -> bytes:
        """Encode float32 audio array to WAV bytes."""
        import soundfile as sf

        buf = io.BytesIO()
        sf.write(buf, audio_np, self.sample_rate, format="WAV")
        return buf.getvalue()

    async def _synthesize_and_send(
        self, websocket: WebSocket, text: str, language: str, speaker_idx: int,
        speed: float = 1.0,
    ) -> None:
        """TTS a text chunk and send the audio over WebSocket."""
        loop = asyncio.get_running_loop()
        audio, audio_len = await loop.run_in_executor(
            None, self._synthesize, text, language, speaker_idx
        )
        audio_np = audio.cpu().numpy().flatten()
        if audio_len is not None:
            audio_np = audio_np[: int(audio_len)]
        audio_np = self._apply_speed(audio_np, speed)
        await websocket.send_bytes(self._to_wav_bytes(audio_np))

    # ------------------------------------------------------------------
    # WebSocket streaming endpoint
    # ------------------------------------------------------------------

    @app.websocket("/v1/audio/stream")
    async def stream_commentary(self, websocket: WebSocket):
        """Low-latency streaming: receive frames, stream audio commentary.

        Protocol
        --------
        Client → Server:
          text   : JSON config {"voice","language","model","max_tokens","prompt"}
          binary : JPEG frame bytes

        Server → Client:
          text   : JSON {"type":"text",  "content":"..."} — VLM sentence chunk
          text   : JSON {"type":"done"}                  — end of this frame
          text   : JSON {"type":"error", "detail":"..."}  — non-fatal error
          binary : WAV audio for the preceding text chunk
        """
        await websocket.accept()

        # Tunables (client can override via a text config message)
        model = "qwen3-vl-8b-instruct"
        voice = "alloy"
        language = "en"
        max_tokens = 80
        speed = 1.0
        prompt = (
            "You are a live commentator. Describe what is happening "
            "in this camera frame in 1 short, energetic sentence. "
            "Be concise — this will be spoken aloud."
        )

        logger.info("[ws-stream] Client connected")

        try:
            while True:
                message = await websocket.receive()

                if message.get("type") == "websocket.disconnect":
                    break

                # --- Config message (text JSON) ---
                if "text" in message:
                    try:
                        cfg = json.loads(message["text"])
                        model = cfg.get("model", model)
                        voice = cfg.get("voice", voice)
                        language = cfg.get("language", language)
                        max_tokens = cfg.get("max_tokens", max_tokens)
                        speed = cfg.get("speed", speed)
                        prompt = cfg.get("prompt", prompt)
                        logger.info(
                            "[ws-stream] Config: model=%s voice=%s", model, voice
                        )
                        await websocket.send_text(
                            json.dumps({"type": "config_ack"})
                        )
                    except json.JSONDecodeError:
                        await websocket.send_text(
                            json.dumps({"type": "error", "detail": "Invalid JSON"})
                        )
                    continue

                # --- JPEG frame (binary) ---
                if "bytes" not in message:
                    continue

                frame_bytes = message["bytes"]
                logger.info(
                    "[ws-stream] Received frame (%d bytes), calling VLM...",
                    len(frame_bytes),
                )
                b64 = base64.b64encode(frame_bytes).decode("ascii")
                data_uri = f"data:image/jpeg;base64,{b64}"

                speaker_idx = VOICE_MAP.get(voice.lower(), 1)
                lang = language if language in SUPPORTED_LANGUAGES else "en"

                vlm_messages = [
                    {"role": "system", "content": "/no_think"},
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": data_uri}},
                            {"type": "text", "text": prompt},
                        ],
                    },
                ]

                vlm_payload = {
                    "model": model,
                    "messages": vlm_messages,
                    "max_tokens": max_tokens,
                    "stream": True,
                }

                try:
                    accumulated = ""

                    async with self._vlm_client.stream(
                        "POST", "/v1/chat/completions", json=vlm_payload
                    ) as vlm_resp:
                        if vlm_resp.status_code != 200:
                            body = await vlm_resp.aread()
                            detail = f"VLM HTTP {vlm_resp.status_code}: {body.decode(errors='replace')[:300]}"
                            logger.error("[ws-stream] %s", detail)
                            await websocket.send_text(json.dumps({
                                "type": "error",
                                "detail": detail,
                            }))
                            continue

                        async for line in vlm_resp.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            chunk_str = line[6:].strip()
                            if chunk_str == "[DONE]":
                                break

                            try:
                                chunk = json.loads(chunk_str)
                            except json.JSONDecodeError:
                                continue

                            delta = (
                                chunk.get("choices", [{}])[0]
                                .get("delta", {})
                            )
                            content = delta.get("content", "")
                            if not content:
                                continue

                            accumulated += content

                            # Split at the *last* sentence boundary so we
                            # flush as many complete sentences as possible
                            # while keeping any trailing fragment.
                            matches = list(
                                _SENTENCE_BOUNDARY.finditer(accumulated)
                            )
                            if matches:
                                split_at = matches[-1].end()
                                sentence = accumulated[:split_at].strip()
                                accumulated = accumulated[split_at:]

                                await websocket.send_text(json.dumps({
                                    "type": "text", "content": sentence,
                                }))
                                await self._synthesize_and_send(
                                    websocket, sentence, lang, speaker_idx,
                                    speed=speed,
                                )

                    # Flush remaining text
                    remaining = accumulated.strip()
                    if remaining:
                        await websocket.send_text(json.dumps({
                            "type": "text", "content": remaining,
                        }))
                        await self._synthesize_and_send(
                            websocket, remaining, lang, speaker_idx,
                            speed=speed,
                        )

                    await websocket.send_text(json.dumps({"type": "done"}))

                except httpx.TimeoutException:
                    logger.error("[ws-stream] VLM timeout")
                    await websocket.send_text(json.dumps({
                        "type": "error", "detail": "VLM request timed out",
                    }))
                except httpx.RequestError as exc:
                    detail = f"VLM connection error: {type(exc).__name__}: {exc}"
                    logger.error("[ws-stream] %s", detail)
                    await websocket.send_text(json.dumps({
                        "type": "error", "detail": detail,
                    }))
                except Exception as exc:
                    detail = f"Frame processing error: {type(exc).__name__}: {exc}"
                    logger.error("[ws-stream] %s", detail, exc_info=True)
                    await websocket.send_text(json.dumps({
                        "type": "error", "detail": detail,
                    }))

        except WebSocketDisconnect:
            logger.info("[ws-stream] Client disconnected")
        except Exception as exc:
            logger.error("[ws-stream] Unexpected error: %s", exc)

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def _synthesize(self, text: str, language: str, speaker_idx: int):
        """Run TTS inference. Delegates to do_tts when available,
        otherwise falls back to manual tokenize → infer_batch."""
        if self._has_do_tts:
            return self.model.do_tts(
                text,
                language=language,
                apply_TN=True,
                speaker_index=speaker_idx,
            )

        # ---- Manual inference path (NeMo v2.6.2) ----
        tokenizer_name = self._find_tokenizer(language)
        tokens = self.model.tokenizer.encode(
            text=text, tokenizer_name=tokenizer_name
        )
        tokens = tokens + [self.model.eos_id]

        text_tensor = torch.tensor(
            [tokens], device=self.model.device, dtype=torch.long
        )
        text_lens = torch.tensor(
            [len(tokens)], device=self.model.device, dtype=torch.long
        )

        batch = {
            "text": text_tensor,
            "text_lens": text_lens,
            "speaker_indices": speaker_idx,
        }

        output = self.model.infer_batch(
            batch,
            use_cfg=True,
            use_local_transformer_for_inference=True,
        )

        return output.predicted_audio, output.predicted_audio_lens

    @app.get("/v1/audio/models")
    async def list_models(self):
        """List available TTS models."""
        return {
            "object": "list",
            "data": [
                {
                    "id": "magpie-tts",
                    "object": "model",
                    "owned_by": "nvidia",
                    "type": "tts",
                },
                {
                    "id": "magpie-tts-stream",
                    "object": "model",
                    "owned_by": "nvidia",
                    "type": "tts-stream",
                    "description": "WebSocket streaming via /v1/audio/stream",
                },
            ],
        }

    @app.get("/health")
    async def health(self):
        return {"status": "ok"}


deployment = MagpieTTSDeployment.bind()
