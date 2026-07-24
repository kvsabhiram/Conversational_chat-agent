import json
import httpx
import time
from app.config import get_settings
from app.utils import metrics
from app.utils.logger import get_logger

logger = get_logger("llm")


class LLMClient:
    """HTTP client for llama.cpp server running on localhost:8080"""

    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.llama_server_url

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.7,
        stop: list[str] | None = None,
    ) -> dict:
        """Send completion request to llama.cpp server.

        Returns dict with: text, tokens_used, latency_ms
        """
        start = time.time()

        payload = {
            "prompt": self._format_prompt(system_prompt, prompt),
            "n_predict": max_tokens,
            "temperature": temperature,
            "stop": stop or ["</s>", "<|im_end|>", "<end_of_turn>"],
            "stream": False,
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(f"{self.base_url}/completion", json=payload)
                response.raise_for_status()
                data = response.json()
        except Exception as e:
            latency = round((time.time() - start) * 1000, 2)
            metrics.llm_errors_total.labels(endpoint="/completion").inc()
            logger.error(
                f"LLM /completion failed after {latency}ms: {e}",
                extra={"endpoint": "/completion", "latency_ms": latency, "error": str(e)},
            )
            raise

        latency = round((time.time() - start) * 1000, 2)
        metrics.llm_latency_seconds.labels(endpoint="/completion").observe(latency / 1000)
        text = data.get("content", "").strip()
        tokens = data.get("tokens_predicted", 0)

        logger.info(
            f"LLM /completion ok latency={latency}ms tokens={tokens} out={text[:120]}",
            extra={
                "endpoint": "/completion",
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system_prompt_preview": system_prompt[:200],
                "prompt_preview": prompt[:200],
                "output": text,
                "tokens_used": tokens,
                "latency_ms": latency,
            },
        )

        return {"text": text, "tokens_used": tokens, "latency_ms": latency}

    async def chat_completion(
        self,
        messages: list[dict],
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> dict:
        """Send chat completion request (OpenAI-compatible /v1/chat/completions)."""
        start = time.time()

        payload = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        system_msg = next((m for m in messages if m.get("role") == "system"), {})
        last_user = next((m for m in reversed(messages) if m.get("role") == "user"), {})

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{self.base_url}/v1/chat/completions", json=payload
                )
                response.raise_for_status()
                data = response.json()
        except Exception as e:
            latency = round((time.time() - start) * 1000, 2)
            metrics.llm_errors_total.labels(endpoint="/v1/chat/completions").inc()
            logger.error(
                f"LLM /v1/chat/completions failed after {latency}ms: {e}",
                extra={
                    "endpoint": "/v1/chat/completions",
                    "messages_count": len(messages),
                    "latency_ms": latency,
                    "error": str(e),
                },
            )
            raise

        latency = round((time.time() - start) * 1000, 2)
        metrics.llm_latency_seconds.labels(endpoint="/v1/chat/completions").observe(latency / 1000)
        choice = data.get("choices", [{}])[0]
        text = choice.get("message", {}).get("content", "").strip()
        tokens = data.get("usage", {}).get("total_tokens", 0)

        logger.info(
            f"LLM /v1/chat/completions ok messages={len(messages)} "
            f"latency={latency}ms tokens={tokens} out={text[:120]}",
            extra={
                "endpoint": "/v1/chat/completions",
                "messages_count": len(messages),
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system_prompt_preview": system_msg.get("content", "")[:200],
                "user_message": last_user.get("content", ""),
                "output": text,
                "tokens_used": tokens,
                "latency_ms": latency,
            },
        )

        return {"text": text, "tokens_used": tokens, "latency_ms": latency}

    async def astream_chat(
        self,
        messages: list[dict],
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ):
        """Stream a chat completion, yielding text deltas as they arrive.

        Uses the OpenAI-compatible SSE format (`data: {...}` lines,
        terminated by `data: [DONE]`) that llama.cpp's server emits.
        """
        payload = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        start = time.time()
        chunks_out = 0

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST", f"{self.base_url}/v1/chat/completions", json=payload
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[len("data:"):].strip()
                        if data == "[DONE]":
                            break
                        try:
                            event = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        delta = (
                            event.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content", "")
                        )
                        if delta:
                            chunks_out += 1
                            yield delta
        except Exception as e:
            latency = round((time.time() - start) * 1000, 2)
            metrics.llm_errors_total.labels(endpoint="/v1/chat/completions:stream").inc()
            logger.error(
                f"LLM stream failed after {latency}ms: {e}",
                extra={
                    "endpoint": "/v1/chat/completions",
                    "stream": True,
                    "latency_ms": latency,
                    "error": str(e),
                },
            )
            raise

        latency = round((time.time() - start) * 1000, 2)
        metrics.llm_latency_seconds.labels(endpoint="/v1/chat/completions:stream").observe(latency / 1000)
        logger.info(
            f"LLM stream ok messages={len(messages)} latency={latency}ms chunks={chunks_out}",
            extra={
                "endpoint": "/v1/chat/completions",
                "stream": True,
                "messages_count": len(messages),
                "latency_ms": latency,
                "chunks": chunks_out,
            },
        )

    async def health_check(self) -> bool:
        """Try llama.cpp /health first, then Ollama /api/tags."""
        for path in ("/health", "/api/tags"):
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(f"{self.base_url}{path}")
                    if resp.status_code == 200:
                        return True
            except Exception:
                continue
        return False

    def _format_prompt(self, system_prompt: str, user_prompt: str) -> str:
        """Format prompt for Gemma 3 chat template.

        Adjust this if you switch models — each model has its own template.
        """
        parts = []
        if system_prompt:
            parts.append(f"<start_of_turn>system\n{system_prompt}<end_of_turn>")
        parts.append(f"<start_of_turn>user\n{user_prompt}<end_of_turn>")
        parts.append("<start_of_turn>model\n")
        return "\n".join(parts)


llm_client = LLMClient()