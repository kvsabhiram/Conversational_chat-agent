from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime

BUILT_IN_SECTORS = {"retail", "education", "medical", "real_estate", "banking", "tourism"}


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: Optional[str] = None
    sector: str = Field(default="retail")
    tenant_id: Optional[str] = None
    src_lang: str = Field(
        default="auto",
        description=(
            "Optional hint about the message's language/script (e.g. 'Hindi', "
            "'Hinglish'). Not used to call a translation service — the LLM reads "
            "the message directly; this only nudges it when the script is ambiguous."
        ),
    )
    lang: str = Field(
        default="ENGLISH",
        description=(
            "Language the reply should be written in, as a plain name (e.g. "
            "'Hindi', 'French', 'Japanese') — passed straight into the LLM prompt, "
            "not looked up against a fixed list. See prompt_builder.language_instruction()."
        ),
    )
    stream: bool = Field(
        default=False,
        description="If true, POST /api/chat returns text/event-stream instead of JSON.",
    )

    @field_validator("sector")
    @classmethod
    def _validate_sector(cls, v: str) -> str:
        if v in BUILT_IN_SECTORS or v.startswith("custom_"):
            return v
        raise ValueError(
            f"Invalid sector '{v}'. Must be one of {sorted(BUILT_IN_SECTORS)} or a 'custom_<id>' persona."
        )


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    intent: Optional[str] = None
    confidence: Optional[float] = None
    sources: Optional[list] = None
    escalated: bool = False


class HealthResponse(BaseModel):
    status: str
    llm_status: str
    timestamp: datetime


class AgentConfig(BaseModel):
    sector: str
    name: str
    system_prompt: str
    intents: list[dict] = []
    guardrail_rules: list[str] = []
    tenant_id: Optional[str] = None


class DocumentUpload(BaseModel):
    sector: str
    filename: str
    content: str
    metadata: dict = {}


class IntentResult(BaseModel):
    intent: str
    confidence: float
    sector: str
    params: dict = {}


class SessionData(BaseModel):
    session_id: str
    sector: str
    tenant_id: Optional[str] = None
    history: list[dict] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ConversationLog(BaseModel):
    session_id: str
    sector: str
    user_message: str
    bot_reply: str
    intent: Optional[str] = None
    confidence: Optional[float] = None
    latency_ms: float
    tokens_used: int = 0
    rag_chunks: int = 0
    escalated: bool = False
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class AnalyticsSummary(BaseModel):
    total_conversations: int
    total_messages: int
    avg_latency_ms: float
    top_intents: list[dict]
    escalation_rate: float
    satisfaction_score: Optional[float] = None
    by_sector: dict = {}
