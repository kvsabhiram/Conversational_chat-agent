"""Tests for prompt_builder.language_instruction() — the mechanism that
replaced the translation-service round trip: the LLM is told what
language to reply in and writes it directly."""

import pytest

from app.services.prompt_builder import build_prompt, language_instruction


def test_language_instruction_english_default():
    assert language_instruction("ENGLISH") == "LANGUAGE:\n- Respond in English."
    assert language_instruction("") == "LANGUAGE:\n- Respond in English."
    assert language_instruction("auto") == "LANGUAGE:\n- Respond in English."


def test_language_instruction_non_english():
    instr = language_instruction("Hindi")
    assert "Respond in Hindi" in instr


def test_language_instruction_does_not_assert_native_script_for_plain_languages():
    # A romanized/transliterated variant would contradict a hardcoded
    # "native script" claim for languages requested in native script.
    instr = language_instruction("Tamil")
    assert "native script" not in instr


def test_language_instruction_romanized_variant_gives_explicit_example():
    # A bare "(Roman script)" suffix is not a strong enough signal on its
    # own — verified against a live model that it silently answers in
    # native script anyway. Known romanized languages must get a concrete
    # negative example (native script) vs. positive example (Latin script).
    instr = language_instruction("Hindi (Roman script / Hinglish)")
    assert "Respond in Hindi, but transliterate" in instr
    assert "aapka order kahan hai" in instr
    assert "आपका ऑर्डर कहाँ है" in instr
    assert "Never write in Hindi's native script" in instr
    assert "Do not add an English translation" in instr


def test_language_instruction_romanized_variant_unknown_language_still_explicit():
    # No canned example for this language, but the instruction must still
    # be explicit about not using native script — not silently fall back
    # to the old (buggy) bare "(Roman script)" passthrough.
    instr = language_instruction("Klingon (Roman script)")
    assert "Respond in Klingon, but transliterate" in instr
    assert "Never write in Klingon's native script" in instr


def test_language_instruction_includes_src_hint_when_relevant():
    instr = language_instruction("Hindi", "Hinglish")
    assert "Respond in Hindi" in instr
    assert "Hinglish" in instr


def test_language_instruction_no_src_hint_for_english_or_auto_src():
    instr = language_instruction("Tamil", "auto")
    assert "Tamil" in instr
    assert "auto" not in instr.lower().replace("respond", "")


def test_build_prompt_embeds_language_instruction():
    prompt = build_prompt(sector="retail", user_lang="French")
    assert "Respond in French" in prompt
    # Language instruction should come before the brevity/style rule.
    assert prompt.index("Respond in French") < prompt.index("RESPONSE STYLE")


def test_build_prompt_defaults_to_english():
    prompt = build_prompt(sector="retail")
    assert "Respond in English" in prompt


@pytest.mark.integration
@pytest.mark.asyncio
async def test_romanized_hindi_produces_latin_script_against_live_llm():
    """Requires a live LLM server. Regression test for the bug where a bare
    "(Roman script)" suffix was silently ignored and the model answered in
    native Devanagari script instead of the requested Latin transliteration."""
    from app.services.llm_client import llm_client

    instr = language_instruction("Hindi (Roman script / Hinglish)")
    result = await llm_client.chat_completion(
        messages=[
            {"role": "system", "content": instr + "\n\nYou are a helpful customer support agent."},
            {"role": "user", "content": "Where is my order?"},
        ],
        max_tokens=100,
        temperature=0.3,
    )
    text = result["text"]
    devanagari_chars = [c for c in text if "ऀ" <= c <= "ॿ"]
    assert not devanagari_chars, f"Expected pure Latin script, got Devanagari in: {text!r}"
