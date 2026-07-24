"""Phase 4: Prometheus metric definitions.

Cardinality rule: label values must stay low and bounded. sector (~7),
status (~3), reason (~10), endpoint (~3), direction (~2). Never label
with session_id or tenant_id — either can have unbounded distinct values,
which explodes Prometheus's time-series count and memory use.
"""

from prometheus_client import Counter, Gauge, Histogram

chat_requests_total = Counter(
    "chat_requests_total",
    "Total chat requests handled",
    ["sector", "status"],
)

chat_latency_seconds = Histogram(
    "chat_latency_seconds",
    "Chat pipeline latency by stage",
    ["sector", "stage"],
)

active_llm_slots = Gauge(
    "active_llm_slots",
    "Currently occupied LLM concurrency slots",
)

guardrail_blocks_total = Counter(
    "guardrail_blocks_total",
    "Guardrail blocks/redactions by reason",
    ["reason"],
)

llm_errors_total = Counter(
    "llm_errors_total",
    "LLM backend request errors",
    ["endpoint"],
)

llm_latency_seconds = Histogram(
    "llm_latency_seconds",
    "LLM backend request latency",
    ["endpoint"],
)

translation_failures_total = Counter(
    "translation_failures_total",
    "Translation gateway failures",
    ["src", "tgt"],
)

translation_latency_seconds = Histogram(
    "translation_latency_seconds",
    "Translation gateway request latency",
    ["direction"],
)
