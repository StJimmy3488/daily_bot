"""Local speech-to-text with faster-whisper (CPU, int8)."""

import asyncio
import logging
from typing import BinaryIO

log = logging.getLogger(__name__)


class Transcriber:
    def __init__(self, model_size: str):
        self.model_size = model_size
        self._model = None
        # One transcription at a time: it's CPU-bound and the VPS is small.
        self._lock = asyncio.Lock()

    def _ensure_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel  # heavy import, only when needed

            log.info("Loading whisper model %r", self.model_size)
            self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
        return self._model

    def _transcribe(self, audio: BinaryIO) -> str:
        segments, info = self._ensure_model().transcribe(audio, vad_filter=True)
        text = " ".join(segment.text.strip() for segment in segments).strip()
        log.info("Transcribed %.1fs of %s audio", info.duration, info.language)
        return text

    async def warm_up(self) -> None:
        """Load (and on first run download) the model in the background at startup."""
        try:
            async with self._lock:
                await asyncio.to_thread(self._ensure_model)
        except Exception:
            log.exception("Could not load whisper model")

    async def transcribe(self, audio: BinaryIO) -> str:
        async with self._lock:
            return await asyncio.to_thread(self._transcribe, audio)
