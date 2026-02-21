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
import io
import logging
import os
from typing import Any, Dict, List, Optional

import httpx
import numpy as np
import torch
from fastapi import FastAPI
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
        description="Speed (reserved, not yet supported)",
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


@serve.deployment(
    ray_actor_options={"num_gpus": 1, "num_cpus": 4},
    autoscaling_config={
        "min_replicas": 1,
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

        if request.response_format == "pcm":
            pcm = (audio_np * 32767).astype(np.int16).tobytes()
            return Response(content=pcm, media_type="audio/pcm")

        import soundfile as sf

        buf = io.BytesIO()
        sf.write(buf, audio_np, self.sample_rate, format="WAV")
        buf.seek(0)

        return Response(
            content=buf.read(),
            media_type="audio/wav",
            headers={"X-VLM-Text": text[:200]},  # Include VLM text in header
        )

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
                }
            ],
        }

    @app.get("/health")
    async def health(self):
        return {"status": "ok"}


deployment = MagpieTTSDeployment.bind()
