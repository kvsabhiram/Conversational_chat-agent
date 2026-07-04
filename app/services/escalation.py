"""Phase 3: Escalation and fallback logic.

Determines when the bot should hand off to a human agent.
"""

from app.models.schemas import IntentResult
from app.utils.logger import get_logger

logger = get_logger("escalation")

# Intents that should always escalate
ALWAYS_ESCALATE = {
    "medical": ["emergency"],
    "banking": ["transaction_dispute"],
}

# Confidence threshold — below this, escalate
CONFIDENCE_THRESHOLD = 0.4

# Max consecutive low-confidence turns before escalating
MAX_LOW_CONFIDENCE_TURNS = 3


def should_escalate(
    intent: IntentResult | None = None,
    error: Exception | None = None,
    low_confidence_count: int = 0,
) -> bool:
    """Determine if the conversation should be escalated to a human.

    Escalates when:
    1. Critical intents (e.g., medical emergency, fraud report)
    2. LLM error / service down
    3. Confidence too low for too many turns
    4. User explicitly requests a human
    """

    # LLM is down — must escalate
    if error is not None:
        logger.info("Escalating: LLM error")
        return True

    if intent:
        # Critical intent — always escalate
        sector_escalate = ALWAYS_ESCALATE.get(intent.sector, [])
        if intent.intent in sector_escalate:
            logger.info(f"Escalating: critical intent {intent.intent}")
            return True

        # Low confidence
        if intent.confidence < CONFIDENCE_THRESHOLD:
            if low_confidence_count >= MAX_LOW_CONFIDENCE_TURNS:
                logger.info(f"Escalating: {low_confidence_count} low-confidence turns")
                return True

    return False


def get_escalation_message(sector: str, reason: str = "") -> str:
    """Get a human-friendly escalation message."""

    messages = {
        "medical": "For your safety, I'm connecting you with our medical helpdesk. Please call our emergency line at 108 if this is urgent.",
        "banking": "I'm transferring you to a senior banking specialist who can help resolve this. Please stay on the line.",
        "default": "Let me connect you with a human agent who can better assist you. Someone will be with you shortly.",
    }

    return messages.get(sector, messages["default"])
