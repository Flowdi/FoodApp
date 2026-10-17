from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from .schemas import MovementResult

VoiceIntent = Literal[
    "add_to_stock",
    "consume",
    "discard",
    "add_to_shopping",
    "remove_from_shopping",
    "check_shopping",
    "query_stock",
    "unknown",
]


class VoiceProductChoice(BaseModel):
    id: str
    name: str


class VoiceAction(BaseModel):
    intent: VoiceIntent
    product_id: str | None = None
    product_name: str = Field(min_length=1, max_length=180)
    quantity: Decimal | None = Field(default=None, gt=0)
    unit: str | None = None
    confidence: float = Field(ge=0, le=1)
    choices: list[VoiceProductChoice] = []
    expected_versions: dict[str, int] = {}
    requires_confirmation: bool = True


class VoiceInterpretRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class VoiceInterpretResponse(BaseModel):
    transcript: str
    actions: list[VoiceAction]
    parser: Literal["rules", "llm"]


class LLMActions(BaseModel):
    actions: list[VoiceAction]


class VoiceExecuteRequest(BaseModel):
    action: VoiceAction
    idempotency_key: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")
    location_id: str | None = None


class VoiceExecuteResponse(BaseModel):
    message: str
    result_type: Literal["stock", "shopping", "query"]
    movements: list[MovementResult] = Field(default_factory=list)


class VoiceTranscription(BaseModel):
    text: str


class VoicePreferences(BaseModel):
    auto_confirm_shopping: bool = False
    speech_output: bool = False
    start_listening_on_launch: bool | None = None
