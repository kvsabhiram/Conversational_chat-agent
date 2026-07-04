"""Translation client for the IndicTrans2 gateway.

Best-effort: if the gateway is unreachable or returns an error, the
original text is returned and the pipeline continues.
"""

import time
import httpx
from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger("translator")
settings = get_settings()


async def _translate(text: str, src_lang: str, tgt_lang: str) -> str:
    if not text.strip():
        return text

    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{settings.translation_url.rstrip('/')}/translate",
                json={"text": text, "src_lang": src_lang, "tgt_lang": tgt_lang},
            )
            resp.raise_for_status()
            output = resp.json().get("output", text)
    except Exception as e:
        latency = round((time.time() - start) * 1000, 2)
        logger.warning(
            f"translation failed src={src_lang} tgt={tgt_lang} after {latency}ms: {e}",
            extra={
                "src_lang": src_lang,
                "tgt_lang": tgt_lang,
                "input": text,
                "input_len": len(text),
                "latency_ms": latency,
                "error": str(e),
            },
        )
        return text

    latency = round((time.time() - start) * 1000, 2)
    logger.info(
        f"translate src={src_lang} tgt={tgt_lang} latency={latency}ms "
        f"in={text[:80]} out={output[:80]}",
        extra={
            "src_lang": src_lang,
            "tgt_lang": tgt_lang,
            "input": text,
            "input_len": len(text),
            "output": output,
            "output_len": len(output),
            "latency_ms": latency,
        },
    )
    return output


async def to_english(text: str, src_lang: str = "auto") -> str:
    """Translate user input into English. Returns original text on failure."""
    if src_lang.upper() == "ENGLISH":
        return text
    return await _translate(text, src_lang, "ENGLISH")


async def from_english(text: str, tgt_lang: str) -> str:
    """Translate bot reply into the user's language. Returns original on failure."""
    if tgt_lang.upper() == "ENGLISH":
        return text
    return await _translate(text, "ENGLISH", tgt_lang)