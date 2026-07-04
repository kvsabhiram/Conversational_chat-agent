import uuid
import re


def generate_session_id() -> str:
    return str(uuid.uuid4())


def sanitize_input(text: str) -> str:
    """Basic input cleaning."""
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    return text[:4000]


def truncate_history(history: list[dict], max_turns: int = 20) -> list[dict]:
    """Keep only the last N turns to fit context window."""
    if len(history) > max_turns * 2:
        return history[-(max_turns * 2):]
    return history
