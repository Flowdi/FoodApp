from functools import lru_cache
from typing import Any, Protocol

import httpx
from fastapi import HTTPException, status

from ..config import Settings, get_settings


class SpeechToText(Protocol):
    def transcribe(self, audio: bytes, filename: str, content_type: str) -> str: ...


class FasterWhisperSpeechToText:
    def __init__(self, model_name: str):
        self.model_name = model_name

    def transcribe(self, audio: bytes, filename: str, content_type: str) -> str:
        import tempfile
        from pathlib import Path

        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                {
                    "code": "stt_unavailable",
                    "message": "Lokale Spracherkennung ist nicht installiert",
                },
            ) from exc
        suffix = Path(filename).suffix or ".webm"
        with tempfile.NamedTemporaryFile(suffix=suffix) as handle:
            handle.write(audio)
            handle.flush()
            segments, _ = _whisper_model(WhisperModel, self.model_name).transcribe(
                handle.name, language="de", vad_filter=True
            )
            return " ".join(segment.text.strip() for segment in segments).strip()


@lru_cache(maxsize=2)
def _whisper_model(model_type: Any, model_name: str) -> Any:
    return model_type(model_name, compute_type="int8")


class OpenAISpeechToText:
    def __init__(self, settings: Settings):
        self.settings = settings

    def transcribe(self, audio: bytes, filename: str, content_type: str) -> str:
        response = httpx.post(
            f"{self.settings.stt_base_url.rstrip('/')}/audio/transcriptions",
            headers={"Authorization": f"Bearer {self.settings.stt_api_key}"},
            files={"file": (filename, audio, content_type)},
            data={"model": self.settings.stt_model, "language": "de"},
            timeout=30,
        )
        response.raise_for_status()
        return str(response.json()["text"]).strip()


def configured_speech(settings: Settings | None = None) -> SpeechToText | None:
    settings = settings or get_settings()
    if settings.stt_provider == "faster-whisper":
        return FasterWhisperSpeechToText(settings.stt_model)
    if settings.stt_provider == "openai":
        return OpenAISpeechToText(settings)
    return None
