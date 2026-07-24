"""Phase 2: Prompt builder.

Assembles the final prompt from:
1. System prompt (sector persona)
2. Domain context (intent-specific instructions)
3. Memory (conversation history)
4. RAG context (retrieved documents)
"""

import re

from app.prompts.base_system import get_system_prompt
from app.models.schemas import IntentResult
from app.services.rag_retriever import RAGResult
from app.utils.logger import get_logger

logger = get_logger("prompt")

# Prepended to every persona so replies are consistently short and direct.
BREVITY_RULE = (
    "RESPONSE STYLE:\n"
    "- Reply in ONE to THREE short sentences. Under 60 words.\n"
    "- Skip greetings, apologies, and filler like 'I understand'.\n"
    "- Answer the user's question directly; ask ONE follow-up if needed.\n"
    "- No bullet lists unless the user asks for one."
)

_NO_TRANSLATION_NEEDED = {"", "ENGLISH", "EN", "AUTO"}

# UI entries that want transliterated output use the convention
# "<Language> (Roman script[/ ...])" — e.g. "Hindi (Roman script / Hinglish)".
_ROMAN_SCRIPT_MARKER = re.compile(r"\(roman", re.IGNORECASE)

# A bare "(Roman script)" suffix is not a strong enough signal — verified
# against a live Gemma 3 server that it silently answers in native script
# anyway unless given a concrete negative example. One short example per
# language is enough; languages not listed here still get the (weaker but
# still explicit) generic instruction below.
_ROMANIZATION_EXAMPLES = {
    "hindi": ("aapka order kahan hai", "आपका ऑर्डर कहाँ है"),
    "telugu": ("mee order ekkada undi", "మీ ఆర్డర్ ఎక్కడ ఉంది"),
    "tamil": ("ungal order eppo varum", "உங்கள் ஆர்டர் எப்போ வரும்"),
    "bengali": ("apnar order kothay ache", "আপনার অর্ডার কোথায় আছে"),
    "marathi": ("tumcha order kuthe ahe", "तुमचा ऑर्डर कुठे आहे"),
    "kannada": ("nimma order elli ide", "ನಿಮ್ಮ ಆರ್ಡರ್ ಎಲ್ಲಿ ಇದೆ"),
    "malayalam": ("ningalude order evideya", "നിങ്ങളുടെ ഓർഡർ എവിടെയാണ്"),
    "gujarati": ("tamaru order kya che", "તમારું ઓર્ડર ક્યાં છે"),
    "punjabi": ("tuhada order kithe hai", "ਤੁਹਾਡਾ ਆਰਡਰ ਕਿੱਥੇ ਹੈ"),
    "odia": ("tama order kauthi achi", "ତୁମର ଅର୍ଡର କେଉଁଠି ଅଛି"),
}


def _romanization_instruction(base_lang: str, hint: str) -> str:
    lines = [
        "LANGUAGE:",
        f"- Respond in {base_lang}, but transliterate every word into the Latin/English "
        f"alphabet (this is called romanized {base_lang}).{hint}",
    ]
    example = _ROMANIZATION_EXAMPLES.get(base_lang.lower())
    if example:
        roman_ex, native_ex = example
        lines.append(f'- Example: write "{roman_ex}" — NOT "{native_ex}".')
    lines.append(
        f"- Never write in {base_lang}'s native script — not even one word. If you "
        "catch yourself doing so, stop and rewrite that word using Latin letters instead."
    )
    lines.append("- Do not switch to English or mix languages unless the user did.")
    lines.append(
        "- Do not add an English translation, gloss, or parenthetical explanation "
        "after your reply. Output ONLY the transliterated reply, nothing else."
    )
    return "\n".join(lines)


def language_instruction(user_lang: str, src_lang: str = "") -> str:
    """Tell the LLM what language to reply in.

    Gemma is fluent enough in ~100 languages to translate as part of
    generation, so there's no separate translation-service round trip —
    the LLM reads and writes the user's language directly.
    """
    if not user_lang or user_lang.strip().upper() in _NO_TRANSLATION_NEEDED:
        return "LANGUAGE:\n- Respond in English."

    hint = ""
    if src_lang and src_lang.strip().upper() not in _NO_TRANSLATION_NEEDED:
        hint = f" The user's message itself may be written in {src_lang}."

    roman_match = _ROMAN_SCRIPT_MARKER.search(user_lang)
    if roman_match:
        base_lang = user_lang[: roman_match.start()].strip()
        return _romanization_instruction(base_lang, hint)

    return (
        "LANGUAGE:\n"
        # Deliberately not "...in its native script" — user_lang may itself
        # specify a script/style (e.g. "Hindi (Roman script / Hinglish)",
        # handled above), and asserting native script here would contradict it.
        f"- Respond in {user_lang}.{hint}\n"
        "- Do not switch to English or mix languages unless the user did."
    )


def build_prompt(
    sector: str,
    intent: IntentResult | None = None,
    rag_context: RAGResult | None = None,
    memory: list[dict] | None = None,
    user_lang: str = "ENGLISH",
    src_lang: str = "",
) -> str:
    """Build the complete system prompt for the LLM.

    Combines all context sources into one coherent system prompt.
    The conversation history (memory) goes into the messages array,
    not into the system prompt itself.
    """

    parts = []

    # 0. Language the reply must be written in — checked first since it's
    #    a hard constraint, not a style preference.
    parts.append(language_instruction(user_lang, src_lang))

    # 0b. Global brevity rule — enforced across every persona.
    parts.append(BREVITY_RULE)

    # 1. Base sector system prompt
    parts.append(get_system_prompt(sector))

    # 2. Intent-specific instructions
    if intent and intent.intent != "general_query":
        intent_instruction = _get_intent_instruction(sector, intent)
        if intent_instruction:
            parts.append(f"\nCURRENT TASK: {intent_instruction}")

        # Add extracted parameters
        if intent.params:
            params_str = ", ".join(f"{k}: {v}" for k, v in intent.params.items())
            parts.append(f"EXTRACTED INFO: {params_str}")

    # 3. RAG context
    if rag_context and rag_context.chunks:
        context_text = "\n---\n".join(rag_context.chunks[:3])  # Max 3 chunks
        parts.append(
            f"\nRELEVANT INFORMATION FROM KNOWLEDGE BASE:\n{context_text}\n"
            "Use the above information to answer the user's question. "
            "If the information doesn't fully answer the question, say so."
        )

    # 4. Conversation context hint
    if memory and len(memory) > 0:
        turn_count = len(memory) // 2
        parts.append(
            f"\nCONVERSATION CONTEXT: This is turn {turn_count + 1} of an ongoing conversation. "
            "Refer to previous context when relevant but don't repeat yourself."
        )

    return "\n\n".join(parts)


def _get_intent_instruction(sector: str, intent: IntentResult) -> str:
    """Get specific instructions for handling a detected intent."""

    INTENT_INSTRUCTIONS = {
        "retail": {
            "order_tracking": "The customer wants to track an order. Ask for order ID if not provided, then give a status update.",
            "refund_request": "The customer wants a refund. Confirm the order details, explain the 5-7 business day refund timeline, and ask for preferred refund method.",
            "return_request": "The customer wants to return a product. Confirm the order, check if within 15-day return window, and explain the return pickup process.",
            "product_inquiry": "The customer is asking about a product. Provide details about features, pricing, and availability.",
            "payment_issue": "The customer has a payment problem. Ask for transaction details and offer troubleshooting steps.",
            "complaint": "The customer is unhappy. Acknowledge their frustration sincerely, apologize, and offer a concrete resolution.",
        },
        "medical": {
            "book_appointment": "Help the patient book an appointment. Ask for preferred department/doctor, date, and time slot.",
            "doctor_availability": "Provide doctor schedule information. List available slots for the requested department.",
            "report_collection": "The patient wants their test reports. Ask for the test date and patient ID, then provide collection instructions.",
            "emergency": "THIS IS URGENT. Immediately provide the emergency helpline number and direct to the nearest ER. Do not ask unnecessary questions.",
            "health_package": "Provide information about available health checkup packages with pricing and what's included.",
        },
        "banking": {
            "loan_eligibility": "Help the customer check loan eligibility. Ask for loan type, amount, income, and employment details.",
            "emi_calculation": "Calculate EMI for the customer. Ask for loan amount, tenure, and use 8.5% default interest rate.",
            "transaction_dispute": "The customer is disputing a transaction. Collect transaction date, amount, merchant name. Provide the dispute resolution timeline (7-10 working days).",
            "credit_card": "Handle credit card query. Could be about application, billing, rewards, or blocking a lost card.",
        },
        "education": {
            "course_info": "Provide detailed information about the requested course or program.",
            "admission_process": "Walk the student through the admission process step by step.",
            "fee_inquiry": "Provide fee structure and available payment plans or scholarships.",
        },
        "real_estate": {
            "property_search": "Help find properties. Ask for budget, location preference, and property type.",
            "site_visit": "Schedule a property visit. Collect name, phone, preferred date/time.",
            "emi_calculation": "Calculate home loan EMI. Ask for property value, down payment, and preferred tenure.",
        },
        "tourism": {
            "itinerary_planning": "Help plan a trip. Ask for destination, duration, budget, and travel style.",
            "hotel_recommendation": "Suggest hotels. Ask for destination, budget range, and preferences (luxury/budget/family).",
            "visa_guidance": "Provide visa requirements. Ask for destination country and passport nationality.",
        },
    }

    sector_intents = INTENT_INSTRUCTIONS.get(sector, {})
    return sector_intents.get(intent.intent, "")
